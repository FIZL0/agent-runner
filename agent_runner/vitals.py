"""F95: Device Vitals in Runner Home: is each machine OK to run on?

Each Home samples its own machine every 30 s (`Sampler`): CPU, GPU, memory, disk and temperatures, read with
the standard library from /proc, /sys/class/hwmon and /sys/class/drm on Linux (nvidia-smi when present),
sysctl and vm_stat on macOS, and PowerShell CIM on Windows. What a machine cannot read is left out of the
sample, never set to zero, and the page hides it. A day of samples (`History`, about 300 KB) gives the 24 h
sparklines.

From a sample Home works out:
    headroom   how many more agents fit: the smallest of the memory, CPU-load, disk (against min_free_gb) and
               usage-cap limits (no usage limit while [models] fallback has a free provider), capped at ROOM_MAX
               (`headroom`)
    alerts     the thresholds that need the person: disk under min_free_gb, high temperatures, memory nearly
               full, session temp folders over 5% of the disk after the auto-clean (`alerts`); they show under
               Needs you on Home and go to each running project's events, which its run page and `since` show
               (`Vitals.push_alerts`); a Claude login ending, ended or missing goes the same way once a day
               (`Vitals.push_login`)
    footprint  what agent-runner keeps on disk: worktrees under each run home, session temp folders, logs,
               wip/ branches, each sized (`footprint`), and Clean's safe list (`clean_plan`, `clean`);
               each regular walk removes the ended sessions' temp folders on that list by itself (`auto_clean`)
               and the old build output of projects whose run is off (`build_clean.clean_builds`)
    sessions   CPU and memory per slot and per control session (`session_rows`)

Homes find each other (`peers`): links in the registry (`agent-runner home peer add LINK`) and, when Tailscale
is up, the tailnet's machines whose Home answers to this Home's token. One Home shows every device: its
Devices list fetches each peer's /vitals/device, and a peer's vitals page, Clean and + slot go through
/dev/<id>/... to that peer.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess as sp
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from agent_runner.build_clean import clean_builds
from agent_runner.build_output import held_files, held_key, held_names

GB = 1024 ** 3
EVERY = 30.0             # s between samples
KEEP = 24 * 3600         # s of samples History keeps
SPARK = 96               # points in a sparkline (15 min each over a day)
AGENT_GB = 1.0           # memory one more agent takes
KEEP_FREE_GB = 4.0       # memory left free for everything else
CPU_SHARE = 0.8          # the load average may reach this share of the threads
DISK_GB = 2.0            # disk one more agent's worktree and temp folder take
ROOM_MAX = 6             # the most "room for N more" ever says
HOT_C = 90.0             # a CPU or GPU this hot is an alert
MEM_LOW = 0.10           # less memory free than this share of it is an alert
TMP_ALERT_SHARE = 0.05   # session temp folders past this share of the disk, after the auto-clean, are an alert
ENDED_AFTER = 3600.0     # s with no write before a session temp folder no process names counts as ended
ANY_SID = '*'            # among the waiting sessions: one that cannot be named waits, so none counts as ended
MAIN_ENDED_AFTER = 24 * 3600.0  # the same for a session in a main checkout
FOOTPRINT_EVERY = 600.0  # s between footprint walks
PEER_TIMEOUT = 3.0
SESSION_DIR = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
WORKTREE = re.compile(r's\d+|merge\d*|fix\d+')


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None


def _num(s) -> float | None:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


# --- Linux collectors (each takes the tree to read, so tests hand them a fixture) --------------------------------

def linux_cpu_ticks(proc: Path = Path('/proc')) -> dict | None:
    """/proc/stat's CPU lines as {'all': (busy, total), 'cores': [(busy, total), ...]}, None when unreadable."""
    text = _read(proc / 'stat')
    if not text:
        return None
    out: dict = {'cores': []}
    for line in text.splitlines():
        parts = line.split()
        if not parts or not parts[0].startswith('cpu'):
            continue
        try:
            v = [int(x) for x in parts[1:]]
        except ValueError:
            continue
        idle = v[3] + (v[4] if len(v) > 4 else 0)  # idle + iowait
        total = sum(v[:8])  # guest time is already in user
        if parts[0] == 'cpu':
            out['all'] = (total - idle, total)
        else:
            out['cores'].append((total - idle, total))
    return out if 'all' in out else None


def busy_pct(prev: tuple[int, int] | None, now: tuple[int, int] | None) -> float | None:
    if not prev or not now or now[1] <= prev[1]:
        return None
    return round(max(0.0, min(100.0, 100.0 * (now[0] - prev[0]) / (now[1] - prev[1]))), 1)


def linux_mem(proc: Path = Path('/proc')) -> dict | None:
    """{'total', 'avail'} in bytes from /proc/meminfo (MemAvailable), None when unreadable."""
    text = _read(proc / 'meminfo')
    if not text:
        return None
    kb = {}
    for line in text.splitlines():
        k, _, v = line.partition(':')
        if (n := _num(v.split()[0] if v.split() else '')) is not None:
            kb[k.strip()] = n * 1024
    if 'MemTotal' not in kb or 'MemAvailable' not in kb:
        return None
    return {'total': int(kb['MemTotal']), 'avail': int(kb['MemAvailable'])}


def linux_load(proc: Path = Path('/proc')) -> float | None:
    text = _read(proc / 'loadavg')
    return _num(text.split()[0]) if text and text.split() else None


def hwmon_sensors(sysfs: Path = Path('/sys')) -> list[dict]:
    """Every temperature /sys/class/hwmon has: [{'chip', 'label', 'c'}]."""
    out = []
    base = sysfs / 'class' / 'hwmon'
    try:
        mons = sorted(base.iterdir(), key=lambda p: p.name)
    except OSError:
        return out
    for mon in mons:
        chip = (_read(mon / 'name') or mon.name).strip()
        try:
            inputs = sorted(mon.glob('temp*_input'), key=lambda p: p.name)
        except OSError:
            continue
        for f in inputs:
            v = _num(_read(f))
            if v is None:
                continue
            n = f.name[:-len('_input')]
            label = (_read(mon / f'{n}_label') or n).strip()
            out.append({'chip': chip, 'label': label, 'c': round(v / 1000.0, 1)})
    return out


CPU_CHIPS = ('k10temp', 'coretemp', 'zenpower', 'cpu_thermal', 'cpu-thermal', 'soc_thermal', 'x86_pkg_temp')
CPU_LABELS = ('tctl', 'tdie', 'package id 0', 'cpu')


def cpu_temp(sensors: list[dict]) -> float | None:
    """The CPU's temperature from the hwmon sensors: Tctl or Package id 0 when there, else the hottest CPU
    sensor; None when no sensor is a CPU's."""
    mine = [s for s in sensors if s['chip'].lower() in CPU_CHIPS]
    for want in CPU_LABELS:
        hit = [s['c'] for s in mine if s['label'].lower() == want]
        if hit:
            return max(hit)
    return max((s['c'] for s in mine), default=None)


def drm_gpus(sysfs: Path = Path('/sys')) -> list[dict]:
    """GPUs /sys/class/drm describes (amdgpu, i915/xe where they report): [{'name', 'pct', 'temp',
    'vram_used', 'vram_total'}], each key only when read."""
    out = []
    try:
        cards = sorted(p for p in (sysfs / 'class' / 'drm').iterdir() if re.fullmatch(r'card\d+', p.name))
    except OSError:
        return out
    for card in cards:
        dev = card / 'device'
        g: dict = {}
        if (v := _num(_read(dev / 'gpu_busy_percent'))) is not None:
            g['pct'] = v
        used, total = _num(_read(dev / 'mem_info_vram_used')), _num(_read(dev / 'mem_info_vram_total'))
        if used is not None and total:
            g['vram_used'], g['vram_total'] = int(used), int(total)
        temps = [s['c'] for s in hwmon_sensors_under(dev)]
        if temps:
            g['temp'] = max(temps)
        if g:
            drv = _read(dev / 'uevent') or ''
            m = re.search(r'^DRIVER=(\S+)', drv, re.M)
            g['name'] = m[1] if m else card.name
            out.append(g)
    return out


def hwmon_sensors_under(dev: Path) -> list[dict]:
    """The temperatures a device's own hwmon folder holds (a GPU's)."""
    out = []
    try:
        mons = list((dev / 'hwmon').iterdir())
    except OSError:
        return out
    for mon in mons:
        for f in mon.glob('temp*_input'):
            if (v := _num(_read(f))) is not None:
                out.append({'chip': 'gpu', 'label': f.name, 'c': round(v / 1000.0, 1)})
    return out


def nvidia_gpus(run=sp.run) -> list[dict]:
    """NVIDIA GPUs from nvidia-smi, when it is on PATH: [{'name', 'pct', 'temp', 'vram_used', 'vram_total'}]."""
    if not shutil.which('nvidia-smi') and run is sp.run:
        return []
    try:
        r = run(['nvidia-smi', '--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total',
                 '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=10)
    except (OSError, sp.SubprocessError):
        return []
    if r.returncode:
        return []
    out = []
    for line in r.stdout.splitlines():
        f = [x.strip() for x in line.split(',')]
        if len(f) < 5:
            continue
        g: dict = {'name': f[0]}
        for k, v in (('pct', f[1]), ('temp', f[2])):
            if (n := _num(v)) is not None:
                g[k] = n
        used, total = _num(f[3]), _num(f[4])
        if used is not None and total:
            g['vram_used'], g['vram_total'] = int(used * 2**20), int(total * 2**20)
        out.append(g)
    return out


def proc_table(proc: Path = Path('/proc')) -> dict[int, tuple[int, int, int, str]]:
    """{pid: (ppid, cpu ticks, resident bytes, name)} of every process /proc shows."""
    out = {}
    page = page_size()
    try:
        entries = [d for d in proc.iterdir() if d.name.isdigit()]
    except OSError:
        return out
    for d in entries:
        stat = _read(d / 'stat')
        if not stat or ')' not in stat:
            continue
        name = stat[stat.find('(') + 1:stat.rfind(')')]
        f = stat[stat.rfind(')') + 2:].split()
        try:
            ppid, ticks = int(f[1]), int(f[11]) + int(f[12])
            rss = int(f[21]) * page
        except (IndexError, ValueError):
            continue
        out[int(d.name)] = (ppid, ticks, rss, name)
    return out


def page_size() -> int:
    """The memory page size /proc counts resident pages in; Windows has no os.sysconf, so 4096 there."""
    try:
        return os.sysconf('SC_PAGE_SIZE')
    except (AttributeError, ValueError, OSError):
        return 4096


def clock_ticks() -> int:
    try:
        return os.sysconf('SC_CLK_TCK')
    except (AttributeError, ValueError, OSError):
        return 100


# --- macOS and Windows -----------------------------------------------------------------------------------------

def mac_stats(run=sp.run) -> dict:
    """{'threads', 'load', 'mem': {'total', 'avail'}, 'pct'} from sysctl, vm_stat and ps; keys only when read."""
    out: dict = {}

    def cmd(argv):
        try:
            r = run(argv, capture_output=True, text=True, timeout=10)
            return r.stdout if r.returncode == 0 else ''
        except (OSError, sp.SubprocessError):
            return ''

    s = cmd(['sysctl', '-n', 'hw.ncpu', 'hw.memsize', 'vm.loadavg']).split('\n')
    if len(s) >= 3:
        if (n := _num(s[0])) is not None:
            out['threads'] = int(n)
        total = _num(s[1])
        m = re.search(r'([\d.]+)', s[2])
        if m:
            out['load'] = float(m[1])
        vm = cmd(['vm_stat'])
        ps = re.search(r'page size of (\d+)', vm)
        pages = {k.strip(): int(v.strip().rstrip('.')) for k, v in re.findall(r'^([^:]+):\s+(\d+)\.?$', vm, re.M)}
        if total and ps and pages:
            free = sum(pages.get(k, 0) for k in ('Pages free', 'Pages inactive', 'Pages speculative'))
            out['mem'] = {'total': int(total), 'avail': free * int(ps[1])}
    cpu = cmd(['ps', '-A', '-o', '%cpu='])
    if cpu and out.get('threads'):
        tot = sum(v for v in (_num(x) for x in cpu.split()) if v is not None)
        out['pct'] = round(min(100.0, tot / out['threads']), 1)
    return out


WIN_PS = ('$o=Get-CimInstance Win32_OperatingSystem;$p=@(Get-CimInstance Win32_Processor);'
          '[pscustomobject]@{free=$o.FreePhysicalMemory;total=$o.TotalVisibleMemorySize;'
          'pct=($p|Measure-Object LoadPercentage -Average).Average;'
          'threads=($p|Measure-Object NumberOfLogicalProcessors -Sum).Sum}|ConvertTo-Json -Compress')


def windows_stats(run=sp.run) -> dict:
    """{'threads', 'pct', 'load', 'mem'} from PowerShell CIM; keys only when read."""
    try:
        r = run(['powershell', '-NoProfile', '-NonInteractive', '-Command', WIN_PS],
                capture_output=True, text=True, timeout=20)
        d = json.loads(r.stdout) if r.returncode == 0 else {}
    except (OSError, sp.SubprocessError, ValueError):
        d = {}
    out: dict = {}
    if not isinstance(d, dict):
        return out
    if (n := _num(d.get('threads'))) is not None:
        out['threads'] = int(n)
    if (p := _num(d.get('pct'))) is not None:
        out['pct'] = p
        if out.get('threads'):
            out['load'] = round(out['threads'] * p / 100.0, 2)  # no load average: busy threads stand in
    free, total = _num(d.get('free')), _num(d.get('total'))
    if free is not None and total:
        out['mem'] = {'total': int(total * 1024), 'avail': int(free * 1024)}
    return out


# --- one sample of the machine ---------------------------------------------------------------------------------

def os_name(platform: str | None = None) -> str:
    p = platform or sys.platform
    return 'windows' if p.startswith('win') else 'macos' if p == 'darwin' else 'linux'


class Sampler:
    """Samples this machine. CPU busy and per-process CPU need two looks, so it keeps the last one: the first
    sample has no 'pct' (hidden, not zero)."""

    def __init__(self, proc: Path = Path('/proc'), sysfs: Path = Path('/sys'), platform: str | None = None,
                 run=sp.run, disk: Path | None = None):
        self.proc, self.sysfs, self.os, self.run = proc, sysfs, os_name(platform), run
        self.disk = disk or Path.home()
        self.prev_cpu: dict | None = None
        self.prev_procs: tuple[float, dict] | None = None
        self.procs: dict = {}
        self.proc_cpu: dict[int, float] = {}  # pid -> % of the machine over the last interval

    def sample(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        snap: dict = {'host': socket.gethostname(), 'os': self.os, 't': round(now)}
        cpu: dict = {}
        if self.os == 'linux':
            ticks = linux_cpu_ticks(self.proc)
            if ticks:
                cpu['threads'] = len(ticks['cores']) or os.cpu_count() or 1
                if self.prev_cpu:
                    if (p := busy_pct(self.prev_cpu.get('all'), ticks['all'])) is not None:
                        cpu['pct'] = p
                    cores = [busy_pct(a, b) for a, b in zip(self.prev_cpu['cores'], ticks['cores'])]
                    if cores and None not in cores:
                        cpu['cores'] = cores
                self.prev_cpu = ticks
            if (l := linux_load(self.proc)) is not None:
                cpu['load'] = l
            if mem := linux_mem(self.proc):
                snap['mem'] = mem
            sensors = hwmon_sensors(self.sysfs)
            if sensors:
                snap['sensors'] = sensors
                if (t := cpu_temp(sensors)) is not None:
                    cpu['temp'] = t
            gpus = sorted(drm_gpus(self.sysfs) + nvidia_gpus(self.run), key=lambda g: -g.get('vram_total', 0))
            if gpus:
                snap['gpus'] = gpus
            self.sample_procs(now, cpu.get('threads') or os.cpu_count() or 1)
        else:
            st = mac_stats(self.run) if self.os == 'macos' else windows_stats(self.run)
            cpu.update({k: st[k] for k in ('threads', 'load', 'pct') if k in st})
            if 'mem' in st:
                snap['mem'] = st['mem']
        if cpu:
            snap['cpu'] = cpu
        try:
            du = shutil.disk_usage(self.disk)
            snap['disk'] = {'path': str(self.disk), 'total': du.total, 'free': du.free}
        except OSError:
            pass
        if self.proc_cpu:
            top = sorted(self.procs, key=lambda p: (-self.proc_cpu.get(p, 0.0), -self.procs[p][2]))[:8]
            snap['top'] = [{'pid': p, 'name': self.procs[p][3], 'cpu': round(self.proc_cpu.get(p, 0.0), 1),
                            'rss': self.procs[p][2]} for p in top]
        return snap

    def sample_procs(self, now: float, threads: int) -> None:
        table = proc_table(self.proc)
        if self.prev_procs and now > self.prev_procs[0]:
            then, old = self.prev_procs
            span = (now - then) * clock_ticks() * threads
            self.proc_cpu = {p: max(0.0, 100.0 * (v[1] - old[p][1]) / span) for p, v in table.items() if p in old}
        self.prev_procs, self.procs = (now, table), table


def tree_usage(pid: int, procs: dict, cpu: dict[int, float]) -> tuple[float, int] | None:
    """(CPU % of the machine, resident bytes) of `pid` and every process under it; None when it is gone."""
    if pid not in procs:
        return None
    kids: dict[int, list[int]] = {}
    for p, v in procs.items():
        kids.setdefault(v[0], []).append(p)
    seen, todo, c, rss = set(), [pid], 0.0, 0
    while todo:
        p = todo.pop()
        if p in seen or p not in procs:
            continue
        seen.add(p)
        c += cpu.get(p, 0.0)
        rss += procs[p][2]
        todo += kids.get(p, [])
    return round(c, 1), rss


# --- headroom and alerts ---------------------------------------------------------------------------------------

LIMIT_WORDS = {'memory': 'memory is nearly full', 'cpu': 'the CPU is busy',
               'disk': 'the disk is near min_free_gb', 'usage': 'a usage cap is reached'}


def free_fallback(c) -> bool:
    """F142: `c`'s [models] fallback has an entry a new task can start on past the usage caps: not claude's, its
    provider not capped and logged in (fallback.chain_next, for any project's config). F406h: or none of its sessions runs on
    claude, so the caps hold nothing."""
    from agent_runner.claude_use import uses
    if not uses(c):
        return True
    from agent_runner.config import harness_model
    from agent_runner.login import missing
    try:
        capped = json.loads(c.notes('capped.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        capped = {}
    if not isinstance(capped, dict):
        capped = {}
    now = time.time()
    held = {p for p, u in capped.items() if isinstance(u, (int, float)) and u > now}
    return any(harness_model(m, c.providers) and m.partition(':')[0] not in held and not missing(m, c)
               for m in c.fallback)


def past_caps(usage: dict | None, caps: dict | None) -> bool:
    """The session or weekly usage is at or past its cap."""
    for name, cap_key in (('session', 'session_max'), ('weekly', 'weekly_max')):
        pct, cap = (usage or {}).get(name), (caps or {}).get(cap_key)
        if pct is not None and cap and pct >= cap:
            return True
    return False


def headroom(snap: dict, min_free_gb: float = 10, usage: dict | None = None, caps: dict | None = None,
             fallback: bool = False) -> dict:
    """How many more agents fit: {'room' (None when nothing could be read), 'by' (the limit that set it),
    'limits' ({memory|cpu|disk|usage: n}, only those read), 'said'}.

        memory  (available - KEEP_FREE_GB) / AGENT_GB
        cpu     threads * CPU_SHARE - load average
        disk    (free - min_free_gb) / DISK_GB
        usage   0 once the session or weekly usage reaches its cap (session_max, weekly_max), else no limit;
                no limit either with `fallback` (new tasks start down [models] fallback): 'said' tells it
    The smallest wins, capped at ROOM_MAX."""
    limits: dict[str, int] = {}
    if mem := snap.get('mem'):
        limits['memory'] = max(0, int((mem['avail'] / GB - KEEP_FREE_GB) // AGENT_GB))
    cpu = snap.get('cpu') or {}
    if 'threads' in cpu and 'load' in cpu:
        limits['cpu'] = max(0, int(cpu['threads'] * CPU_SHARE - cpu['load']))
    if (disk := snap.get('disk')) and min_free_gb is not None:
        limits['disk'] = max(0, int((disk['free'] / GB - (min_free_gb or 0)) // DISK_GB))
    over = past_caps(usage, caps)
    if over and not fallback:
        limits['usage'] = 0
    if not limits:
        return {'room': None, 'by': '', 'limits': {}, 'said': 'Headroom unknown: nothing here could be read' + (
            f'; {LIMIT_WORDS["usage"]}, new tasks start down [models] fallback' if over else '')}
    by = min(limits, key=lambda k: limits[k])
    room = min(limits[by], ROOM_MAX)
    said = (f'Room for {room} more agent{"" if room == 1 else "s"}' if room
            else f'No room for another agent: {LIMIT_WORDS[by]}')
    if over and room:
        said += f', on [models] fallback: {LIMIT_WORDS["usage"]}'
    return {'room': room, 'by': by if limits[by] <= ROOM_MAX else '', 'limits': limits, 'said': said}


def alerts(snap: dict, min_free_gb: float = 10, foot: dict | None = None) -> list[dict]:
    """The thresholds crossed: [{'id', 'what', 'clean' (Clean helps)}]. `id` stays the same while the
    problem lasts, so it is pushed once. `foot` is the footprint: its session temp folders are an alert past
    TMP_ALERT_SHARE of the disk, and offer Clean only when its list has one to free."""
    host, out = snap.get('host', 'this machine'), []
    if (d := snap.get('disk')) and min_free_gb and d['free'] / GB < min_free_gb:
        out.append({'id': f'{host}:disk', 'clean': True,
                    'what': f'{host}: {d["free"] / GB:.1f} GB free on disk, under min_free_gb ({min_free_gb} GB): '
                            f'no new task starts'})
    hot = [('CPU', (snap.get('cpu') or {}).get('temp'))]
    hot += [(f'GPU {g.get("name", "")}'.strip(), g.get('temp')) for g in snap.get('gpus') or []]
    for what, c in hot:
        if c is not None and c >= HOT_C:
            out.append({'id': f'{host}:hot:{what}', 'clean': False,
                        'what': f'{host}: {what} at {c:.0f}°C (over {HOT_C:.0f}°C)'})
    if (m := snap.get('mem')) and m['total'] and m['avail'] / m['total'] < MEM_LOW:
        out.append({'id': f'{host}:memory', 'clean': False,
                    'what': f'{host}: memory nearly full, {m["avail"] / GB:.1f} GB free of {m["total"] / GB:.0f} GB'})
    tmp = (foot or {}).get('tmp')
    if tmp is not None and (d := snap.get('disk')) and d.get('total') and tmp > TMP_ALERT_SHARE * d['total']:
        said = (f'{host}: session temp folders use {size_words(tmp)} '
                f'(over {TMP_ALERT_SHARE:.0%} of the {size_words(d["total"])} disk)')
        if big := foot.get('tmp_largest'):
            said += f'; the largest is {big["path"]} ({size_words(big["size"])})'
        can = any(i['kind'] == 'tmp' for i in foot.get('clean') or [])
        out.append({'id': f'{host}:tmp', 'clean': can,
                    'what': said + ('. Clean frees the ended sessions\'' if can else '')})
    return out


def verdict(room: dict, found: list[dict]) -> dict:
    """A device card's one line: its top alert, else its headroom. {'said', 'level': ok|warn|bad}."""
    if found:
        return {'said': found[0]['what'].split(': ', 1)[-1], 'level': 'bad'}
    if room.get('room') is None:
        return {'said': room['said'], 'level': 'warn'}
    return {'said': room['said'], 'level': 'ok' if room['room'] else 'warn'}


def meters(snap: dict) -> list[dict]:
    """The card's meters: [{'name', 'pct', 'said'}], only for what was read."""
    out = []
    cpu = snap.get('cpu') or {}
    if 'pct' in cpu:
        out.append({'name': 'CPU', 'pct': cpu['pct'],
                    'said': f'{cpu["pct"]:.0f}%' + (f' {cpu["temp"]:.0f}°' if 'temp' in cpu else '')})
    for g in (snap.get('gpus') or [])[:1]:
        if 'pct' in g:
            out.append({'name': 'GPU', 'pct': g['pct'],
                        'said': f'{g["pct"]:.0f}%' + (f' {g["temp"]:.0f}°' if 'temp' in g else '')})
    if m := snap.get('mem'):
        used = m['total'] - m['avail']
        out.append({'name': 'RAM', 'pct': round(100 * used / m['total'], 1) if m['total'] else 0,
                    'said': f'{used / GB:.0f}/{m["total"] / GB:.0f} GB'})
    if d := snap.get('disk'):
        out.append({'name': 'Disk', 'pct': round(100 * (1 - d['free'] / d['total']), 1) if d['total'] else 0,
                    'said': f'{size_words(d["free"])} free'})
    return out


def size_words(n: int | float | None) -> str:
    if n is None:
        return ''
    for unit, k in (('TB', 1024 ** 4), ('GB', GB), ('MB', 2 ** 20), ('KB', 1024)):
        if n >= k:
            v = n / k
            return f'{v:.1f} {unit}' if v < 10 else f'{v:.0f} {unit}'
    return f'{int(n)} B'


# --- history ---------------------------------------------------------------------------------------------------

def point(snap: dict) -> dict:
    """What History keeps of a sample: {'t', 'cpu', 'gpu', 'mem' (% used), 'disk' (GB free), 'temp'}."""
    p: dict = {'t': snap['t']}
    cpu = snap.get('cpu') or {}
    if 'pct' in cpu:
        p['cpu'] = cpu['pct']
    if 'temp' in cpu:
        p['temp'] = cpu['temp']
    g = (snap.get('gpus') or [{}])[0]
    if 'pct' in g:
        p['gpu'] = g['pct']
    if 'temp' in g:
        p['gtemp'] = g['temp']
    if (m := snap.get('mem')) and m['total']:
        p['mem'] = round(100 * (m['total'] - m['avail']) / m['total'], 1)
    if d := snap.get('disk'):
        p['disk'] = round(d['free'] / GB, 1)
    return p


class History:
    """A day of points, one JSON line each in `path` (rewritten without the old ones as it doubles)."""

    def __init__(self, path: Path | None, keep: float = KEEP):
        self.path, self.keep, self.points, self.lock = path, keep, [], threading.Lock()
        if path:
            for line in (_read(path) or '').splitlines():
                try:
                    p = json.loads(line)
                except ValueError:
                    continue
                if isinstance(p, dict) and isinstance(p.get('t'), (int, float)):
                    self.points.append(p)

    def add(self, p: dict) -> None:
        with self.lock:
            self.points.append(p)
            cut = p['t'] - self.keep
            old = len(self.points)
            self.points = [x for x in self.points if x['t'] >= cut]
            if not self.path:
                return
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if old > len(self.points) and self.path.exists() and \
                        self.path.stat().st_size > 2 * 100 * max(1, len(self.points)):
                    tmp = self.path.with_name(self.path.name + '.tmp')
                    tmp.write_text(''.join(json.dumps(x) + '\n' for x in self.points), encoding='utf-8')
                    os.replace(tmp, self.path)
                else:
                    with open(self.path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(p) + '\n')
            except OSError:
                pass

    def series(self, key: str, now: float | None = None, n: int = SPARK) -> list[float | None]:
        """`key` over the last day in `n` buckets, each the mean of its points (None where none)."""
        now = time.time() if now is None else now
        start, step = now - self.keep, self.keep / n
        sums, counts = [0.0] * n, [0] * n
        with self.lock:
            for p in self.points:
                if key in p and p['t'] >= start:
                    i = min(n - 1, int((p['t'] - start) // step))
                    sums[i] += p[key]
                    counts[i] += 1
        return [round(s / c, 1) if c else None for s, c in zip(sums, counts)]


# --- the runner's footprint and Clean -----------------------------------------------------------------------------

def du(p: Path) -> int:
    """Bytes under `p` (symlinks not followed)."""
    total = 0
    for top, dirs, files in os.walk(p, onerror=lambda e: None):
        for name in files:
            try:
                total += os.lstat(os.path.join(top, name)).st_size
            except OSError:
                pass
    return total


def newest_write(d: Path) -> float:
    try:
        newest = d.stat().st_mtime
    except OSError:
        return time.time()
    for top, dirs, files in os.walk(d, onerror=lambda e: None):
        for name in dirs + files:
            try:
                newest = max(newest, os.lstat(os.path.join(top, name)).st_mtime)
            except OSError:
                pass
    return newest


def git_out(cwd: Path, *args: str) -> str | None:
    try:
        r = sp.run(['git', *args], cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, sp.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def slug(p: Path) -> str:
    """Claude Code's folder name for a working directory: every character but [A-Za-z0-9] as '-'."""
    return re.sub(r'[^A-Za-z0-9]', '-', str(p.resolve()))


def live_session_ids(proc: Path = Path('/proc')) -> set[str] | None:
    """The session ids any running process names on its command line (an agent's --session-id or --resume);
    None where there is no /proc to tell (then no temp folder counts as ended)."""
    try:
        entries = [d for d in proc.iterdir() if d.name.isdigit()]
    except OSError:
        return None
    out: set[str] = set()
    for d in entries:
        try:
            out.update(SESSION_DIR.findall((d / 'cmdline').read_bytes().decode(errors='replace')))
        except OSError:
            continue
    return out


def open_sessions(proc: Path = Path('/proc'), registry: Path | None = None) -> tuple[set[str], bool]:
    """(the session ids Claude Code's registry says are open, whether it could be read in full). Each session has
    a `<pid>.json` there (`feed.claude_sessions_dir`) and is open while that pid is alive with the start time the
    entry gives as procStart. Not in full: no registry, or an entry of a live pid that cannot be read; a session
    that names no id on its command line (a person's own) may then be open unseen."""
    if registry is None:
        from agent_runner.feed import claude_sessions_dir
        registry = claude_sessions_dir()
    out: set[str] = set()
    full = True
    try:
        entries = [f for f in registry.iterdir() if f.suffix == '.json']
    except OSError:
        return out, False
    for f in entries:
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
            pid, sid = int(d['pid']), str(d['sessionId'])
            if not SESSION_DIR.fullmatch(sid):
                raise ValueError(sid)
        except (OSError, ValueError, KeyError, TypeError):
            if f.stem.isdigit() and (proc / f.stem).is_dir():
                full = False
            continue
        if not (proc / str(pid)).is_dir():
            continue
        start, said = proc_start(proc, pid), d.get('procStart')
        if start is None or said is None or str(said) == start:  # not told apart: counts as open
            out.add(sid)
    return out, full


def proc_start(proc: Path, pid: int) -> str | None:
    """When `pid` started (clock ticks since boot, as Claude Code's procStart): /proc's stat, field 22."""
    stat = _read(proc / str(pid) / 'stat')
    try:
        return stat.rsplit(')', 1)[1].split()[19] if stat else None
    except IndexError:
        return None


def live_now(proc: Path = Path('/proc'), registry: Path | None = None) -> tuple[set[str] | None, bool]:
    """(the live sessions' ids: those a process names and those the registry has open, whether the registry was
    read in full); (None, False) with no /proc to tell."""
    live = live_session_ids(proc)
    if live is None:
        return None, False
    ids, full = open_sessions(proc, registry)
    return live | ids, full


def waiting_sids(p: 'Project') -> set[str]:
    """The sessions of `p` the runner will resume or wake, whose temp folders stay: those queued to resume
    (<ID>.resume), those whose ask waits for the person's answer (<ID>.ask), those waiting for a shared tool (<ID>.wait), the last session of a slot worktree
    still on its task/ branch (the next run start resumes one that was cut off), the runner feed's, and cN's while its pid file is there (reopened after a shutdown). ANY_SID is among them when a
    resume or ask cannot be read: any session may be the one it names."""
    out = set(p.resume)
    for f in [*p.notes.glob('*.resume'), *p.notes.glob('*.ask'), *p.notes.glob('*.wait')]:
        try:
            out.add(str(json.loads(f.read_text(encoding='utf-8'))['sid']))
        except FileNotFoundError:
            continue  # resumed meanwhile
        except (OSError, ValueError, KeyError, TypeError):
            if not re.fullmatch(r'control\d+\.ask', f.name):  # that one marks a session opened for one ask
                out.add(ANY_SID)
    kept = [p.notes / 'remote' / 'feed.sid']
    for f in p.notes.glob('control*.pid'):
        kept += [f, f.with_suffix('.sid')]
    for f in kept:
        out.update(SESSION_DIR.findall(_read(f) or ''))
    for d in _dirs(p.home):
        if re.fullmatch(r's\d+', d.name) and (b := git_out(d, 'branch', '--show-current') or '').startswith('task/'):
            if sid := slot_session(p.notes / f'slot{d.name[1:]}.log', b.removeprefix('task/')):
                out.add(sid)
    return out


def slot_session(log: Path, tid: str) -> str:
    """Task `tid`'s latest session in a slot's log, by its header lines; '' for none."""
    from agent_runner.watch import HEADER
    sid = ''
    try:
        with open(log, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if (m := HEADER.match(line)) and m.group(2) == tid:
                    sid = m.group(3)
    except OSError:
        pass
    return sid


def busy_dirs(proc: Path = Path('/proc')) -> list[str]:
    """The working folder of every process: a worktree one is in is not Clean's to remove."""
    out = []
    try:
        entries = [d for d in proc.iterdir() if d.name.isdigit()]
    except OSError:
        return out
    for d in entries:
        try:
            out.append(os.readlink(d / 'cwd'))
        except OSError:
            continue
    return out


class Project:
    """What the footprint needs of one project: its main checkout, run home, notes, main branch, the slots its
    run has busy and the sessions waiting to resume."""

    def __init__(self, root: Path, home: Path, notes: Path, main: str, up: bool, busy: set[str],
                 resume: set[str], min_free_gb: float = 10, caps: dict | None = None, fallback: bool = False,
                 agent: str = 'claude'):
        self.fallback, self.agent = fallback, agent
        self.root, self.home, self.notes, self.main, self.up = root, home, notes, main, up
        self.busy, self.resume, self.min_free_gb, self.caps = busy, resume, min_free_gb, caps or {}

    @classmethod
    def of(cls, root: Path, info=None) -> 'Project | None':
        try:
            from agent_runner.config import Config
            c = Config(root)
            home, notes = c.home, c.notes()
            main = c.master_branch or git_out(root, 'branch', '--show-current') or 'main'
            from agent_runner.claude_use import uses
            used = uses(c)  # F406h: no session on claude: its login and caps are nothing to it
            mff, caps = c.run.get('min_free_gb', 10), {k: c.run.get(k) for k in ('weekly_max', 'session_max')} if used else {}
            fallback, agent = free_fallback(c), (c.run.get('agent') or 'claude') if used else ''
        except (OSError, SystemExit, ValueError, KeyError, TypeError):
            return None
        if info is None:
            from agent_runner.cmds import run_info as info
        run = info(root) or {}
        busy = {f's{k}' for k, v in (run.get('running') or {}).items() if v} if run.get('up') else set()
        resume = set()
        try:
            for f in notes.glob('*.resume'):
                try:
                    resume.add(str(json.loads(f.read_text(encoding='utf-8'))['sid']))
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        except OSError:
            pass
        return cls(root, home, notes, main, bool(run.get('up')), busy, resume, mff, caps, fallback, agent)


def tmp_roots(projects: list[Project]) -> list[Path]:
    """Where Claude Code keeps per-session temp folders (`<root>/claude-<uid>/<project slug>/<session>/`):
    CLAUDE_CODE_TMPDIR, each run home's tmp, the system temp folder."""
    import tempfile
    roots = [os.environ.get('CLAUDE_CODE_TMPDIR'), *(str(p.home / 'tmp') for p in projects),
             tempfile.gettempdir(), '/tmp']
    seen, out = set(), []
    for r in roots:
        if r and (rp := Path(r)).is_dir() and str(rp.resolve()) not in seen:
            seen.add(str(rp.resolve()))
            out.append(rp)
    return out


def session_folders(projects: list[Project], roots: list[Path], main: bool = False) -> list[tuple[Project, Path]]:
    """Each session temp folder of a runner worktree (s1…, merge, fix…) of these projects; `main`: those of
    the main checkouts instead (control sessions, and the person's own sessions there)."""
    if main:
        mine = {slug(p.root): p for p in projects}
    else:
        mine = {slug(p.home / d.name): p for p in projects for d in _dirs(p.home) if WORKTREE.fullmatch(d.name)}
    out = []
    for root in roots:
        for proj in root.glob('claude-*/*'):
            if (p := mine.get(proj.name)) is None or not inside(root, proj):
                continue
            out += [(p, d) for d in _dirs(proj) if SESSION_DIR.fullmatch(d.name)]
    return out


def inside(root: Path, d: Path) -> bool:
    """Is `d` really where its path says under `root`: no symlink on the way?"""
    try:
        return d.resolve() == root.resolve() / d.relative_to(root)
    except (OSError, ValueError, RuntimeError):
        return False


def _dirs(p: Path) -> list[Path]:
    try:
        return sorted(d for d in p.iterdir() if d.is_dir() and not d.is_symlink())
    except OSError:
        return []


def footprint(projects: list[Project], live: set[str] | None, now: float | None = None,
              size=du, written=newest_write, cwds: list[str] | None = None, registry: bool = False) -> dict:
    """What agent-runner keeps on this machine: {'worktrees', 'tmp', 'logs': bytes, 'wip': [branches],
    'total', 'largest': [{'path', 'size'}], 'tmp_largest': the largest session temp folder or None, 'clean':
    Clean's list}. `live` and `registry` are `live_now`'s answer."""
    now = time.time() if now is None else now
    out = {'worktrees': 0, 'tmp': 0, 'logs': 0, 'wip': [], 'largest': []}
    sized: list[dict] = []
    trees: list[tuple[Project, Path, int]] = []
    for p in projects:
        for d in _dirs(p.home):
            n = size(d)
            sized.append({'path': str(d), 'size': n})
            if WORKTREE.fullmatch(d.name):
                out['worktrees'] += n
                trees.append((p, d, n))
        for f in [*p.notes.glob('*.log'), p.notes / 'events.jsonl']:
            try:
                out['logs'] += f.stat().st_size
            except OSError:
                pass
        refs = git_out(p.root, 'for-each-ref', '--format=%(refname:short)', 'refs/heads/wip/')
        out['wip'] += [{'project': p.root.name, 'root': str(p.root), 'branch': b} for b in (refs or '').split() if b]
    temps, out['dirs'], out['tmps'] = [], sized, []
    for main in (False, True):
        for p, d in session_folders(projects, tmp_roots(projects), main):
            n = size(d)
            out['tmp'] += n
            out['tmps'].append({'path': str(d), 'size': n})
            temps.append((p, d, n, main))
    waits = set().union(*(waiting_sids(p) for p in projects))
    rank(out)
    out['total'] = out['worktrees'] + out['tmp'] + out['logs']
    out['clean'] = clean_plan(trees, temps, out['wip'], live, now, written, cwds, registry=registry, waits=waits)
    return out


def clean_plan(trees, temps, wips, live: set[str] | None, now: float, written=newest_write,
               cwds: list[str] | None = None, merged=None, registry: bool = False,
               waits: set[str] = frozenset()) -> list[dict]:
    """Clean's safe list, shown before anything is removed: [{'id', 'kind', 'path', 'size', 'why', 'ask'
    (only when the person ticks it)}]. Only:
        tmp       an ended session's temp folder (`session_ended`), a runner worktree's or a main checkout's; the
                  regular footprint walk removes these by itself (`auto_clean`)
        worktree  a runner worktree whose HEAD is merged into the project's main branch, with nothing
                  uncommitted, listed unticked when it holds git-ignored files that are no build output or link
                  (`held_files`; they are named, and the id is of that list of them), that no process works in, of a project whose run is off (a run up may start a
                  task in any of its worktrees at any moment; the next run makes a removed one again)
        wip       a wip/ branch: listed unticked, removed only when the person ticks it"""
    merged = merged or worktree_merged
    cwds = busy_dirs() if cwds is None else cwds
    out = []
    for p, d, n, main in temps:
        if session_ended(d, main, live, registry, waits | p.resume, now, written):
            out.append({'id': 'tmp:' + str(d), 'kind': 'tmp', 'path': str(d), 'size': n, 'ask': False,
                        'main': main, 'why': 'ended session\'s temp folder'})
    for p, d, n in trees:
        if p.up or d.name in p.busy:
            continue
        here = str(d.resolve())
        if any(c == here or c.startswith(here + os.sep) for c in cwds):
            continue
        if not merged(p, d):
            continue
        if (held := held_files(d)) is None:
            continue
        why, kind = 'nothing uncommitted, nothing ignored but build output and links', 'worktree'
        if held:  # an id of its own: a tick given before it held these does not count
            why = f'holds files git ignores, deleted with it: {held_names(held)}'
            kind += '+' + held_key(d, held)
        out.append({'id': f'{kind}:{d}', 'kind': 'worktree', 'path': str(d), 'size': n, 'ask': bool(held),
                    'root': str(p.root), 'held': held_key(d, held), 'why': f'worktree merged into {p.main}, {why}'})
    for w in wips:
        out.append({'id': f'wip:{w["root"]}:{w["branch"]}', 'kind': 'wip', 'path': w['branch'], 'size': 0,
                    'ask': True, 'root': w['root'], 'why': f'{w["project"]}: parked work; remove only if you are sure'})
    return out


def session_ended(d: Path, main: bool, live: set[str] | None, registry: bool, waits: set[str], now: float,
                  written=newest_write) -> bool:
    """Has the session of temp folder `d` ended: nothing names it as live, no resume waits for it (`waits`), and
    nothing wrote to it in ENDED_AFTER (`main`, one in a main checkout: MAIN_ENDED_AFTER)? Never where /proc
    cannot tell (`live` None), nor, in a main checkout, when Claude Code's registry could not be read in full
    (`registry`): a person's own session names no id on its command line."""
    if live is None or (main and not registry) or d.name in live or d.name in waits or ANY_SID in waits:
        return False
    return now - written(d) >= (MAIN_ENDED_AFTER if main else ENDED_AFTER)


def auto_clean(foot: dict, projects: list[Project], look, now: float, size=du, written=newest_write,
               rm=shutil.rmtree) -> tuple[int, int]:
    """Remove the ended sessions' temp folders on Clean's list, each looked at again just before (`look()` is
    `live_now`'s answer then), and take them off `foot`. Worktrees and wip/ branches stay for the person.
    (how many it removed, the bytes it freed)."""
    count, freed = 0, 0
    for item in [i for i in foot['clean'] if i['kind'] == 'tmp']:
        d = Path(item['path'])
        written_at = written(d)  # the slow walk first: the looks at what is live and waits come last
        waits = set().union(*(waiting_sids(p) for p in projects))
        live, registry = look()
        if not inside(d.parents[2], d) or not session_ended(d, item['main'], live, registry, waits, now,
                                                            lambda _: written_at):
            foot['clean'].remove(item)
            continue
        try:
            rm(d)
        except OSError:
            pass  # what is left stays on the list
        left = size(d) if d.exists() else 0
        gone = max(0, item['size'] - left)
        freed += gone
        foot['tmp'] -= gone
        foot['total'] -= gone
        if d.exists():
            item['size'] = left
        else:
            count += 1
            foot['clean'].remove(item)
        for x in foot['tmps']:
            if x['path'] == item['path']:
                x['size'] = left
    rank(foot)
    return count, freed


def rank(foot: dict) -> None:
    """The footprint's 'largest' folders and its largest session temp folder, from what is still there."""
    foot['tmps'] = [x for x in foot['tmps'] if x['size']]
    foot['largest'] = sorted(foot['dirs'] + foot['tmps'], key=lambda x: -x['size'])[:8]
    foot['tmp_largest'] = max(foot['tmps'], key=lambda x: x['size'], default=None)


def worktree_merged(p: Project, d: Path) -> bool:
    """Is worktree `d`'s HEAD in `p`'s main branch, with nothing uncommitted (untracked included)?"""
    if git_out(d, 'status', '--porcelain') != '':
        return False
    head = git_out(d, 'rev-parse', 'HEAD')
    if not head:
        return False
    try:
        r = sp.run(['git', 'merge-base', '--is-ancestor', head, p.main], cwd=p.root, capture_output=True, timeout=30)
    except (OSError, sp.SubprocessError):
        return False
    return r.returncode == 0


def clean(chosen: list[str], plan: list[dict], rm=shutil.rmtree, call=sp.run) -> dict:
    """Remove what the person chose from a freshly made Clean list: anything not on it is refused, so a stale
    or forged id removes nothing. A temp folder is deleted, a worktree goes with `git worktree remove` (which
    refuses one with changes; not when its held files changed since the list), a wip/ branch with `git branch -D`. {'ok', 'out', 'freed', 'removed'}."""
    by_id = {i['id']: i for i in plan}
    said, freed, removed = [], 0, []
    for cid in chosen:
        item = by_id.get(cid)
        if item is None:
            said.append(f'not removed (no longer safe, or unknown): {cid.split(":", 1)[-1]}')
            continue
        try:
            if item['kind'] == 'tmp':
                rm(item['path'])
                ok = True
            elif (item['kind'] == 'worktree'
                  and held_key(w := Path(item['path']), held_files(w)) != item.get('held', '')):
                said.append(f'not removed (no longer safe: its ignored files changed): {item["path"]}')
                ok = False
            elif item['kind'] == 'worktree':
                r = call(['git', 'worktree', 'remove', item['path']], cwd=item['root'], capture_output=True,
                         text=True, timeout=120)
                ok = r.returncode == 0
                if not ok:
                    said.append(f'git kept {item["path"]}: {(r.stderr or "").strip()[:200]}')
            else:
                r = call(['git', 'branch', '-D', item['path']], cwd=item['root'], capture_output=True, text=True,
                         timeout=60)
                ok = r.returncode == 0
                if not ok:
                    said.append(f'git kept {item["path"]}: {(r.stderr or "").strip()[:200]}')
        except (OSError, sp.SubprocessError) as e:
            said.append(f'{item["path"]}: {e}')
            ok = False
        if ok:
            freed += item['size']
            removed.append(cid)
    said.insert(0, f'Removed {len(removed)} of {len(chosen)}, freed {size_words(freed) or "0 B"}')
    return {'ok': len(removed) == len(chosen), 'out': '\n'.join(said), 'freed': freed, 'removed': removed}


# --- sessions --------------------------------------------------------------------------------------------------

def session_rows(projects: list[dict], procs: dict, cpu: dict[int, float]) -> list[dict]:
    """CPU and memory per slot and per control session: `projects` as cmds.device_sessions gives them;
    [{'project', 'name', 'what', 'cpu', 'rss'}], only the rows with a live process."""
    out = []
    for p in projects:
        for r in p.get('rows') or []:
            if not r.get('pid') or not re.fullmatch(r'[sc]\d+', r.get('name', '')):
                continue
            if (u := tree_usage(int(r['pid']), procs, cpu)) is None:
                continue
            out.append({'project': p['name'], 'name': r['name'], 'what': r.get('what', ''), 'cpu': u[0],
                        'rss': u[1]})
    return out


def worktree_rows(projects: list[Project], procs: dict, cpu: dict[int, float], cwd_of,
                  have: set[tuple[str, str]] = frozenset()) -> list[dict]:
    """CPU and memory of every process working in a runner worktree (s1…, merge, fix…), one row per worktree:
    the slots a session marker did not name (`have`: (project, name) already counted)."""
    homes = {str(p.home.resolve()): p for p in projects}
    sums: dict[tuple[str, str], list] = {}
    for pid in procs:
        cwd = cwd_of(pid)
        if not cwd:
            continue
        for home, p in homes.items():
            if cwd.startswith(home + os.sep):
                name = cwd[len(home) + 1:].split(os.sep)[0]
                if WORKTREE.fullmatch(name) and (p.root.name, name) not in have:
                    s = sums.setdefault((p.root.name, name), [0.0, 0])
                    s[0] += cpu.get(pid, 0.0)
                    s[1] += procs[pid][2]
                break
    busy = {(p.root.name, n) for p in projects for n in p.busy}
    return [{'project': k[0], 'name': k[1], 'what': 'running a task' if k in busy else '', 'cpu': round(v[0], 1),
             'rss': v[1]} for k, v in sorted(sums.items())]


def proc_cwd(proc: Path = Path('/proc')):
    def cwd_of(pid: int) -> str:
        try:
            return os.readlink(proc / str(pid) / 'cwd')
        except OSError:
            return ''
    return cwd_of


# --- peers -----------------------------------------------------------------------------------------------------

def peer_base(link: str) -> tuple[str, str] | None:
    """('http://host:port', token) from a Home link ('http://host:8770/?t=TOKEN'); None when it is not one."""
    u = urlsplit(link.strip())
    t = (parse_qs(u.query).get('t') or [''])[0]
    if u.scheme not in ('http', 'https') or not u.hostname or not t:
        return None
    return f'{u.scheme}://{u.netloc}', t


def peer_id(base: str) -> str:
    return 'p' + hashlib.sha1(base.encode()).hexdigest()[:8]


def tailscale_hosts(run=sp.run) -> list[tuple[str, str]]:
    """(name, address) of each online machine on the tailnet but this one; none without Tailscale."""
    if run is sp.run and not shutil.which('tailscale'):
        return []
    try:
        r = run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=10)
        d = json.loads(r.stdout) if r.returncode == 0 else {}
    except (OSError, sp.SubprocessError, ValueError):
        return []
    out = []
    for peer in (d.get('Peer') or {}).values() if isinstance(d, dict) else []:
        if not isinstance(peer, dict) or not peer.get('Online'):
            continue
        ips = [ip for ip in peer.get('TailscaleIPs') or [] if ':' not in ip]
        if ips:
            out.append((str(peer.get('HostName') or ips[0]), ips[0]))
    return out


def fetch_json(url: str, data: dict | None = None, timeout: float = PEER_TIMEOUT) -> tuple[int, dict]:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method='POST' if body is not None else 'GET',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {'ok': False, 'out': f'HTTP {e.code}'}
    except (OSError, ValueError) as e:
        return 0, {'ok': False, 'out': str(e)}


# --- pushing alerts --------------------------------------------------------------------------------------------

def push_alert(roots: list[Path], what: str, host: str) -> int:
    """Put a device alert in each running project's events, where `since` shows it as
    'needs you: …'. It goes as a device alert event (EV_DEVICE; status.since_event prints those as needs you
    lines), with its host in `device`. How many projects got it."""
    from agent_runner.cmds import run_info
    from agent_runner.state import EV_DEVICE
    from agent_runner.config import Config
    import datetime as dt
    n = 0
    for root in roots:
        if not (run_info(root) or {}).get('up'):
            continue
        rec = {'time': dt.datetime.now().isoformat(timespec='seconds'), 'kind': EV_DEVICE, 'id': '',
               'text': what, 'device': host}
        try:
            with open(Config(root).notes('events.jsonl'), 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            n += 1
        except (OSError, SystemExit, ValueError, KeyError, TypeError):
            continue
    return n


def new_alerts(found: list[dict], said: set[str]) -> tuple[list[dict], set[str]]:
    """The alerts not pushed yet, and the ids now pushed: one that clears and comes back is pushed again."""
    now = {a['id'] for a in found}
    return [a for a in found if a['id'] not in said], now


def device_link(query: dict) -> str:
    """B818b: where the old /device?id= page sends: Home's app with that device open (devLink in page/052-device.js),
    the token kept as it was given. Relative, so it holds wherever Home is mounted."""
    tok = query.get('t')
    return ('./' + (f'?{urlencode({"t": tok[0]})}' if tok else '')
            + '#device-' + quote((query.get('id') or ['local'])[0], safe=''))


# --- the service Home runs -------------------------------------------------------------------------------------

def usage_now() -> dict:
    """The account's session and weekly usage %, when the local login can read them (at most every 5 min)."""
    try:
        from agent_runner.watch import usage_pct
        return {k: v for k, v in (('session', usage_pct('five_hour')), ('weekly', usage_pct('seven_day')))
                if v is not None}
    except Exception:  # noqa: BLE001 - usage is optional: no login, offline
        return {}


def login_now(now: float) -> str:
    """F126c: what to push about this machine's Claude login, with the command that renews it; '' when it is fine."""
    from agent_runner.watch import LOGIN_CMD, claude_login
    said = claude_login(now)
    return f'{said} ({LOGIN_CMD})' if said else ''


def login_banner(roots: list[Path], now: float | None = None) -> str:
    """F126a: Home's banner about this machine's Claude login: `login_now`, when a project at `roots` has [run] agent
    claude and a role on it; '' when it is fine, or when no project runs on it."""
    from agent_runner.claude_use import account
    from agent_runner.config import Config
    try:
        said = login_now(time.time() if now is None else now)
    except Exception:  # noqa: BLE001 - costs the banner, not All projects
        return ''
    for root in roots if said else ():
        try:
            if account(Config(root)):
                return said
        except (Exception, SystemExit):  # noqa: BLE001 - settings that cannot be read
            pass
    return ''


class Vitals:
    """This machine's vitals for Home: samples every EVERY s in a thread once started, walks the footprint every
    FOOTPRINT_EVERY s and removes the ended sessions' temp folders it finds (`auto_clean`) and old build output
    (`build_clean`), pushes new alerts,
    and answers the page's calls (`handle`)."""

    def __init__(self, roots, store: Path | None, peers=lambda: [], token: str = '', tailscale: bool = True,
                 sampler: Sampler | None = None, sessions=None, usage=usage_now, info=None, push=push_alert,
                 act=None, registry: Path | None = None, log=lambda said: print(said, flush=True),
                 login=login_now):
        self.registry, self.log, self.login_fn = registry, log, login
        self.roots, self.peers, self.token, self.tailscale = roots, peers, token, tailscale
        self.sampler = sampler or Sampler()
        self.history = History(store / 'vitals.jsonl' if store else None)
        self.said_file = store / 'vitals-alerts.json' if store else None
        self.login_file = store / 'vitals-login' if store else None  # F126c: the day login_day holds
        self.login_day = ((_read(self.login_file) if self.login_file else None) or '').strip()
        self.login_bad: bool | None = None  # whether the last sample had a login warning
        self.sessions_fn, self.usage_fn, self.info, self.push, self.act = sessions, usage, info, push, act
        self.snap: dict = {}
        self.foot: dict | None = None
        self.foot_at = -1e9
        self.usage: dict = {}
        self.usage_at = -1e9
        self.lock, self.foot_lock = threading.Lock(), threading.Lock()
        self.started = False
        self.peer_cache: tuple[float, list[dict]] = (-1e9, [])
        self.ts_cache: tuple[float, list[tuple[str, str]]] = (-1e9, [])
        try:
            self.said = set(json.loads(_read(self.said_file) or '[]')) if self.said_file else set()
        except ValueError:
            self.said = set()

    # sampling
    def start(self) -> None:
        with self.lock:
            if self.started:
                return
            self.started = True
        self.tick(walk=False)
        threading.Thread(target=self.loop, name='home-vitals', daemon=True).start()

    def loop(self) -> None:
        wait = 2.0  # the second look soon, so CPU busy shows within seconds of starting
        while True:
            time.sleep(wait)
            wait = EVERY
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - one bad read must not end the sampling
                pass

    def projects(self) -> list[Project]:
        return [p for p in (Project.of(r, self.info) for r in self.roots()) if p]

    def tick(self, now: float | None = None, walk: bool = True) -> dict:
        """One sample: kept, alerts pushed. `walk`: also walk the footprint here when due (else in a thread,
        so the first page load does not wait for it)."""
        now = time.time() if now is None else now
        projs = self.projects()
        if homes := [p.home for p in projs if p.home.exists()]:  # the run home on the fullest disk
            def free(h: Path) -> float:
                try:
                    return shutil.disk_usage(h).free
                except OSError:
                    return float('inf')
            self.sampler.disk = min(homes, key=free)
        snap = self.sampler.sample(now)
        self.history.add(point(snap))
        self.snap = snap
        if now - self.usage_at > 300:
            # F406h: not read when no project runs on claude
            self.usage, self.usage_at = self.usage_fn() if not projs or any(p.agent for p in projs) else {}, now
        if self.foot is None or now - self.foot_at > FOOTPRINT_EVERY:
            if walk:
                self.refresh_footprint(projs, now)
            else:
                threading.Thread(target=self.refresh_footprint, name='home-footprint', daemon=True).start()
        self.push_alerts(projs)
        self.push_login(projs, now)
        return snap

    def refresh_footprint(self, projs: list[Project] | None = None, now: float | None = None,
                          auto: bool = True) -> dict:
        """Walk the footprint again, remove the ended sessions' temp folders, and old build output first, and
        log what that freed. Without `auto` nothing is removed or kept: the answer is the person's Clean's fresh list."""
        with self.foot_lock:
            projs = self.projects() if projs is None else projs
            now = time.time() if now is None else now
            if auto:
                self.foot_at = now  # a walk under way is not started again
                try:
                    self.clear_builds(projs, now)
                except Exception as e:  # noqa: BLE001 - the walk goes on without it
                    self.log(f'{time.strftime("%Y-%m-%d %H:%M:%S")} old build output not cleared: {e!r}')
            live, registry = self.look()
            foot = footprint(projs, live, now, registry=registry)
            if auto:
                count, freed = auto_clean(foot, projs, self.look, now)
                if count or freed:
                    self.log(f'{time.strftime("%Y-%m-%d %H:%M:%S")} removed {count} ended sessions\' temp folders, '
                             f'freed {size_words(freed) or "0 B"}')
                self.foot = foot
            return foot

    def clear_builds(self, projs: list[Project], now: float) -> None:
        """F424: remove the old build output of projects whose run is off, and log what that freed."""
        def said(d: Path, count: int, freed: int) -> None:
            self.log(f'{time.strftime("%Y-%m-%d %H:%M:%S")} removed {count} old build folders in {d}, '
                     f'freed {size_words(freed) or "0 B"}')
        clean_builds(projs, self.run_off, lambda: busy_dirs(self.sampler.proc), now, du, said=said)

    def run_off(self, p: Project) -> bool:
        """Is `p`'s run off now? Not when that cannot be told."""
        info = self.info
        if info is None:
            from agent_runner.cmds import run_info as info
        return (info(p.root) or {}).get('up') is False

    def look(self) -> tuple[set[str] | None, bool]:
        return live_now(self.sampler.proc, self.registry)

    def limits(self, projs: list[Project]) -> tuple[float, dict]:
        """The strictest min_free_gb and usage caps over this machine's projects."""
        mff = max((p.min_free_gb for p in projs if p.min_free_gb), default=10)
        caps = {}
        for k in ('weekly_max', 'session_max'):
            vals = [p.caps.get(k) for p in projs if p.caps.get(k)]
            if vals:
                caps[k] = min(vals)
        return mff, caps

    def push_alerts(self, projs: list[Project]) -> None:
        found = self.alerts(projs)
        fresh, self.said = new_alerts(found, self.said)
        for a in fresh:
            try:
                got = self.push([p.root for p in projs], a['what'], self.snap.get('host', ''))
            except Exception:  # noqa: BLE001 - a push that fails must not stop the sampling
                got = 0
            if not got:  # no run up to feed it: try again on the next sample, so a run started later hears it
                self.said.discard(a['id'])
        if self.said_file and fresh:
            try:
                self.said_file.write_text(json.dumps(sorted(self.said)), encoding='utf-8')
            except OSError:
                pass

    def push_login(self, projs: list[Project], now: float) -> None:
        """F126c: while the Claude login is ending, has ended or is missing, push that once a day (local date), as a
        device alert, to the running projects whose [run] agent is claude, with a role on it. The day is kept over a restart, and
        forgotten once the login is fine, so a new warning is pushed again. Two samples in a row must agree: one
        read while Claude Code rewrites its credentials file neither warns nor counts as a renewal."""
        try:
            said = self.login_fn(now)
        except Exception:  # noqa: BLE001 - a login that cannot be read must not stop the sampling
            return
        before, self.login_bad = self.login_bad, bool(said)
        if before != self.login_bad:
            return
        today = time.strftime('%Y-%m-%d', time.localtime(now)) if said else ''
        if today == self.login_day:
            return
        if said:
            host = self.snap.get('host', '')
            try:
                got = self.push([p.root for p in projs if p.agent == 'claude'], f'{host}: {said}', host)
            except Exception:  # noqa: BLE001 - a push that fails must not stop the sampling
                got = 0
            if not got:  # no run up to hear it: tried again on the next sample
                return
        self.login_day = today
        if self.login_file:
            try:
                self.login_file.write_text(today, encoding='utf-8')
            except OSError:
                pass

    def alerts(self, projs: list[Project]) -> list[dict]:
        mff, _ = self.limits(projs)
        return alerts(self.snap, mff, self.foot)

    # what the page reads
    def device(self, detail: bool = True) -> dict:
        """This machine as /vitals/device answers: the card ('verdict', 'meters', 'alerts', 'headroom') and, with
        `detail`, the vitals page's sections."""
        if not self.started:
            self.start()
        projs = self.projects()
        mff, caps = self.limits(projs)
        # a project past its own caps starts tasks down its chain: one whose run is up; with none up, any
        mine = [p for p in projs if p.up] or projs
        if not any(p.caps for p in mine):  # F406h: no run here runs on claude: its caps hold none
            caps = {}
        fell = any(p.fallback and past_caps(self.usage, p.caps) for p in mine)
        room = headroom(self.snap, mff, self.usage, caps, fell)
        found = alerts(self.snap, mff, self.foot)
        try:
            from agent_runner.home import keys
            named = {str(v): k for k, v in keys(self.roots()).items()}
        except Exception:  # noqa: BLE001
            named = {}
        out = {'ok': True, 'id': 'local', 'host': self.snap.get('host') or socket.gethostname(),
               'os': self.snap.get('os'), 't': self.snap.get('t'), 'here': True, 'headroom': room,
               'verdict': verdict(room, found), 'meters': meters(self.snap), 'alerts': found,
               'running': [{'key': named.get(str(p.root), p.root.name), 'root': str(p.root), 'busy': len(p.busy)}
                           for p in projs if p.up],
               'min_free_gb': mff}
        if not detail:
            return out
        snap = self.snap
        out['machine'] = {k: snap[k] for k in ('cpu', 'mem', 'disk', 'gpus', 'sensors', 'top') if k in snap}
        out['spark'] = {k: self.history.series(k) for k in ('cpu', 'gpu', 'mem', 'disk', 'temp', 'gtemp')}
        out['spark'] = {k: v for k, v in out['spark'].items() if any(x is not None for x in v)}
        foot = self.foot or {}
        out['footprint'] = {k: foot.get(k) for k in ('worktrees', 'tmp', 'logs', 'wip', 'total', 'largest')}
        out['clean'] = foot.get('clean') or []
        out['sessions'] = self.session_rows()
        return out

    def session_rows(self, projs: list[Project] | None = None) -> list[dict]:
        """Per slot and per control session: those a session marker names, then each worktree's processes."""
        try:
            if self.sessions_fn is None:
                from agent_runner.cmds import device_sessions
                rows = device_sessions()
            else:
                rows = self.sessions_fn()
        except Exception:  # noqa: BLE001 - sessions are a nice-to-have on the page
            rows = []
        procs, cpu = self.sampler.procs, self.sampler.proc_cpu
        out = session_rows(rows, procs, cpu)
        have = {(r['project'], r['name']) for r in out}
        out += worktree_rows(self.projects() if projs is None else projs, procs, cpu, proc_cwd(self.sampler.proc),
                             have)
        return out

    def peer_links(self) -> list[tuple[str, str, str]]:
        """(id, base, token) of each peer: the registry's links, then Tailscale machines (this Home's token)."""
        out, seen = [], set()
        for link in self.peers():
            if (b := peer_base(link)) and b[0] not in seen:
                seen.add(b[0])
                out.append((peer_id(b[0]), *b))
        if self.tailscale:
            at, hosts = self.ts_cache
            if time.time() - at > 300:
                hosts = tailscale_hosts()
                self.ts_cache = (time.time(), hosts)
            port = self.port()
            for _name, ip in hosts:
                base = f'http://{ip}:{port}'
                if base not in seen:
                    seen.add(base)
                    out.append((peer_id(base), base, self.token))
        return out

    def port(self) -> int:
        try:
            from agent_runner.home import load_registry
            return load_registry()['port']
        except Exception:  # noqa: BLE001
            return 8770

    def devices(self) -> list[dict]:
        """This machine first, then each peer that answered (a registry peer that did not is listed as
        unreachable; a Tailscale machine without a Home is left out)."""
        out = [self.device(detail=False)]
        at, cached = self.peer_cache
        if time.time() - at < EVERY / 2:
            return out + cached
        links = self.peer_links()
        listed = {peer_id(b[0]) for link in self.peers() if (b := peer_base(link))}

        def one(item):
            pid, base, tok = item
            code, d = fetch_json(f'{base}/vitals/device?{urlencode({"t": tok, "card": "1"})}')
            if code == 200 and d.get('ok'):
                return {**d, 'id': pid, 'here': False}
            if pid in listed:
                return {'ok': False, 'id': pid, 'host': urlsplit(base).hostname, 'here': False,
                        'verdict': {'said': 'Not answering' if code != 403 else 'Its Home refused the token in '
                                    'the link', 'level': 'bad'}, 'meters': [], 'alerts': []}
            return None
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            found = [d for d in ex.map(one, links) if d]
        hosts, peers = {out[0]['host']}, []
        for d in found:  # one machine listed by its link and found on Tailscale too: shown once
            if d.get('host') not in hosts or not d.get('ok'):
                hosts.add(d.get('host'))
                peers.append(d)
        self.peer_cache = (time.time(), peers)
        return out + peers

    def peer(self, pid: str) -> tuple[str, str] | None:
        for i, base, tok in self.peer_links():
            if i == pid:
                return base, tok
        return None

    # the page's calls
    def handle(self, method: str, path: str, query: dict, body: bytes) -> tuple[int, dict | str, str]:
        """Answer one of Home's vitals calls: (status, body, content type)."""
        json_t = 'application/json; charset=utf-8'
        if method == 'GET' and path == '/devices':
            devs = self.devices()
            needs = [{**a, 'device': d['id']} for d in devs for a in d.get('alerts') or []]
            return 200, {'ok': True, 'devices': devs, 'needs': needs}, json_t
        if path.startswith('/dev/'):
            _, _, pid, rest = (path + '/').split('/', 3)
            rest = '/' + rest.rstrip('/')
            if pid == 'local':
                return self.handle(method, rest, query, body)
            peer = self.peer(pid)
            if peer is None:
                return 404, {'ok': False, 'out': f'no such device: {pid}'}, json_t
            base, tok = peer
            try:
                data = json.loads(body or b'null')
            except ValueError:
                data = None
            code, d = fetch_json(f'{base}{rest}?{urlencode({"t": tok})}', data if method == 'POST' else None,
                                 timeout=30 if method == 'POST' else PEER_TIMEOUT * 2)
            if isinstance(d, dict) and rest == '/vitals/device':
                d['id'] = pid
            return code or 502, d, json_t
        if method == 'GET' and path == '/vitals/device':
            return 200, self.device(detail=not query.get('card')), json_t
        if method == 'POST' and path == '/act' and self.act is not None:  # /dev/local/act: Home's own buttons
            try:
                req = json.loads(body or b'{}')
                key, name, arg = str(req.get('project') or ''), str(req.get('name') or ''), str(req.get('arg') or '')
            except (ValueError, AttributeError):
                return 400, {'ok': False, 'out': 'bad request'}, json_t
            return 200, self.act(key, name, arg), json_t
        if method == 'POST' and path == '/vitals/clean':
            try:
                req = json.loads(body or b'{}')
                chosen = [str(x) for x in req.get('items') or []]
            except (ValueError, AttributeError):
                return 400, {'ok': False, 'out': 'bad request: {"items": [ids]}'}, json_t
            plan = self.refresh_footprint(auto=False).get('clean') or []  # made again now: only what is still safe
            res = clean(chosen, plan)
            self.refresh_footprint()
            return 200, res, json_t
        return 404, {'ok': False, 'out': f'no such page: {path}'}, json_t
