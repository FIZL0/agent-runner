#!/usr/bin/env python3
"""F95: Device Vitals in Runner Home. The headroom maths, the collectors on fixture /proc and /sys trees (and
macOS, Windows and nvidia-smi output), the day of samples, Clean's safe list, the threshold alerts and their
push to a runner feed, and Home's vitals calls (this machine and a peer Home).

    python3 tests/test_vitals.py      (temp folders, servers on free local ports)
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _check import check, eq, git, report

from agent_runner import vitals as V  # noqa: E402

GB = V.GB


def tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix='vitals-')).resolve()


def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')
    return p


def snap(**kw) -> dict:
    s = {'host': 'box', 't': 1000}
    s.update(kw)
    return s


# --- headroom ---------------------------------------------------------------------------------------------------

def test_headroom():
    print('headroom: the smallest of memory, CPU load, disk and usage cap, capped at 6')
    s = snap(mem={'total': 30 * GB, 'avail': 16 * GB}, cpu={'threads': 16, 'load': 6.08},
             disk={'path': '/', 'total': 2000 * GB, 'free': 902 * GB})
    h = V.headroom(s, 10)
    eq(h['limits'], {'memory': 12, 'cpu': 6, 'disk': 446}, 'the concept\'s desktop: memory 12, CPU 6, disk plenty')
    eq((h['room'], h['by'], h['said']), (6, 'cpu', 'Room for 6 more agents'), 'the CPU sets it')
    s['cpu']['load'] = 10.5
    eq((V.headroom(s, 10)['room'], V.headroom(s, 10)['said']), (2, 'Room for 2 more agents'), 'busier CPU: 2')
    s['cpu']['load'] = 0.0
    s['mem']['avail'] = 64 * GB
    h = V.headroom(s, 10)
    eq((h['room'], h['by']), (6, ''), 'never more than ROOM_MAX, and no limit is named when the cap sets it')
    s['mem']['avail'] = 5 * GB
    eq(V.headroom(s, 10)['said'], 'Room for 1 more agent', 'one: singular')
    s['mem']['avail'] = 3 * GB
    h = V.headroom(s, 10)
    eq((h['room'], h['by']), (0, 'memory'), 'under the 4 GB kept free: no room')
    eq(h['said'], 'No room for another agent: memory is nearly full', 'and says why')
    s['mem']['avail'] = 32 * GB
    s['disk']['free'] = 13 * GB
    eq(V.headroom(s, 10)['limits']['disk'], 1, 'disk: 2 GB per agent above min_free_gb')
    s['disk']['free'] = 8 * GB
    eq((V.headroom(s, 10)['room'], V.headroom(s, 10)['by']), (0, 'disk'), 'under min_free_gb: none')
    s['disk']['free'] = 900 * GB
    h = V.headroom(s, 10, {'weekly': 91.0, 'session': 10.0}, {'weekly_max': 90, 'session_max': 90})
    eq((h['room'], h['by']), (0, 'usage'), 'a usage cap reached: none')
    h = V.headroom(s, 10, {'weekly': 91.0}, {'weekly_max': 90}, fallback=True)
    eq((h['room'], h['said']), (6, 'Room for 6 more agents, on [models] fallback: a usage cap is reached'),
       'B157: new tasks start down the chain, and it says so')
    check('usage' not in h['limits'], 'so usage sets no limit')
    low = snap(mem={'total': 30 * GB, 'avail': 3 * GB})
    eq(V.headroom(low, 10, {'weekly': 91.0}, {'weekly_max': 90}, fallback=True)['said'],
       'No room for another agent: memory is nearly full', 'another limit still holds')
    eq(V.headroom(s, 10, {'weekly': 50.0}, {'weekly_max': 90}, fallback=True)['said'], 'Room for 6 more agents',
       'under the caps the chain is not named')
    h = V.headroom(s, 10, {'weekly': 50.0}, {'weekly_max': 90})
    check('usage' not in h['limits'], 'under the caps: usage sets no limit')
    eq(V.headroom(snap(), 10)['room'], None, 'nothing read: unknown, not zero')
    eq(V.headroom(snap(cpu={'threads': 8}), 10)['limits'], {}, 'threads without a load average: no CPU limit')


def test_fallback_room():
    print('B157: a project past the usage caps has room while its [models] fallback has a free provider')
    t = tmpdir()
    root = t / 'proj'
    root.mkdir()
    git(root, 'init', '-q')

    def room(models: str) -> tuple:
        write(root / 'runner.toml', '[run]\nweekly_max = 90\n' + models)
        v = V.Vitals(lambda: [root], None, tailscale=False, usage=lambda: {}, info=lambda r: {'up': True},
                     sampler=V.Sampler())
        v.started, v.usage = True, {'weekly': 91.0}
        v.snap = snap(mem={'total': 64 * GB, 'avail': 64 * GB})
        h = v.device(detail=False)['headroom']
        return h['room'], '[models] fallback' in h['said']

    with mock.patch.dict(os.environ, {'PI_CODING_AGENT_DIR': str(t / 'pi'), 'GEMINI_API_KEY': 'k'}):
        eq(room(''), (0, False), 'no chain: none')
        eq(room('[models]\nfallback = ["sonnet"]\n'), (0, False), 'only claude in it: none')
        chain = '[models]\nfallback = ["sonnet", "gemini:pro-test"]\n'
        eq(room(chain), (6, True), 'a free provider: room')
        write(t / 'other' / 'runner.toml', '[run]\nweekly_max = 95\n' + chain)
        git(t / 'other', 'init', '-q')
        write(root / 'runner.toml', '[run]\nweekly_max = 90\n')
        v = V.Vitals(lambda: [root, t / 'other'], None, tailscale=False, usage=lambda: {},
                     info=lambda r: {'up': True}, sampler=V.Sampler())
        v.started, v.usage, v.snap = True, {'weekly': 91.0}, snap(mem={'total': 64 * GB, 'avail': 64 * GB})
        eq(v.device(detail=False)['headroom']['room'], 0, 'a chain counts only with its own project\'s caps reached')
        from agent_runner.config import Config
        capped = write(Config(root).notes('capped.json'), json.dumps({'gemini': time.time() + 900}))
        eq(room(chain), (0, False), 'its provider capped: none')
        write(capped, json.dumps({'gemini': time.time() - 1}))
        eq(room(chain), (6, True), 'its cap over: room again')
        del os.environ['GEMINI_API_KEY']
        eq(room(chain), (0, False), 'no login: none')


# --- collectors -------------------------------------------------------------------------------------------------

STAT1 = 'cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 50 0 50 400 0 0 0 0 0 0\ncpu1 50 0 50 400 0 0 0 0 0 0\nintr 1\n'
STAT2 = 'cpu  200 0 200 1000 0 0 0 0 0 0\ncpu0 150 0 50 500 0 0 0 0 0 0\ncpu1 50 0 150 500 0 0 0 0 0 0\nintr 1\n'


def proc_stat_line(pid: int, name: str, ppid: int, ticks: int, rss_pages: int) -> str:
    f = ['S', str(ppid)] + ['0'] * 9 + [str(ticks), '0'] + ['0'] * 8 + [str(rss_pages), '0', '0']
    return f'{pid} ({name}) ' + ' '.join(f) + '\n'


def fixture_tree(t: Path) -> tuple[Path, Path]:
    proc, sysfs = t / 'proc', t / 'sys'
    write(proc / 'stat', STAT1)
    write(proc / 'meminfo', 'MemTotal:       32000000 kB\nMemFree:  1000 kB\nMemAvailable:   16000000 kB\n')
    write(proc / 'loadavg', '3.50 2.00 1.00 2/900 12345\n')
    write(proc / '10' / 'stat', proc_stat_line(10, 'claude', 1, 100, 1000))
    write(proc / '11' / 'stat', proc_stat_line(11, 'cargo build', 10, 50, 500))
    write(proc / '12' / 'stat', proc_stat_line(12, 'firefox', 1, 10, 2000))
    mon = sysfs / 'class' / 'hwmon'
    write(mon / 'hwmon0' / 'name', 'nvme\n')
    write(mon / 'hwmon0' / 'temp1_input', '41850\n')
    write(mon / 'hwmon0' / 'temp1_label', 'Composite\n')
    write(mon / 'hwmon1' / 'name', 'k10temp\n')
    write(mon / 'hwmon1' / 'temp1_input', '61250\n')
    write(mon / 'hwmon1' / 'temp1_label', 'Tctl\n')
    write(mon / 'hwmon1' / 'temp3_input', '55000\n')
    write(mon / 'hwmon1' / 'temp3_label', 'Tccd1\n')
    write(mon / 'hwmon2' / 'name', 'broken\n')
    write(mon / 'hwmon2' / 'temp1_input', 'garbage\n')
    card = sysfs / 'class' / 'drm' / 'card1' / 'device'
    write(card / 'gpu_busy_percent', '6\n')
    write(card / 'mem_info_vram_used', str(2 * GB) + '\n')
    write(card / 'mem_info_vram_total', str(16 * GB) + '\n')
    write(card / 'uevent', 'DRIVER=amdgpu\nPCI_ID=1002:744C\n')
    write(card / 'hwmon' / 'hwmon5' / 'temp1_input', '44000\n')
    (sysfs / 'class' / 'drm' / 'card1-DP-1').mkdir(parents=True)  # a connector, not a card
    (sysfs / 'class' / 'drm' / 'card0' / 'device').mkdir(parents=True)  # a card that reports nothing
    return proc, sysfs


def test_linux_collectors():
    print('collectors read fixture /proc and /sys trees')
    t = tmpdir()
    proc, sysfs = fixture_tree(t)
    ticks = V.linux_cpu_ticks(proc)
    eq(ticks['all'], (200, 1000), '/proc/stat: busy and total')
    eq(len(ticks['cores']), 2, 'one per core')
    eq(V.linux_mem(proc), {'total': 32000000 * 1024, 'avail': 16000000 * 1024}, 'meminfo: MemAvailable')
    eq(V.linux_load(proc), 3.5, 'loadavg: the 1-minute load')
    sensors = V.hwmon_sensors(sysfs)
    eq([(s['chip'], s['label'], s['c']) for s in sensors],
       [('nvme', 'Composite', 41.9), ('k10temp', 'Tctl', 61.2), ('k10temp', 'Tccd1', 55.0)],
       'hwmon: every readable temperature with its label; an unreadable one is left out')
    eq(V.cpu_temp(sensors), 61.2, 'the CPU temperature is Tctl')
    eq(V.cpu_temp([{'chip': 'coretemp', 'label': 'Core 0', 'c': 50.0}, {'chip': 'coretemp', 'label': 'Core 1', 'c': 57.0}]),
       57.0, 'no Tctl or package: the hottest CPU sensor')
    eq(V.cpu_temp([{'chip': 'nvme', 'label': 'Composite', 'c': 40.0}]), None, 'no CPU sensor: no CPU temperature')
    eq(V.drm_gpus(sysfs), [{'pct': 6.0, 'vram_used': 2 * GB, 'vram_total': 16 * GB, 'temp': 44.0, 'name': 'amdgpu'}],
       'drm: the amdgpu card; the connector and the card that reports nothing are left out')
    table = V.proc_table(proc)
    eq(sorted(table), [10, 11, 12], 'the process table')
    eq(table[11][0], 10, 'with each parent')
    eq(table[11][3], 'cargo build', 'and its name, spaces and all')
    eq(V.tree_usage(10, table, {10: 5.0, 11: 20.0, 12: 9.0}), (25.0, 1500 * V.page_size()),
       'a session\'s CPU and memory count every process under it')
    eq(V.tree_usage(99, table, {}), None, 'a session whose process is gone: none')

    print('Sampler: CPU busy from two looks; what cannot be read is hidden, never zero')
    s = V.Sampler(proc, sysfs, 'linux', run=lambda *a, **k: SimpleNamespace(returncode=1, stdout=''), disk=t)
    first = s.sample(now=1000)
    check('pct' not in first['cpu'], 'the first sample has no CPU busy (one look), rather than 0%')
    eq((first['cpu']['threads'], first['cpu']['load'], first['cpu']['temp']), (2, 3.5, 61.2), 'threads, load, temp')
    eq(first['gpus'][0]['name'], 'amdgpu', 'the GPU')
    check('disk' in first and first['disk']['total'] > 0, 'the disk')
    write(proc / 'stat', STAT2)
    write(proc / '10' / 'stat', proc_stat_line(10, 'claude', 1, 160, 1000))
    second = s.sample(now=1030)
    eq(second['cpu']['pct'], 50.0, 'busy between the two looks: (400-200)/(1400-1000) ticks')
    eq(second['cpu']['cores'], [50.0, 50.0], 'per core')
    check(second['top'][0]['name'] == 'claude', 'top processes, the busiest first')

    print('a machine with none of it: every section is hidden')
    bare = V.Sampler(t / 'none', t / 'none', 'linux', run=lambda *a, **k: SimpleNamespace(returncode=1, stdout=''),
                     disk=t / 'none')
    got = bare.sample(now=1)
    eq(sorted(got), ['host', 'os', 't'], 'no cpu, mem, disk, gpus or sensors keys at all')
    eq(V.meters(got), [], 'and no meters')
    eq(V.meters({'cpu': {'pct': 38.0, 'temp': 61.0}, 'mem': {'total': 30 * GB, 'avail': 17 * GB}}),
       [{'name': 'CPU', 'pct': 38.0, 'said': '38% 61°'}, {'name': 'RAM', 'pct': 43.3, 'said': '13/30 GB'}],
       'meters only for what was read')


def fake_run(outputs: dict):
    def run(argv, **kw):
        for k, v in outputs.items():
            if argv[0] == k:
                return SimpleNamespace(returncode=0, stdout=v, stderr='')
        return SimpleNamespace(returncode=1, stdout='', stderr='')
    return run


def test_other_collectors():
    print('nvidia-smi, macOS (sysctl, vm_stat, ps) and Windows (PowerShell CIM)')
    run = fake_run({'nvidia-smi': 'NVIDIA GeForce RTX 4090, 37, 66, 4096, 24564\nbad line\n'})
    eq(V.nvidia_gpus(run), [{'name': 'NVIDIA GeForce RTX 4090', 'pct': 37.0, 'temp': 66.0,
                             'vram_used': 4096 * 2**20, 'vram_total': 24564 * 2**20}], 'nvidia-smi\'s CSV')
    eq(V.nvidia_gpus(fake_run({})), [], 'nvidia-smi failing: no GPU')
    vm = ('Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free:      100000.\n'
          'Pages active:    200000.\nPages inactive:  50000.\nPages speculative:  10000.\n')
    mac = V.mac_stats(fake_run({'sysctl': '10\n17179869184\n{ 2.50 2.00 1.50 }\n', 'vm_stat': vm,
                                'ps': ' 50.0\n 30.0\n 20.0\n'}))
    eq(mac, {'threads': 10, 'load': 2.5, 'mem': {'total': 17179869184, 'avail': 160000 * 16384}, 'pct': 10.0},
       'macOS: threads, load, free + inactive + speculative pages, CPU busy from ps')
    eq(V.mac_stats(fake_run({})), {}, 'macOS with nothing readable: nothing')
    win = V.windows_stats(fake_run({'powershell': json.dumps({'free': 8000000, 'total': 16000000, 'pct': 25,
                                                               'threads': 8})}))
    eq(win, {'threads': 8, 'pct': 25.0, 'load': 2.0, 'mem': {'total': 16000000 * 1024, 'avail': 8000000 * 1024}},
       'Windows: CIM memory in KB, load percentage standing in for a load average')
    eq(V.windows_stats(fake_run({'powershell': 'not json'})), {}, 'Windows unreadable: nothing')
    s = V.Sampler(platform='darwin', run=fake_run({'sysctl': '10\n17179869184\n{ 2.50 2.00 1.50 }\n', 'vm_stat': vm}),
                  disk=tmpdir())
    got = s.sample(now=5)
    eq((got['os'], got['cpu'], 'gpus' in got, 'sensors' in got), ('macos', {'threads': 10, 'load': 2.5}, False, False),
       'a Mac sample: no GPU or sensors to show, so none listed')


# --- history ----------------------------------------------------------------------------------------------------

def test_history():
    print('History keeps a day of points and gives sparklines')
    t = tmpdir()
    h = V.History(t / 'vitals.jsonl', keep=3600)
    for i in range(240):  # 2 h at 30 s
        h.add({'t': 1000 + i * 30, 'cpu': float(i % 10), 'disk': 900.0})
    eq(len(h.points), 121, 'only the last hour is kept')
    check(min(p['t'] for p in h.points) >= 1000 + 239 * 30 - 3600, 'the oldest dropped')
    again = V.History(t / 'vitals.jsonl', keep=3600)
    check(len(again.points) >= 121, 'read back after a restart')
    size = (t / 'vitals.jsonl').stat().st_size
    check(size < 4 * 121 * 60, f'the file is rewritten as it grows ({size} bytes)')
    sp = h.series('cpu', now=1000 + 239 * 30, n=12)
    eq(len(sp), 12, 'a sparkline of n points')
    check(all(x is not None for x in sp[1:]), 'each a bucket\'s mean')
    eq(h.series('gpu', now=1000 + 239 * 30, n=4), [None] * 4, 'a key never read: all gaps, never zeros')
    eq(V.point({'t': 5, 'cpu': {'threads': 4}, 'mem': {'total': 4 * GB, 'avail': 1 * GB}}),
       {'t': 5, 'mem': 75.0}, 'a point keeps only what was read')
    print('a day of points is about 300 KB')
    day = V.History(t / 'day.jsonl')
    s = {'t': 0, 'cpu': 38.4, 'temp': 61.2, 'gpu': 6.0, 'mem': 45.3, 'disk': 902.1}
    for i in range(2880):
        day.add({**s, 't': 1_795_000_000 + i * 30})
    kb = (t / 'day.jsonl').stat().st_size / 1024
    check(150 < kb < 400, f'{kb:.0f} KB for 2880 samples')


# --- footprint and Clean ----------------------------------------------------------------------------------------

def clean_fixture():
    t = tmpdir()
    root = t / 'proj'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'commit', '-q', '--allow-empty', '-m', 'start')
    home = t / 'runs' / 'proj'
    home.mkdir(parents=True)
    git(root, 'worktree', 'add', '-q', '--detach', str(home / 's1'), 'main')  # merged: main itself
    git(root, 'worktree', 'add', '-q', '-b', 'task/X', str(home / 's2'), 'main')
    write(home / 's2' / 'new.txt', 'work')
    git(home / 's2', 'add', 'new.txt')
    git(home / 's2', 'commit', '-q', '-m', 'unmerged work')
    git(root, 'worktree', 'add', '-q', '--detach', str(home / 's3'), 'main')
    write(home / 's3' / 'dirty.txt', 'uncommitted')
    git(root, 'worktree', 'add', '-q', '--detach', str(home / 'merge'), 'main')
    git(root, 'branch', 'wip/B1')
    write(home / 'plan' / 'TODO.md', 'p' * 300_000)  # not a worktree: never Clean's
    notes = root / '.runner'
    write(notes / 'run.log', 'x' * 1000)
    write(notes / 'events.jsonl', 'y' * 500)
    tmp = t / 'tmp'
    sess = tmp / 'claude-1000' / V.slug(home / 's1')
    ended, live, recent, resumed = (sess / f'{n}0000000-0000-0000-0000-000000000000' for n in 'abcd')
    for d in (ended, live, recent, resumed):
        write(d / 'scratch.bin', 'z' * 2048)
    old = time.time() - 2 * 3600
    for d in (ended, live, resumed):
        for f in (d / 'scratch.bin', d):
            os.utime(f, (old, old))
    control = tmp / 'claude-1000' / V.slug(root) / 'f0000000-0000-0000-0000-000000000000'
    write(control / 'notes.txt', 'c' * 1024)
    os.utime(control, (old, old))
    other = tmp / 'claude-1000' / '-home-someone-else' / 'e0000000-0000-0000-0000-000000000000'
    write(other / 'f', 'not ours')
    os.utime(other, (old, old))
    p = V.Project(root, home, notes, 'main', up=False, busy=set(), resume={resumed.name})
    return SimpleNamespace(t=t, root=root, home=home, p=p, tmp=tmp, ended=ended, live=live, recent=recent,
                           resumed=resumed, other=other, control=control)


def test_clean():
    print('footprint: worktrees, session temp folders, logs and wip/ branches, each sized')
    f = clean_fixture()
    with mock.patch.dict(os.environ, {'CLAUDE_CODE_TMPDIR': str(f.tmp)}):
        foot = V.footprint([f.p], live={f.live.name}, cwds=[])
    eq(foot['logs'], 1500, 'logs: the notes\' .log files and events')
    eq(foot['tmp'], 4 * 2048 + 1024, 'temp folders: the runner worktrees\' sessions and the main checkout\'s, '
       'not another project\'s')
    eq([w['branch'] for w in foot['wip']], ['wip/B1'], 'the wip/ branches')
    check(foot['worktrees'] > 0 and foot['total'] == foot['worktrees'] + foot['tmp'] + foot['logs'], 'sized and summed')
    check(any(x['path'].endswith('plan') for x in foot['largest']), 'largest folders cover the whole run home')

    print('Clean\'s safe list')
    plan = foot['clean']
    ids = {i['id']: i for i in plan}
    paths = {i['path'] for i in plan}
    check(str(f.ended) in paths, 'an ended session\'s temp folder is on it')
    check(str(f.live) not in paths, 'not one a running process names')
    check(str(f.recent) not in paths, 'not one written to in the last hour')
    check(str(f.resumed) not in paths, 'not one a resume waits for')
    check(str(f.other) not in paths, 'not another project\'s')
    check(str(f.control) not in paths, 'not a main checkout session\'s with no registry read: sized only')
    eq(foot['tmp_largest']['size'], 2048, 'the largest temp folder')
    check(str(f.home / 's1') in paths, 'a worktree merged into main with nothing uncommitted is on it')
    check(str(f.home / 'merge') in paths, 'the merge worktree too, while the run is off')
    check(str(f.home / 's2') not in paths, 'not one with unmerged commits')
    check(str(f.home / 's3') not in paths, 'not one with uncommitted files')
    check(str(f.home / 'plan') not in paths, 'not the plan clone')
    wip = [i for i in plan if i['kind'] == 'wip']
    eq([(i['path'], i['ask']) for i in wip], [('wip/B1', True)], 'wip/ branches only when the person ticks them')
    check(not any(i['ask'] for i in plan if i['kind'] != 'wip'), 'the rest come ticked')

    up = V.Project(f.root, f.home, f.p.notes, 'main', up=True, busy={'s1'}, resume=set())
    with mock.patch.dict(os.environ, {'CLAUDE_CODE_TMPDIR': str(f.tmp)}):
        plan_up = V.footprint([up], live=set(), cwds=[])['clean']
    check(not [i for i in plan_up if i['kind'] == 'worktree'], 'a run up: none of its worktrees')
    with mock.patch.dict(os.environ, {'CLAUDE_CODE_TMPDIR': str(f.tmp)}):
        plan_cwd = V.footprint([f.p], live=set(), cwds=[str(f.home / 's1' / 'sub')])['clean']
    check(str(f.home / 's1') not in {i['path'] for i in plan_cwd}, 'nor one a process works in')
    with mock.patch.dict(os.environ, {'CLAUDE_CODE_TMPDIR': str(f.tmp)}):
        plan_win = V.footprint([f.p], live=None, cwds=[])['clean']
    check(not [i for i in plan_win if i['kind'] == 'tmp'], 'no /proc to tell (Windows): no temp folder at all')

    print('clean removes only what is on a fresh list')
    res = V.clean(['tmp:/etc', 'worktree:' + str(f.home / 's2')], plan)
    eq(res['removed'], [], 'ids not on the list remove nothing')
    check(f.home.joinpath('s2').is_dir(), 's2 stays')
    chosen = ['tmp:' + str(f.ended), 'worktree:' + str(f.home / 's1')]
    res = V.clean(chosen, plan)
    eq(res['removed'], chosen, 'the chosen temp folder and worktree go')
    check(not f.ended.exists() and not (f.home / 's1').exists(), 'gone from disk')
    check('s1' not in git(f.root, 'worktree', 'list'), 'and git forgot the worktree')
    eq(res['freed'], 2048 + ids['worktree:' + str(f.home / 's1')]['size'], 'what it freed')
    check(f.live.exists() and f.recent.exists() and f.resumed.exists(), 'the rest stay')
    check('wip/B1' in git(f.root, 'branch', '--list', 'wip/*'), 'an unticked wip/ branch stays')
    res = V.clean([wip[0]['id']], plan)
    eq(res['removed'], [wip[0]['id']], 'a ticked one goes')
    check('wip/B1' not in git(f.root, 'branch', '--list', 'wip/*'), 'deleted')
    item = {'id': 'worktree:x', 'kind': 'worktree', 'path': str(f.home / 's3'), 'size': 1, 'root': str(f.root)}
    res = V.clean(['worktree:x'], [item])
    check(not res['ok'] and (f.home / 's3').is_dir(), 'git itself keeps a worktree with changes, whatever the list says')


def fake_proc(t: Path, starts: dict[int, str], cmdlines: dict[int, str] | None = None) -> Path:
    proc = t / 'proc'
    proc.mkdir(exist_ok=True)
    for pid, start in starts.items():
        write(proc / str(pid) / 'stat', f'{pid} (claude (x)) S ' + ' '.join(['0'] * 18) + f' {start} 0 0')
        write(proc / str(pid) / 'cmdline', (cmdlines or {}).get(pid, 'claude'))
    return proc


def test_open_sessions():
    print('Claude Code\'s registry: which sessions are open')
    t = tmpdir()
    a, b, c, e, g = (f'{n}0000000-0000-0000-0000-000000000000' for n in '12345')
    proc = fake_proc(t, {10: '500', 11: '900', 12: '7'}, {12: f'claude\0--resume\0{e}'})
    reg = t / 'sessions'
    eq(V.open_sessions(proc, reg), (set(), False), 'no registry: not read in full')
    for pid, sid, start in ((10, a, '500'), (11, b, '800'), (99, c, '1')):
        write(reg / f'{pid}.json', json.dumps({'pid': pid, 'sessionId': sid, 'procStart': start}))
    write(reg / '10.abc.key', 'secret')
    eq(V.open_sessions(proc, reg), ({a}, True), 'open: its pid alive with that procStart; not a reused pid or a dead one')
    write(reg / '98.json', '{broken')
    eq(V.open_sessions(proc, reg)[1], True, 'a dead pid\'s unreadable entry does not matter')
    eq(V.live_now(proc, reg), ({a, e}, True), 'live: the registry\'s and those a process names')
    write(reg / '12.json', '{broken')
    eq(V.live_now(proc, reg), ({a, e}, False), 'an unreadable entry of a live pid: not in full')
    write(reg / '12.json', json.dumps({'pid': 12, 'procStart': '7'}))
    eq(V.open_sessions(proc, reg)[1], False, 'nor one that names no session')
    write(reg / '12.json', json.dumps({'pid': 12, 'sessionId': g}))
    eq(V.open_sessions(proc, reg), ({a, g}, True), 'no procStart to tell by: open')
    eq(V.live_now(t / 'none', reg), (None, False), 'no /proc: cannot tell')
    with mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(t)}):
        eq(V.open_sessions(proc), ({a, g}, True), 'found under CLAUDE_CONFIG_DIR')


def test_auto_clean():
    print('the regular footprint walk removes ended sessions\' temp folders itself')
    f = clean_fixture()
    now = time.time() + 30 * 24 * 3600  # the fixture's own files are all long quiet; each folder below is dated
    main = f.tmp / 'claude-1000' / V.slug(f.root)
    sids = {k: f'{i}1111111-1111-1111-1111-111111111111' for i, k in enumerate(
        ('opened', 'reused', 'h23', 'h25', 'c1', 'c4', 'c5', 'feed', 'queued', 'asked'))}

    def folder(sid: str, hours: float, under: Path = main) -> Path:
        d = under / sid
        write(d / 'x.bin', 'z' * 1000)
        for q in (d / 'x.bin', d):
            os.utime(q, (now - hours * 3600,) * 2)
        return d
    dirs = {k: folder(s, 23 if k == 'h23' else 25) for k, s in sids.items()}
    cut = folder('a2222222-2222-2222-2222-222222222222', 25, f.tmp / 'claude-1000' / V.slug(f.home / 's2'))
    fresh = folder('b2222222-2222-2222-2222-222222222222', 0.5, f.tmp / 'claude-1000' / V.slug(f.home / 's1'))
    write(f.p.notes / 'slot2.log', f'=== 2026-01-01T00:00:00 X session {cut.name} m\n')
    write(f.p.notes / 'control.sid', sids['c1'] + '\n')
    write(f.p.notes / 'control4.pid', f'77 {sids["c4"]}')
    write(f.p.notes / 'control5.sid', sids['c5'])  # closed on purpose: no pid file
    write(f.p.notes / 'remote' / 'feed.sid', sids['feed'] + '\n./run\n')
    write(f.p.notes / 'B7.resume', json.dumps({'slot': 1, 'sid': sids['queued'], 'why': 'x'}))
    write(f.p.notes / 'B8.ask', json.dumps({'sid': sids['asked'], 'question': 'x'}))
    # symlinks out of the temp root
    out = f.t / 'elsewhere'
    far = folder('c2222222-2222-2222-2222-222222222222', 99, out / V.slug(f.root))
    if os.name != 'nt':  # symlinks need rights there
        (f.tmp / 'claude-2000').symlink_to(out, target_is_directory=True)
        (f.tmp / 'claude-3000').mkdir()
        (f.tmp / 'claude-3000' / V.slug(f.root)).symlink_to(out / V.slug(f.root), target_is_directory=True)
        (dirs['h25'] / 'link').symlink_to(out, target_is_directory=True)
        os.utime(dirs['h25'] / 'link', (now - 25 * 3600,) * 2, follow_symlinks=False)
    os.utime(dirs['h25'], (now - 25 * 3600,) * 2)

    proc = fake_proc(f.t, {10: '500', 11: '900'}, {10: f'claude --resume {f.live.name}'})
    reg = f.t / 'sessions'
    write(reg / '10.json', json.dumps({'pid': 10, 'sessionId': sids['opened'], 'procStart': '500'}))
    write(reg / '11.json', json.dumps({'pid': 11, 'sessionId': sids['reused'], 'procStart': '1'}))
    said = []
    s = SimpleNamespace(proc=proc, disk=f.t, procs={}, proc_cpu={}, sample=lambda now: snap())
    v = V.Vitals(lambda: [], None, tailscale=False, sampler=s, usage=lambda: {}, registry=reg, log=said.append)

    def there() -> set[str]:
        return {k for k, d in dirs.items() if d.exists()}

    with mock.patch.dict(os.environ, {'CLAUDE_CODE_TMPDIR': str(f.tmp)}), \
            mock.patch('tempfile.gettempdir', lambda: str(f.tmp)):
        before = set(dirs)
        s.proc = f.t / 'none'
        v.refresh_footprint([f.p], now)
        check(there() == before and f.ended.exists(), 'no /proc: nothing is removed')
        s.proc = proc
        plan = v.refresh_footprint([f.p], now, auto=False)['clean']
        check(there() == before and f.ended.exists(), 'nor by the walk for the person\'s Clean list')
        listed = {i['path'] for i in plan if i['kind'] == 'tmp'}
        check(str(dirs['h25']) in listed and str(dirs['opened']) not in listed, 'it lists a main checkout\'s ended one')
        write(f.p.notes / 'B9.resume', '{"slot": 1')
        v.refresh_footprint([f.p], now)
        check(there() == before and f.ended.exists(), 'a resume that cannot be read may name any session: none goes')
        (f.p.notes / 'B9.resume').unlink()
        write(f.p.notes / 'control6.ask', 'a1111111-1111-1111-1111-111111111111\n')  # a one-ask mark: waits for nothing
        write(reg / '11.json', '{broken')
        v.refresh_footprint([f.p], now)
        eq(there(), before, 'unreadable registry: no main checkout folder goes')
        check(not f.ended.exists(), 'an ended worktree session\'s still does')
        check(f.live.exists() and f.resumed.exists() and fresh.exists(), 'not a live, queued or recent one')
        check(cut.exists(), 'nor a cut-off one its slot will resume')
        check(len(said) == 1 and 'freed' in said[0], f'logged: {said}')
        write(reg / '11.json', json.dumps({'pid': 11, 'sessionId': sids['reused'], 'procStart': '1'}))

        foot = V.footprint([f.p], V.live_now(proc, reg)[0], now, registry=True)
        rm = []
        V.auto_clean(foot, [f.p], lambda: ({*sids.values(), f.control.name}, True), now, rm=rm.append)
        eq(rm, [], 'each is looked at again just before: one opened since stays')
        check(not [i for i in foot['clean'] if i['kind'] == 'tmp'], 'and leaves the list')

        v.refresh_footprint([f.p], now)
    eq(before - there(), {'reused', 'h25', 'c5'}, 'gone: quiet 25 h, a reused pid\'s, a closed control session\'s; '
       'kept: open, quiet 23 h, c1, cN with a pid file, the feed, queued to resume, waiting for an answer')
    check(far.exists() and (far / 'x.bin').exists(), 'nothing behind a symlink goes')
    check(f.other.exists(), 'nor another project\'s')
    check((f.home / 's1').is_dir() and 'wip/B1' in git(f.root, 'branch', '--list', 'wip/*'), 'worktrees and wip/ stay')
    kinds = {i['kind'] for i in v.foot['clean']}
    eq(kinds, {'worktree', 'wip'}, 'and wait for the person in Clean')
    eq(v.foot['total'], v.foot['worktrees'] + v.foot['tmp'] + v.foot['logs'], 'the sums follow')
    check(not any(x['path'] == str(dirs['h25']) for x in v.foot['largest']), 'the largest folders too')
    eq(len(said), 2, 'logged again')

    print('a folder that cannot be removed stays on the list')
    d = folder('d2222222-2222-2222-2222-222222222222', 25)

    def refuse(p):
        raise OSError('busy')
    with mock.patch.dict(os.environ, {'CLAUDE_CODE_TMPDIR': str(f.tmp)}):
        foot = V.footprint([f.p], V.live_now(proc, reg)[0], now, registry=True)
        tmp = foot['tmp']
        eq(V.auto_clean(foot, [f.p], lambda: V.live_now(proc, reg), now, rm=refuse), (0, 0), 'freed nothing')
    check(foot['tmp'] == tmp and str(d) in {i['path'] for i in foot['clean']}, 'still counted and listed')


# --- alerts -----------------------------------------------------------------------------------------------------

def test_alerts():
    print('thresholds become alerts')
    fine = snap(disk={'path': '/', 'total': 1000 * GB, 'free': 500 * GB}, mem={'total': 32 * GB, 'avail': 16 * GB},
                cpu={'temp': 60.0}, gpus=[{'name': 'amdgpu', 'temp': 50.0}])
    eq(V.alerts(fine, 10, {'tmp': 49 * GB, 'clean': []}), [], 'all fine: nothing')
    bad = snap(disk={'path': '/', 'total': 1000 * GB, 'free': 8 * GB}, mem={'total': 32 * GB, 'avail': 2 * GB},
               cpu={'temp': 95.0}, gpus=[{'name': 'amdgpu', 'temp': 91.0}])
    over = {'tmp': 51 * GB, 'tmp_largest': {'path': '/t/big', 'size': 40 * GB},
            'clean': [{'kind': 'tmp', 'id': 'tmp:/t/big'}]}
    got = V.alerts(bad, 10, over)
    eq([a['id'] for a in got], ['box:disk', 'box:hot:CPU', 'box:hot:GPU amdgpu', 'box:memory', 'box:tmp'],
       'disk under min_free_gb, a hot CPU and GPU, memory nearly full, temp folders over 5% of the disk')
    eq(got[0]['what'], 'box: 8.0 GB free on disk, under min_free_gb (10 GB): no new task starts', 'in plain words')
    eq([a['clean'] for a in got], [True, False, False, False, True], 'Clean is offered where it helps')
    eq(V.alerts(bad, 0, None)[0]['id'], 'box:hot:CPU', 'min_free_gb 0: no disk alert; no footprint yet: no temp alert')
    eq(got[-1]['what'], 'box: session temp folders use 51 GB (over 5% of the 1000 GB disk); the largest is /t/big '
       '(40 GB). Clean frees the ended sessions\'', 'the size, the largest folder and Clean')
    stuck = V.alerts(fine, 10, {**over, 'clean': [{'kind': 'worktree', 'id': 'worktree:x'}]})[0]
    check(not stuck['clean'] and 'Clean' not in stuck['what'] and '/t/big' in stuck['what'],
          'nothing tmp to free: no Clean, no word of it')
    eq(V.alerts(fine, 10, {**over, 'tmp': 50 * GB}), [], 'exactly 5%: not over')
    eq(V.alerts(snap(), 10, over), [], 'no disk read: no temp alert')
    eq(V.verdict(V.headroom(bad, 10), got)['level'], 'bad', 'a card with an alert shows it, not its headroom')
    eq(V.verdict(V.headroom(fine, 10), [])['said'], 'Room for 6 more agents', 'else its headroom')

    print('each alert is pushed once while it lasts, again when it comes back')
    fresh, said = V.new_alerts(got[:2], set())
    eq([a['id'] for a in fresh], ['box:disk', 'box:hot:CPU'], 'new ones go out')
    fresh, said = V.new_alerts(got[:2], said)
    eq(fresh, [], 'not again while they last')
    fresh, said = V.new_alerts(got[1:2], said)
    fresh, said = V.new_alerts(got[:2], said)
    eq([a['id'] for a in fresh], ['box:disk'], 'one that cleared and came back goes again')


def test_push():
    print('an alert goes to each running project\'s runner feed as a needs-you line')
    t = tmpdir()
    up, off = t / 'up', t / 'off'
    for r in (up, off):
        r.mkdir()
        git(r, 'init', '-q')
        write(r / 'runner.toml', '[run]\nslots = 1\n')
    with mock.patch('agent_runner.cmds.run_info', lambda root: {'up': root == up}):
        n = V.push_alert([up, off], 'box: CPU at 95°C (over 90°C)', 'box')
    eq(n, 1, 'only the project whose run is up')
    from agent_runner.config import Config
    ev = json.loads(Config(up).notes('events.jsonl').read_text(encoding='utf-8').splitlines()[-1])
    eq((ev['device'], ev['text']), ('box', 'box: CPU at 95°C (over 90°C)'), 'written as an event')
    from agent_runner.state import EV_DEVICE
    eq(ev['kind'], EV_DEVICE, 'as a device alert, not a Claude Code drift')
    check(not Config(off).notes('events.jsonl').exists(), 'none for a project with no run (no feed to push it)')
    from agent_runner import status
    line = status.since_event(ev, {})
    eq(line[2], 'needs you: box: CPU at 95°C (over 90°C)', 'the feed prints it as needs you, which it pushes')
    import datetime as dt
    nl = status.needs_you_line(ev, {}, dt.datetime.fromisoformat(ev['time']), [])
    check(nl and nl.endswith('needs you: box: CPU at 95°C (over 90°C)'), f'and the needs-you feed keeps it: {nl!r}')

    print('Vitals pushes each new alert once and keeps what it said over a restart')
    pushed = []
    s = SimpleNamespace(proc=t / 'none', sample=lambda now: snap(t=int(now), cpu={'temp': 99.0}), disk=t,
                        procs={}, proc_cpu={})
    tried = []
    v0 = V.Vitals(lambda: [], None, tailscale=False, sampler=s, usage=lambda: {},
                  push=lambda roots, what, host: tried.append(what) and 0)
    v0.foot, v0.foot_at = {}, time.time()
    v0.tick(walk=True)
    v0.tick(walk=True)
    eq(len(tried), 2, 'no run up took it: tried again on the next sample, so a run started later hears it')
    v = V.Vitals(lambda: [], t / 'store', tailscale=False, sampler=s, usage=lambda: {},
                 push=lambda roots, what, host: pushed.append(what) or 1)
    v.foot, v.foot_at = {}, time.time()
    v.tick(walk=True)
    v.tick(walk=True)
    eq(pushed, ['box: CPU at 99°C (over 90°C)'], 'pushed once over two samples')
    v2 = V.Vitals(lambda: [], t / 'store', tailscale=False, sampler=s, usage=lambda: {},
                  push=lambda roots, what, host: pushed.append(what) or 1)
    v2.foot, v2.foot_at = {}, time.time()
    v2.tick(walk=True)
    eq(len(pushed), 1, 'and not again after Home restarts')


# --- Home's vitals calls and peers --------------------------------------------------------------------------------

def get(url: str, data: dict | None = None) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 method='POST' if data is not None else 'GET',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode()
            return r.status, json.loads(body) if r.headers.get_content_type() == 'application/json' else body
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def fixed_sampler(host: str, t: Path):
    return SimpleNamespace(proc=t / 'none', disk=t, procs={}, proc_cpu={},
                           sample=lambda now: snap(host=host, t=int(now), cpu={'threads': 8, 'load': 1.0, 'pct': 12.5},
                                                   mem={'total': 16 * GB, 'avail': 10 * GB}))


def test_home_calls():
    print('Home answers the vitals calls: this machine, and a peer Home through /dev/ID')
    t = tmpdir()
    from agent_runner import home as H
    with mock.patch.dict(os.environ, {'AGENT_RUNNER_HOME_CONFIG': str(t / 'cfg')}):
        acted = []
        peer_v = V.Vitals(lambda: [], None, tailscale=False, sampler=fixed_sampler('rycs', t), usage=lambda: {},
                          sessions=lambda: [], push=lambda *a: 0)
        (t / 'proj').mkdir()
        peer = H.serve_home('PEERTOKEN', 0, '127.0.0.1', roots=lambda: [t / 'proj'], rows=lambda: [], vitals=peer_v,
                            act=lambda root, name, arg: acted.append((root, name, arg)) or {'ok': True, 'out': 'ok'})
        link = f'http://127.0.0.1:{peer.server_address[1]}/?t=PEERTOKEN'
        links = [link, 'http://127.0.0.1:1/?t=NOBODY']
        here_v = V.Vitals(lambda: [], None, peers=lambda: links, tailscale=False,
                          sampler=fixed_sampler('desk', t), usage=lambda: {}, sessions=lambda: [], push=lambda *a: 0)
        here = H.serve_home('HT', 0, '127.0.0.1', roots=lambda: [], rows=lambda: [], vitals=here_v)
        u = f'http://127.0.0.1:{here.server_address[1]}'
        try:
            here_v.foot = peer_v.foot = {'clean': [], 'tmp': 0}
            here_v.foot_at = peer_v.foot_at = time.time()
            eq(get(u + '/devices')[0], 403, 'the token gates it')
            code, d = get(u + '/devices?t=HT')
            eq(code, 200, '/devices answers')
            eq([x['host'] for x in d['devices']], ['desk', 'rycs', '127.0.0.1'],
               'this machine first, then each peer, an unreachable listed one too')
            eq(d['devices'][0]['verdict']['said'], 'Room for 5 more agents', 'each with its verdict')
            eq(d['devices'][2]['verdict']['said'], 'Not answering', 'one that does not answer says so')
            eq(d['devices'][0]['meters'][0]['said'], '12%', 'and its meters')
            pid = d['devices'][1]['id']
            code, page = get(u + f'/device?t=HT&id={pid}')
            check(code == 200 and 'Device Vitals' in page, 'the vitals page')
            code, dev = get(u + f'/dev/{pid}/vitals/device?t=HT')
            eq((code, dev['host'], dev['id']), (200, 'rycs', pid), 'a peer\'s detail goes through this Home')
            check({'headroom', 'machine', 'spark', 'footprint', 'clean', 'sessions'} <= set(dev), 'every section')
            code, dev = get(u + '/dev/local/vitals/device?t=HT')
            eq((code, dev['host']), (200, 'desk'), 'and this machine\'s')
            code, res = get(u + f'/dev/{pid}/act?t=HT', {'project': 'x', 'name': 'slots', 'arg': '+1'})
            eq(code, 404, 'a project the peer does not list: refused there')
            code, res = get(u + f'/dev/{pid}/act?t=HT', {'project': 'proj', 'name': 'slots', 'arg': '+1'})
            eq((code, acted), (200, [(t / 'proj', 'slots', '+1')]), '+ slot on a peer runs `slots +1` in its project')
            code, res = get(u + '/dev/local/act?t=HT', {'project': 'proj', 'name': 'slots', 'arg': '+1'})
            eq(code, 200, 'and on this machine through its own buttons')
            eq(res['ok'], False, 'which says when it lists no such project')
            code, res = get(u + f'/dev/{pid}/vitals/clean?t=HT', {'items': ['tmp:/home']})
            eq((code, res['removed']), (200, []), 'Clean on a peer: an id not on its list removes nothing')
            eq(get(u + '/dev/nope/vitals/device?t=HT')[0], 404, 'an unknown device')
        finally:
            here.stop()
            peer.stop()

    print('`home peer add|remove` keeps the links in the registry')
    with mock.patch.dict(os.environ, {'AGENT_RUNNER_HOME_CONFIG': str(t / 'cfg2')}):
        eq(H.peer_change('add', 'not a link')[0], False, 'a link without a token is refused')
        ok, said = H.peer_change('add', 'http://rycs:8770/?t=ABC')
        check(ok and 'rycs' in said, said)
        eq(H.load_registry()['peers'], ['http://rycs:8770/?t=ABC'], 'listed')
        H.peer_change('add', 'http://rycs:8770/?t=ABC')
        eq(len(H.load_registry()['peers']), 1, 'once')
        H.add_project(str(t))  # another registry write keeps the peers
        eq(H.load_registry()['peers'], ['http://rycs:8770/?t=ABC'], 'kept through other changes')
        eq(H.peer_change('remove', 'http://rycs:8770/?t=ABC')[0], True, 'removed')
        eq(H.peer_change('remove', 'http://rycs:8770/?t=ABC')[0], False, 'not listed any more')


def test_tailscale():
    print('Tailscale: the tailnet\'s online machines')
    out = json.dumps({'Self': {'HostName': 'desk'}, 'Peer': {
        'a': {'HostName': 'rycs', 'Online': True, 'TailscaleIPs': ['100.64.0.2', 'fd7a::2']},
        'b': {'HostName': 'phone', 'Online': False, 'TailscaleIPs': ['100.64.0.3']}}})
    eq(V.tailscale_hosts(fake_run({'tailscale': out})), [('rycs', '100.64.0.2')], 'online ones, by their IPv4')
    eq(V.tailscale_hosts(fake_run({})), [], 'no Tailscale: none')
    eq(V.peer_base('http://rycs:8770/?t=ABC'), ('http://rycs:8770', 'ABC'), 'a peer link')
    eq(V.peer_base('http://rycs:8770/'), None, 'no token: not a peer link')


def test_sessions():
    print('sessions: CPU and memory per slot and control session')
    procs = {10: (1, 0, 100, 'claude'), 11: (10, 0, 50, 'cargo'), 20: (1, 0, 300, 'claude'), 30: (1, 0, 7, 'x')}
    cpu = {10: 2.0, 11: 8.0, 20: 1.5, 30: 50.0}
    rows = [{'name': 'proj', 'rows': [{'name': 'run', 'pid': 0}, {'name': 's1', 'pid': 10, 'what': 'F5 · 3m'},
                                      {'name': 'c1', 'pid': 20, 'what': 'control session'},
                                      {'name': 's2', 'pid': 99, 'what': 'idle'}]}]
    eq(V.session_rows(rows, procs, cpu),
       [{'project': 'proj', 'name': 's1', 'what': 'F5 · 3m', 'cpu': 10.0, 'rss': 150},
        {'project': 'proj', 'name': 'c1', 'what': 'control session', 'cpu': 1.5, 'rss': 300}],
       'a session counts its whole process tree; a gone one is left out')
    t = tmpdir()
    p = V.Project(t / 'proj', t / 'runs', t / 'notes', 'main', up=True, busy={'s3'}, resume=set())
    (t / 'runs').mkdir()
    cwds = {10: str(t / 'runs' / 's1'), 11: str(t / 'runs' / 's3' / 'src'), 20: str(t / 'runs' / 's3'),
            30: str(t / 'elsewhere')}
    eq(V.worktree_rows([p], procs, cpu, cwds.get, have={('proj', 's1')}),
       [{'project': 'proj', 'name': 's3', 'what': 'running a task', 'cpu': 9.5, 'rss': 350}],
       'slots no marker names: by the worktree their processes work in')


if __name__ == '__main__':
    raise SystemExit(report([test_headroom, test_fallback_room, test_linux_collectors, test_other_collectors,
                             test_history, test_clean, test_open_sessions, test_auto_clean, test_alerts, test_push, test_home_calls, test_tailscale, test_sessions]))
