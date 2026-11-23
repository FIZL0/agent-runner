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
               full, session temp folders over 5 GB (`alerts`); they show under Needs you on Home and go to
               each running project's runner feed, which pushes them (`Vitals.push_alerts`)
    footprint  what agent-runner keeps on disk: worktrees under each run home, session temp folders, logs,
               wip/ branches, each sized (`footprint`), and Clean's safe list (`clean_plan`, `clean`)
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
from urllib.parse import parse_qs, urlencode, urlsplit

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
TMP_ALERT_GB = 5.0       # session temp folders past this are an alert
ENDED_AFTER = 3600.0     # s with no write before a session temp folder no process names counts as ended
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
    provider not capped and logged in (fallback.chain_next, for any project's config)."""
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


def alerts(snap: dict, min_free_gb: float = 10, tmp_bytes: int | None = None) -> list[dict]:
    """The thresholds crossed: [{'id', 'what', 'clean' (Clean helps)}]. `id` stays the same while the
    problem lasts, so it is pushed once."""
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
    if tmp_bytes is not None and tmp_bytes >= TMP_ALERT_GB * GB:
        out.append({'id': f'{host}:tmp', 'clean': True,
                    'what': f'{host}: session temp folders use {tmp_bytes / GB:.1f} GB (over {TMP_ALERT_GB:.0f} GB): '
                            f'Clean frees the ended sessions\''})
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
                 resume: set[str], min_free_gb: float = 10, caps: dict | None = None, fallback: bool = False):
        self.fallback = fallback
        self.root, self.home, self.notes, self.main, self.up = root, home, notes, main, up
        self.busy, self.resume, self.min_free_gb, self.caps = busy, resume, min_free_gb, caps or {}

    @classmethod
    def of(cls, root: Path, info=None) -> 'Project | None':
        try:
            from agent_runner.config import Config
            c = Config(root)
            home, notes = c.home, c.notes()
            main = c.master_branch or git_out(root, 'branch', '--show-current') or 'main'
            mff, caps = c.run.get('min_free_gb', 10), {k: c.run.get(k) for k in ('weekly_max', 'session_max')}
            fallback = free_fallback(c)
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
        return cls(root, home, notes, main, bool(run.get('up')), busy, resume, mff, caps, fallback)


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
            if (p := mine.get(proj.name)) is None:
                continue
            out += [(p, d) for d in _dirs(proj) if SESSION_DIR.fullmatch(d.name)]
    return out


def _dirs(p: Path) -> list[Path]:
    try:
        return sorted(d for d in p.iterdir() if d.is_dir() and not d.is_symlink())
    except OSError:
        return []


def footprint(projects: list[Project], live: set[str] | None, now: float | None = None,
              size=du, written=newest_write, cwds: list[str] | None = None) -> dict:
    """What agent-runner keeps on this machine: {'worktrees', 'tmp', 'logs': bytes, 'wip': [branches],
    'total', 'largest': [{'path', 'size'}], 'clean': Clean's list}."""
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
    temps = []
    for p, d in session_folders(projects, tmp_roots(projects)):
        n = size(d)
        out['tmp'] += n
        sized.append({'path': str(d), 'size': n})
        temps.append((p, d, n))
    for p, d in session_folders(projects, tmp_roots(projects), main=True):
        # control sessions' temp folders count in the size and the 5 GB alert, but Clean never lists them: a
        # person's own session in the main checkout names no session id on its command line, so a quiet one
        # cannot be told from an ended one
        n = size(d)
        out['tmp'] += n
        sized.append({'path': str(d), 'size': n})
    out['largest'] = sorted(sized, key=lambda x: -x['size'])[:8]
    out['total'] = out['worktrees'] + out['tmp'] + out['logs']
    out['clean'] = clean_plan(trees, temps, out['wip'], live, now, written, cwds)
    return out


def clean_plan(trees, temps, wips, live: set[str] | None, now: float, written=newest_write,
               cwds: list[str] | None = None, merged=None) -> list[dict]:
    """Clean's safe list, shown before anything is removed: [{'id', 'kind', 'path', 'size', 'why', 'ask'
    (only when the person ticks it)}]. Only:
        tmp       a session temp folder no running process names, no resume waits for, and nothing wrote to in
                  ENDED_AFTER; none where /proc cannot tell (`live` None)
        worktree  a runner worktree whose HEAD is merged into the project's main branch, with nothing
                  uncommitted, that no process works in, of a project whose run is off (a run up may start a
                  task in any of its worktrees at any moment; the next run makes a removed one again)
        wip       a wip/ branch: listed unticked, removed only when the person ticks it"""
    merged = merged or worktree_merged
    cwds = busy_dirs() if cwds is None else cwds
    out = []
    if live is not None:
        for p, d, n in temps:
            if d.name in live or d.name in p.resume:
                continue
            if now - written(d) < ENDED_AFTER:
                continue
            out.append({'id': 'tmp:' + str(d), 'kind': 'tmp', 'path': str(d), 'size': n, 'ask': False,
                        'why': 'ended session\'s temp folder'})
    for p, d, n in trees:
        if p.up or d.name in p.busy:
            continue
        here = str(d.resolve())
        if any(c == here or c.startswith(here + os.sep) for c in cwds):
            continue
        if not merged(p, d):
            continue
        out.append({'id': 'worktree:' + str(d), 'kind': 'worktree', 'path': str(d), 'size': n, 'ask': False,
                    'root': str(p.root), 'why': f'worktree merged into {p.main}, nothing uncommitted'})
    for w in wips:
        out.append({'id': f'wip:{w["root"]}:{w["branch"]}', 'kind': 'wip', 'path': w['branch'], 'size': 0,
                    'ask': True, 'root': w['root'], 'why': f'{w["project"]}: parked work; remove only if you are sure'})
    return out


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
    refuses one with changes), a wip/ branch with `git branch -D`. {'ok', 'out', 'freed', 'removed'}."""
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
    """Put a device alert in each running project's events, where its runner feed reads it and pushes it as
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


# --- the service Home runs -------------------------------------------------------------------------------------

def usage_now() -> dict:
    """The account's session and weekly usage %, when the local login can read them (at most every 5 min)."""
    try:
        from agent_runner.watch import usage_pct
        return {k: v for k, v in (('session', usage_pct('five_hour')), ('weekly', usage_pct('seven_day')))
                if v is not None}
    except Exception:  # noqa: BLE001 - usage is optional: no login, offline
        return {}


class Vitals:
    """This machine's vitals for Home: samples every EVERY s in a thread once started, walks the footprint every
    FOOTPRINT_EVERY s, pushes new alerts, and answers the page's calls (`handle`)."""

    def __init__(self, roots, store: Path | None, peers=lambda: [], token: str = '', tailscale: bool = True,
                 sampler: Sampler | None = None, sessions=None, usage=usage_now, info=None, push=push_alert,
                 act=None):
        self.roots, self.peers, self.token, self.tailscale = roots, peers, token, tailscale
        self.sampler = sampler or Sampler()
        self.history = History(store / 'vitals.jsonl' if store else None)
        self.said_file = store / 'vitals-alerts.json' if store else None
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
            self.usage, self.usage_at = self.usage_fn(), now
        if self.foot is None or now - self.foot_at > FOOTPRINT_EVERY:
            if walk:
                self.refresh_footprint(projs, now)
            else:
                threading.Thread(target=self.refresh_footprint, name='home-footprint', daemon=True).start()
        self.push_alerts(projs)
        return snap

    def refresh_footprint(self, projs: list[Project] | None = None, now: float | None = None) -> dict:
        with self.foot_lock:
            projs = self.projects() if projs is None else projs
            now = time.time() if now is None else now
            self.foot_at = now  # a walk under way is not started again
            self.foot = footprint(projs, live_session_ids(self.sampler.proc), now)
            return self.foot

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

    def alerts(self, projs: list[Project]) -> list[dict]:
        mff, _ = self.limits(projs)
        return alerts(self.snap, mff, (self.foot or {}).get('tmp'))

    # what the page reads
    def device(self, detail: bool = True) -> dict:
        """This machine as /vitals/device answers: the card ('verdict', 'meters', 'alerts', 'headroom') and, with
        `detail`, the vitals page's sections."""
        if not self.started:
            self.start()
        projs = self.projects()
        mff, caps = self.limits(projs)
        # a project past its own caps starts tasks down its chain: one whose run is up; with none up, any
        fell = any(p.fallback and past_caps(self.usage, p.caps) for p in [p for p in projs if p.up] or projs)
        room = headroom(self.snap, mff, self.usage, caps, fell)
        found = alerts(self.snap, mff, (self.foot or {}).get('tmp'))
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
        if method == 'GET' and path == '/device':
            return 200, VITALS_PAGE, 'text/html; charset=utf-8'
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
            plan = self.refresh_footprint().get('clean') or []  # made again now: only what is still safe
            res = clean(chosen, plan)
            self.refresh_footprint()
            return 200, res, json_t
        return 404, {'ok': False, 'out': f'no such page: {path}'}, json_t


# --- the vitals page -------------------------------------------------------------------------------------------

VITALS_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Device Vitals</title>
<style>
:root{--bg:#f7f6f3;--fg:#1f1e1c;--dim:#6b6860;--card:#fff;--line:#e3e0d8;--accent:#c2410c;--ok:#15803d;--warn:#b45309;--bad:#b91c1c;--track:#ece9e2;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#1a1917;--fg:#ecebe8;--dim:#a19e96;--card:#24231f;--line:#3a3833;--accent:#fb923c;--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--track:#33312c;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;
 padding:max(16px,env(safe-area-inset-top)) max(16px,env(safe-area-inset-right)) 24px max(16px,env(safe-area-inset-left))}
main{max-width:720px;margin:0 auto}h1{font-size:1.3rem;margin:0 0 4px}a{color:var(--accent)}
.sec{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin:10px 0}
.sec h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:var(--dim);margin:0 0 8px;display:flex;justify-content:space-between}
.s{color:var(--dim);font-size:.9rem}.big{font-size:1.15rem;font-weight:600}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
.row{display:flex;justify-content:space-between;gap:8px;padding:3px 0;border-bottom:1px solid var(--line)}.row:last-child{border:0}
.row span:last-child{color:var(--dim);font-variant-numeric:tabular-nums;text-align:right}
.row span:first-child{min-width:0;overflow-wrap:anywhere}
.m{display:grid;grid-template-columns:70px 1fr 110px;gap:8px;align-items:center;margin:6px 0}
.bar{height:7px;background:var(--track);border-radius:4px;overflow:hidden}.bar i{display:block;height:100%;background:var(--ok)}
.bar i.w{background:var(--warn)}.bar i.b{background:var(--bad)}
.r{text-align:right;color:var(--dim);font-variant-numeric:tabular-nums;font-size:.9rem}
svg{width:100%;height:28px;display:block;color:var(--accent)}
button{font:inherit;font-size:.9rem;border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:8px;padding:5px 11px;margin:6px 6px 0 0;cursor:pointer}
.go{background:var(--accent);color:var(--card);border-color:var(--accent)}
.more{font-size:.8rem;border:0;background:none;color:var(--accent);padding:0;margin:0}
label{display:flex;gap:8px;align-items:flex-start;padding:3px 0}label span{min-width:0;overflow-wrap:anywhere}
#msg{white-space:pre-wrap;font-size:.85rem;color:var(--dim)}
</style></head><body><main>
<a id="back" href="#">← Home</a>
<h1 id="h">Device</h1><div id="v" class="s">Loading…</div>
<div id="body"></div><div id="msg"></div>
</main><script>
const P=new URLSearchParams(location.search),T=P.get('t')||'',ID=P.get('id')||'local';
const q=p=>p+(p.includes('?')?'&':'?')+'t='+encodeURIComponent(T);
document.getElementById('back').href=q('./');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const GB=1073741824;const sz=n=>n==null?'':n>=1099511627776?(n/1099511627776).toFixed(1)+' TB':n>=GB?(n/GB).toFixed(1)+' GB':n>=1048576?(n/1048576).toFixed(0)+' MB':(n/1024).toFixed(0)+' KB';
const open={};let busy=false,picked=null;
function bar(p){const c=p>=90?'b':p>=75?'w':'';return `<div class="bar"><i class="${c}" style="width:${Math.max(0,Math.min(100,p))}%"></i></div>`}
function spark(v){if(!v)return'';const pts=v.map((x,i)=>x==null?null:[i,x]).filter(Boolean);if(pts.length<2)return'';
 const lo=Math.min(...pts.map(p=>p[1])),hi=Math.max(...pts.map(p=>p[1])),span=hi-lo||1;
 return `<svg viewBox="0 0 ${v.length-1} 28" preserveAspectRatio="none"><polyline fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke" points="${pts.map(p=>p[0]+','+(26-24*(p[1]-lo)/span).toFixed(1)).join(' ')}"/></svg>`}
function sec(id,title,inner,more){return `<div class="sec"><h2><span>${title}</span>${more?`<button class="more" data-more="${id}">${open[id]?'Less':'More'}</button>`:''}</h2>${inner}${more&&open[id]?more:''}</div>`}
function rows(list){return list.map(([a,b])=>`<div class="row"><span>${esc(a)}</span><span>${esc(b)}</span></div>`).join('')}
function render(d){document.getElementById('h').textContent=d.host+(d.here?' · this one':'');document.title=d.host+' · Device Vitals';
 const v=d.verdict||{};document.getElementById('v').innerHTML=`<span class="${esc(v.level)}">${esc(v.said)}</span>`;
 if(!d.ok){document.getElementById('body').innerHTML='';return}
 const h=d.headroom||{},lim=h.limits||{},out=[];
 const why=Object.entries(lim).map(([k,n])=>`${k} ${n}`).join(' · ');
 let plus=(d.running||[]).map(r=>`<button class="go" data-slot="${esc(r.key)}">+ slot${d.running.length>1?' · '+esc(r.key):''}</button>`).join('');
 out.push(sec('room','Headroom',`<div class="big">${esc(h.said||'')}</div><div class="s">Smallest of: ${esc(why)} (at most 6)</div>${plus||'<div class="s">No run up on this device to add a slot to.</div>'}`));
 const m=d.machine||{},sp=d.spark||{},mm=[];
 if(m.cpu){const c=m.cpu;mm.push(`<div class="m"><span>CPU</span>${c.pct!=null?bar(c.pct):'<span></span>'}<span class="r">${c.pct!=null?c.pct.toFixed(0)+'%':''} ${c.threads?c.threads+' thr':''} ${c.load!=null?'load '+c.load:''}</span></div>${spark(sp.cpu)}`);
  if(c.temp!=null)mm.push(`<div class="m"><span>Temp</span>${bar(c.temp)}<span class="r">${c.temp.toFixed(0)}°C</span></div>${spark(sp.temp)}`)}
 (m.gpus||[]).forEach((g,i)=>{mm.push(`<div class="m"><span>GPU</span>${g.pct!=null?bar(g.pct):'<span></span>'}<span class="r">${g.pct!=null?g.pct.toFixed(0)+'%':''} ${g.temp!=null?g.temp.toFixed(0)+'°':''} ${g.vram_total?sz(g.vram_used)+'/'+sz(g.vram_total):''}</span></div><div class="s">${esc(g.name)}</div>${i==0?spark(sp.gpu):''}`);
  if(i==0&&g.temp!=null)mm.push(`<div class="m"><span>GPU temp</span>${bar(g.temp)}<span class="r">${g.temp.toFixed(0)}°C</span></div>${spark(sp.gtemp)}`)});
 if(m.mem){const u=m.mem.total-m.mem.avail;mm.push(`<div class="m"><span>Memory</span>${bar(100*u/m.mem.total)}<span class="r">${sz(u)} / ${sz(m.mem.total)}</span></div>${spark(sp.mem)}`)}
 if(m.disk){mm.push(`<div class="m"><span>Disk</span>${bar(100*(1-m.disk.free/m.disk.total))}<span class="r">${sz(m.disk.free)} free</span></div><div class="s">${esc(m.disk.path)} · free GB, last 24 h</div>${spark(sp.disk)}`)}
 let more='';if(m.cpu&&m.cpu.cores)more+='<div class="s" style="margin-top:8px">Per core</div>'+m.cpu.cores.map((c,i)=>`<div class="m"><span>${i}</span>${bar(c)}<span class="r">${c.toFixed(0)}%</span></div>`).join('');
 if(m.sensors)more+='<div class="s" style="margin-top:8px">All sensors</div>'+rows(m.sensors.map(s=>[s.chip+' · '+s.label,s.c.toFixed(0)+'°C']));
 if(m.top)more+='<div class="s" style="margin-top:8px">Top processes</div>'+rows(m.top.map(p=>[p.name+' ('+p.pid+')',p.cpu.toFixed(1)+'% · '+sz(p.rss)]));
 out.push(sec('machine','Machine',mm.join('')||'<div class="s">Nothing here could be read.</div>',more));
 const f=d.footprint||{};const fr=[];
 if(f.worktrees!=null)fr.push(['Worktrees (run homes)',sz(f.worktrees)]);if(f.tmp!=null)fr.push(['Session temp folders',sz(f.tmp)]);
 if(f.logs!=null)fr.push(['Logs',sz(f.logs)]);if(f.wip)fr.push(['wip/ branches',String(f.wip.length)]);
 const cl=d.clean||[];let cin='';
 if(picked){cin='<div class="s" style="margin-top:8px">Clean removes only what you tick:</div>'+cl.map(i=>`<label><input type="checkbox" data-id="${esc(i.id)}"${picked.has(i.id)?' checked':''}><span>${esc(i.path)} <span class="s">· ${esc(i.why)}${i.size?' · '+sz(i.size):''}</span></span></label>`).join('')+
  `<button class="go" data-clean="go">Remove ticked</button><button data-clean="cancel">Cancel</button>`}
 else{const safe=cl.filter(i=>!i.ask).reduce((a,i)=>a+i.size,0);cin=cl.length?`<button class="go" data-clean="list">Clean ${sz(safe)} safely…</button>`:'<div class="s">Nothing to clean.</div>'}
 const lmore=(f.largest||[]).length?'<div class="s" style="margin-top:8px">Largest folders</div>'+rows(f.largest.map(x=>[x.path,sz(x.size)])):'';
 out.push(sec('foot','Runner footprint'+(f.total!=null?' · '+sz(f.total):''),(fr.length?rows(fr):'<div class="s">Not measured yet.</div>')+cin,lmore));
 const ss=d.sessions||[];
 out.push(sec('sess','Sessions',ss.length?rows(ss.map(s=>[s.project+' '+s.name+(s.what?' · '+s.what:''),s.cpu.toFixed(1)+'% · '+sz(s.rss)])):'<div class="s">No slot or control session running here.</div>'));
 document.getElementById('body').innerHTML=out.join('')}
let last=null;
async function load(){if(busy)return;try{const r=await fetch(q('dev/'+encodeURIComponent(ID)+'/vitals/device'));last=await r.json();render(last)}catch(e){}}
async function post(path,body){busy=true;const m=document.getElementById('msg');m.textContent='…';
 try{const r=await fetch(q(path),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();m.textContent=d.out||''}catch(e){m.textContent=String(e)}busy=false;load()}
document.getElementById('body').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
 if(b.dataset.more){open[b.dataset.more]=!open[b.dataset.more];render(last);return}
 if(b.dataset.slot)return post('dev/'+encodeURIComponent(ID)+'/act',{project:b.dataset.slot,name:'slots',arg:'+1'});
 if(b.dataset.clean==='list'){picked=new Set((last.clean||[]).filter(i=>!i.ask).map(i=>i.id));busy=true;render(last);return}
 if(b.dataset.clean==='cancel'){picked=null;busy=false;render(last);return}
 if(b.dataset.clean==='go'){const ids=[...document.querySelectorAll('[data-id]')].filter(x=>x.checked).map(x=>x.dataset.id);picked=null;busy=false;
  if(ids.length)post('dev/'+encodeURIComponent(ID)+'/vitals/clean',{items:ids});else render(last)}});
load();setInterval(load,30000);
</script></body></html>
"""
