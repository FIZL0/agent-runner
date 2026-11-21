"""Control sessions: a person runs the run from an interactive session (briefs, names, asks, panes), idle
ones are closed, the control server, and the Remote Control processes a run started."""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import shlex
import shutil
import subprocess as sp
import sys
import threading
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

from agent_runner import plan as P, plansync, plat
from agent_runner.config import RUNNER, runner_cmd, shown_cmd
from agent_runner.state import (C, commit_plan, git, HIDDEN, init, log, MERGE, note, plan_rel, REPO_TAG, ROOT,
    RUN_TAG, TAG)
from agent_runner.brief import has_sheet
from agent_runner.slots import (attach_target, backend, background_env, background_session, entries, marker_pid, MUX,
    pi, PRESENCE_ENV, quiet_file, remote_on, REMOTE_URL, send_to_pane, silent, tmux, TmuxMux, transcript, window)
from agent_runner.slots import link_drift, remote_answer_drift
from agent_runner.merge import gate_alive


# --- control sessions: a person runs the run from an interactive session in the main checkout -------------

CONTROL_SERVER_WAIT = (30, 600)  # s before the control server restarts after it exits, doubling to the second


def control_ok() -> bool:
    """Control sessions are Claude Code sessions: none for pi."""
    return not pi()


def control_brief() -> str:
    """What every control session is told, through its SessionStart hook (`control --brief` prints it)."""
    from agent_runner.guide import CONTROL, CONTROL_ANSWER, CONTROL_FEED_WATCH, CONTROL_WATCH
    notes = Path(C.run['notes']).expanduser()
    logf = (notes / 'run.log').as_posix() if not notes.is_absolute() else str(notes / 'run.log')
    # B71: the runner itself, not [run] command: a project's command may wrap only part of it (openmx's ./kit)
    watch = (CONTROL_FEED_WATCH if feed_on() else CONTROL_WATCH).format(repo=ROOT.name, cmd=RUNNER)
    cf = P.needs_cfg()  # B27: the heading's words
    answer = CONTROL_ANSWER.format(cmd=RUNNER)
    from agent_runner import glossary  # F22: the glossary paragraph (and the seed ask), or none when it is off
    from agent_runner.guide import grill_fit  # F20: the grilling line fitted to [run] grill
    from agent_runner import voice  # F21: the person's wording, read fresh by every session's brief
    return voice.fit(grill_fit(glossary.fit(CONTROL.format(repo=ROOT.name, cmd=RUNNER, log=logf, watch=watch,
                                                           needs=cf['heading'], answer=answer), 'control', RUNNER, C),
                               RUNNER, C), RUNNER, C)


def control_settings_data() -> dict:
    """`<notes>/control-settings.json`, given to every control session and the control server with --settings:
    a SessionStart hook (every source: startup, resume, clear, compact) that prints the control brief, so each
    one gets it the same way however it started; and the runner's commands, Read and Monitor allowed without a
    prompt. Control sessions run with bypassPermissions (`control_argv`, `control_server_argv`), so a person on a
    phone never waits on a permission question; the bypass dialog is skipped here for the same reason. No Stop
    hook: a control session is never ended on idle."""
    hook = plat.command_text([*runner_cmd(), 'control', '--brief'])
    return {'hooks': {'SessionStart': [{'hooks': [{'type': 'command', 'command': hook}]}]},
            'skipDangerousModePermissionPrompt': True,
            'permissions': {'additionalDirectories': [str(control_skills_dir())]}}


CONTROL_SKILL = 'control'  # the slash command: Claude Code's /new is /clear's alias, so not that


def control_skills_dir() -> Path:
    """`<notes>/control-skills`: a directory only control sessions add (`--add-dir`, and the settings'
    additionalDirectories), holding `.claude/skills/control/SKILL.md`, the /control slash command that opens
    another control session. Never in the person's repo files."""
    from agent_runner.guide import control_skills  # /control, and the opening hints line's /run /since …
    for name, text in control_skills(RUNNER, CONTROL_SKILL).items():
        f = C.notes('control-skills', '.claude', 'skills', name, 'SKILL.md')
        try:
            if not f.is_file() or f.read_text(encoding='utf-8') != text:
                f.write_text(text, encoding='utf-8')
        except OSError:
            pass
    return f.parents[3]


def control_settings() -> Path:
    """Write the control settings file when its text changed; its path."""
    f = C.notes('control-settings.json')
    text = json.dumps(control_settings_data(), indent=2) + '\n'
    try:
        if f.read_text(encoding='utf-8') == text:
            return f
    except OSError:
        pass
    tmp = f.with_name(f.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, f)
    return f


def control_title(ask: str = '', images: list[str] | tuple = ()) -> str:
    """A short title for a control session opened with `--ask`: the ask's first words (up to 5, trimmed at a word
    to about 40 characters, trailing punctuation dropped); for a files-only ask "screenshot" when they are all
    images, else the first file's name (B30); "" without one."""
    words = (ask or '').split()[:5]
    while len(' '.join(words)) > 40 and len(words) > 1:
        words.pop()
    title = ' '.join(words)
    if len(title) > 40:
        title = title[:39].rstrip() + '…'
    title = title.rstrip(' ,.;:-–—')
    if title or not images:
        return title
    if all(Path(i).suffix.lower() in IMAGE_EXTS for i in images):
        return 'screenshot'
    return attached_name(images[0])[:40]


def control_name(n: int, ask: str = '', images: list[str] | tuple = ()) -> str:
    """Control session `n`'s name in the Claude apps (B25): "<repo> · N · <title>" when opened with an ask
    (`control_title`; N kept so higher is newer and `attach cN` still matches), else "<repo> · control N"."""
    title = control_title(ask, images)
    return f'{ROOT.name} · {n} · {title}' if title else f'{ROOT.name} · control {n}'


CONTROL_N_ENV = 'AGENT_RUNNER_CONTROL'  # F29: a control session's number, in its tools' environment


SUMMARY_TASK_RE = re.compile(r'^([A-Z]\d+[a-z]?)[:,.;]?$')  # F32: a summary's leading task id (R43, P17a)


def control_summary_name(n: int, summary: str) -> str:
    """F29/F32: the name control session `n` takes once it has read its first message: "<repo> · <ID> ·
    <rest>" when the summary starts with a task id (one task: `iFizBox · R43 · site deploy via tags`), else
    "<repo> · N · <summary>"; the summary one line trimmed as an ask's title is (`control_title`); "" for an
    empty summary. `control_given` keeps it, so `control_renamed` does not take it for the person's."""
    words = ' '.join(str(summary or '').replace('"', ' ').replace('`', ' ').split()).split(' ')
    if (m := SUMMARY_TASK_RE.match(words[0])):
        rest = control_title(' '.join(words[1:]))
        return ' · '.join(x for x in (ROOT.name, m[1], rest) if x)
    title = control_title(' '.join(words))
    return f'{ROOT.name} · {n} · {title}' if title else ''


def control_base_name(n: int) -> str:
    """F32: control session `n`'s name with no ask of its own yet: "<repo> · N" (after /new or /clear)."""
    return f'{ROOT.name} · {n}'


def control_given(n: int) -> str:
    """F32: the name the runner last gave control session `n` (`<notes>/control<n>.title`), '' for none."""
    try:
        return C.notes(f'control{n}.title').read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def control_give(n: int, name: str) -> None:
    """F32: record `name` as the one the runner last gave control session `n` (see `control_renamed`)."""
    try:
        C.notes(f'control{n}.title').write_text(name + '\n', encoding='utf-8')
    except OSError:
        pass


def control_mark_ask(n: int, sid: str) -> None:
    """F56: record that control session `n`, as conversation `sid`, was opened for one ask (the runner gave it
    its first message: a feed reply, `control --new --ask`), in `<notes>/control<n>.ask`; '' clears it."""
    f = C.notes(f'control{n}.ask')
    try:
        if sid:
            f.write_text(sid + '\n', encoding='utf-8')
        else:
            f.unlink(missing_ok=True)
    except OSError:
        pass


def control_one_ask(n: int, sid: str) -> bool:
    """F56: whether control session `n`'s conversation `sid` is the one it was opened for one ask with (after
    /clear or /new it is another conversation, and is not)."""
    try:
        return bool(sid) and C.notes(f'control{n}.ask').read_text(encoding='utf-8').strip() == sid
    except OSError:
        return False


def control_session_start(n: int, hook: dict) -> str:
    """F32: the SessionStart hook of control session `n` (`control --brief`, its JSON input `hook`). On
    source 'clear' (/clear, and /new, its alias) the session starts afresh in a new transcript: the pid file
    follows it to the new session id, and a name the runner gave it for the old ask (a task's) goes back to
    "<repo> · N" until the new conversation has its own; a name the person typed stays. Returns the name it
    was reset to, or ''."""
    if not n or not isinstance(hook, dict) or hook.get('source') != 'clear':
        return ''
    pidf = C.notes(f'control{n}.pid')
    try:
        pid_s, _, old = pidf.read_text(encoding='utf-8').strip().partition(' ')
    except OSError:
        pid_s, old = '', ''
    new = str(hook.get('session_id') or '')
    if pid_s and new and new != old:
        try:
            pidf.write_text(f'{pid_s} {new}', encoding='utf-8')
        except OSError:
            pass
    if old and transcript(old) and control_renamed(control_state(entries(old, skip_bad=True)), n):
        return ''  # the person named it: never overwritten
    base, given = control_base_name(n), control_given(n)
    if not given or given in (base, control_name(n)):
        return ''
    if not (pane := control_pane(n)) or not send_to_pane(pane, f'/rename {base}'):
        return ''
    tmux('rename-window', '-t', pane, base)
    control_give(n, base)
    return base


def control_hook_input() -> dict:
    """The JSON a Claude Code hook gets on stdin, {} when there is none to read at once (a person running
    `control --brief` by hand, or a stdin left open)."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        if not plat.WINDOWS:
            import select
            if not select.select([sys.stdin], [], [], 1.0)[0]:
                return {}
        d = json.loads(sys.stdin.read() or '{}')
    except (OSError, ValueError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


def control_pane(n: int) -> str:
    """The tmux pane control session `n` runs in: $TMUX_PANE when the caller is that session's own tool (its
    shells inherit the pane), else the pane tagged c<n> for this repository; '' for none."""
    if pane := os.environ.get('TMUX_PANE', ''):
        return pane
    if not shutil.which('tmux'):
        return ''
    rows = tmux('list-panes', '-a', '-F', f'#{{session_name}}\t#{{pane_id}}\t#{{{TAG}}}\t#{{{REPO_TAG}}}\t#{{{RUN_TAG}}}')
    hit = attach_target(rows.stdout.splitlines(), ROOT, f'c{n}') if not rows.returncode else None
    return hit[1] if hit else ''


def control_set_title(n: int, summary: str) -> int:
    """F29 `control --title SUMMARY`: control session `n` (its own $AGENT_RUNNER_CONTROL) names itself for what
    it is for, once it has read its first message: types `/rename <repo> · N · SUMMARY` into its pane (queued
    until its turn ends) and renames its tmux window. Not over a name the person gave it (B41)."""
    if not n:
        print(f'no control session number: run it from a control session, or give N ({RUNNER} control N --title …)',
              file=sys.stderr)
        return 2
    if not (name := control_summary_name(n, summary)):
        print('--title needs a few words saying what the session is for', file=sys.stderr)
        return 2
    try:
        sid = C.notes(f'control{n}.pid').read_text(encoding='utf-8').strip().partition(' ')[2]
    except OSError:
        sid = ''
    if sid and transcript(sid) and control_renamed(control_state(entries(sid, skip_bad=True)), n):
        print(f'control {n} keeps the name the person gave it')
        return 0
    if not (pane := control_pane(n)) or not send_to_pane(pane, f'/rename {name}'):
        print(f'control {n} has no tmux pane to rename it in; it stays as it is', file=sys.stderr)
        return 1
    tmux('rename-window', '-t', pane, name)
    control_give(n, name)
    print(f'control {n} is renamed "{name}" when this turn ends')
    return 0


def control_ask(ask: str, images: list[str] | tuple = ()) -> str:
    """The first message a handed-on request opens a control session with: `ask`, and for each `--file PATH`
    (`--image`: an alias) a line saying the person attached that file, by name and saved path, and to Read or open
    it before answering (the runner feed forwards text only, so a screenshot or an upload reaches the new session
    by its saved path, B30)."""
    lines = [ask] if ask else []
    lines += [f'The person attached {attached_name(p)}, saved at "{p}": Read or open it before you answer.'
              for p in images]
    if ask and (waiting := waiting_for_ask(ask, ask_waiting())):
        lines.append(ask_waiting_block(waiting))
    return '\n\n'.join(lines)


# B54: a handed-on ask carries only the waiting items it plausibly answers: one it names by id, one it shares two
# words with, or all of them for a bare reply ("yes", "B", "later") whose item it does not name.
ASK_STOP = frozenset('''about after again also been before being both does done each from have here into just
like make more much need needs only other over please should some still such than that their them then there
these they this those very want what when where which while will with would could your runner task item'''.split())
ASK_REPLY = frozenset('yes no ok okay go later done sure fine approve approved confirm confirmed shelve skip'.split())


def ask_words(text: str) -> set[str]:
    """The words of `text` that can tie an ask to an item: 4+ letters, not ASK_STOP, a plural's s dropped."""
    out = set()
    for w in re.findall(r'[a-z0-9]+', text.lower()):
        w = w[:-1] if len(w) > 4 and w.endswith('s') and not w.endswith('ss') else w
        if len(w) >= 4 and w not in ASK_STOP:
            out.add(w)
    return out


def waiting_for_ask(ask: str, waiting: str) -> str:
    """B54: the lines of `waiting` ('- ID: ask' each) that the handed-on `ask` plausibly answers; '' for none, so a
    hand-off about something else carries no item and no order to settle one."""
    words = re.findall(r'[a-z0-9]+', ask.lower())
    if words and len(words) <= 3 and all(w in ASK_REPLY or len(w) == 1 for w in words):
        return waiting  # a bare reply: it can only be to an item
    mine = ask_words(ask)
    keep = []
    for line in waiting.splitlines():
        m = re.match(r'-\s*(\S+?):\s*(.*)', line)
        if not m:
            continue
        named = re.search(rf'(?<![A-Za-z0-9]){re.escape(m[1])}(?![A-Za-z0-9])', ask, re.I)
        if named or len(mine & ask_words(m[2])) >= 2:
            keep.append(line)
    return '\n'.join(keep)


def ask_waiting_block(waiting: str) -> str:
    """B84: the Needs you items a handed-on ask carries (B47), fenced off as runner-added and placed after the
    person's words, so the session answers the person and not the list; the control brief names the tag."""
    return ('<runner-waiting>\nAdded by the runner, not the person\'s ask. Waiting under Needs you:\n' + waiting +
            f'\nSettle one by its id (`{RUNNER} plan confirm|change|shelve ID`, not only a new task) only if the '
            'words above answer it; else say nothing of these.\n</runner-waiting>')


def ask_waiting() -> str:
    """The items under Needs you, one '- ID: ask' line each, for a handed-on request (B47); '' when none or the
    plan cannot be read (opening the session matters more)."""
    try:
        return '\n'.join(f'- {a[1]}: {P.plain_ask(a[0], a[3], a[5], a[0] == "DECIDE" and has_sheet(a[1]))}'
                         + (f' {a[4]}' if a[4] and a[0] == 'DECIDE' and has_sheet(a[1]) else '') for a in P.asks())
    except (OSError, SystemExit, ValueError):
        return ''


UPLOAD_ID_RE = re.compile(r'^[0-9a-f]{8}-(.+)$')
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.heic', '.bmp')


def attached_name(path: str) -> str:
    """The name the person gave a file they attached: Claude Code saves an upload as
    ~/.claude/uploads/<sid>/<8-hex id>-<name> (B30), so the id prefix is dropped there; else the base name."""
    p = Path(path)
    m = UPLOAD_ID_RE.match(p.name)
    return m.group(1) if m and 'uploads' in p.parts else p.name


def control_argv(n: int, sid: str, resume: bool, blank: bool = False, ask: str = '', local: bool = False,
                 images: list[str] | tuple = ()) -> list[str]:
    """Control session `n`: interactive, on `[run] model` (no model of its own), the brief from its settings
    file; with `[run] remote` on Remote Control as "<repo> · control N". Control 1 (the kept session the run
    starts) gets a first message asking for the status summary (`status` only: `since` would move the last-look
    mark past updates the person has not seen); any other (`control --new`, /control) gets none and stays blank
    until the person types, its brief still loaded by the SessionStart hook. bypassPermissions, as the slots: it
    is driven from a phone or the web as often as from here, and a permission prompt there stalls it. Not lean: a
    person is there (all tools, so /statusline and the like work). `blank` (`control 1 --blank`: the c1 a run
    with `[run] remote` opens): no first message either, so it costs nothing until the person types. `local`
    (`control 1 --local`, the same c1): not on Remote Control even with `[run] remote` on, so it is in the
    terminal only and its start pushes nothing; the control server is the apps' one entry. `ask`
    (`control --new --ask TEXT`, from the runner feed): TEXT is its first message instead; `images` (`--file
    PATH`, alias `--image`, repeatable) adds a line per attached file to it (`control_ask`)."""
    from agent_runner.guide import CONTROL_START, CONTROL_START_WATCH
    opening = CONTROL_START.format(cmd=RUNNER, watch_start='' if feed_on() else  # B71: the runner, not [run] command
                                   CONTROL_START_WATCH.format(cmd=RUNNER))
    if n == 1 and not resume and CONTROL_FRESH[0]:  # F27: a bloated c1 started over; the summary says so first
        opening = f'Say first, in one line: "{CONTROL_FRESH[0]}." Then: {opening}'
    ask_text, ask = ask, control_ask(ask, images)
    first = [ask] if ask else [opening] if n == 1 and not blank else []
    return [plat.exe(C.run['agent']), *first,
            '--resume' if resume else '--session-id', sid, '--model', C.run['model'],
            '--permission-mode', 'bypassPermissions',
            '--settings', str(control_settings()), '--add-dir', str(control_skills_dir()),
            *(['--remote-control', control_name(n, ask_text, images)] if remote_on() and not local else [])]


def control_live(n: int) -> int:
    """The pid control session `n` runs as (`<notes>/control<n>.pid`: "pid sid"), or 0. The sid in its command
    line tells it from a process that got the pid since (where the command line can be read). B59: after /clear
    or /new the pid file holds the new sid (`control_session_start`) while the argv keeps the --session-id it
    started with, so a process whose argv names a control file (its control-settings.json) also counts: tested
    as a substring of each arg, since `plat.cmdline` gives a list."""
    try:
        pid_s, _, sid = C.notes(f'control{n}.pid').read_text(encoding='utf-8').strip().partition(' ')
        pid = int(pid_s)
    except (OSError, ValueError):
        return 0
    if not plat.alive(pid) or pid == os.getpid():
        return 0
    args = plat.cmdline(pid)
    return pid if args is None or not sid or sid in args or any('control' in a for a in args) else 0


def control_number() -> int:
    """The first control number with no live session: 1 (the kept session) when it is free."""
    n = 1
    while control_live(n):
        n += 1
    return n


RESTART_GAP = 300  # s: a run started this soon after the last one ended is a restart (F27: c1 resumes)
CONTROL_FRESH = ['']  # F27: why this c1 started a fresh session, for its opening line ('' when it did not)


RECOVER_GAP = 6 * 3600  # s: a run that never logged its stop, and was last alive this recently, is recovered


def run_restart(now: float | None = None) -> bool:
    """F27: whether the run starting now is a restart of the last one rather than a new run a person started:
    it stopped under RESTART_GAP ago, or it never logged its stop (the self-restart on upgrade or
    auto_upgrade, a crash, a kill, Ctrl-C) and was last alive under RECOVER_GAP ago. Its end is its last event
    or its last STATE, whichever is later. Called before this run logs its own 'run up'; no earlier run at all
    is a new run."""
    from agent_runner.state import EV_RUN_UP, EV_STOPPED
    now = time.time() if now is None else now
    last, latest = None, ''
    try:
        with open(C.notes('events.jsonl'), encoding='utf-8') as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get('kind') in (EV_RUN_UP, EV_STOPPED):
                    last = d
                if isinstance(d, dict) and d.get('time'):
                    latest = str(d['time'])
    except OSError:
        pass
    if not last:
        return False
    gap = RECOVER_GAP if last['kind'] == EV_RUN_UP else RESTART_GAP
    ends = [latest]
    try:
        ends.append(str(json.loads(C.notes('STATE').read_text(encoding='utf-8')).get('at', '')))
    except (OSError, ValueError, AttributeError):
        pass
    stamps = []
    for s in ends:
        try:
            stamps.append(dt.datetime.fromisoformat(s).timestamp())
        except ValueError:
            pass
    return bool(stamps) and now - max(stamps) < gap


def control_bloated(sid: str) -> int:
    """F27: session `sid`'s last context in k tokens when it is over [run] context_warn (0 is off), else 0."""
    from agent_runner.watch import usage
    try:
        warn = int(C.run.get('context_warn') or 0)
    except (TypeError, ValueError):
        return 0
    ctx = usage(sid)[1]
    last = ctx[-1] // 1000 if ctx else 0
    return last if warn > 0 and last > warn else 0


def control_sid(n: int, new_run: bool = False) -> tuple[str, bool]:
    """(session id, resume?): c1 keeps its id in `<notes>/control.sid` and resumes it across runs while its
    transcript is there; any other control session starts fresh. F27: `new_run` (`control 1 --new-run`, from a
    run a person started, not a restart: `run_restart`) starts c1 fresh, with a new id in control.sid, when
    the kept transcript's last context is over [run] context_warn; the plan, ledger and since hold the state,
    so the opening summary covers it. CONTROL_FRESH then says why, in one line."""
    f = C.notes('control.sid')
    CONTROL_FRESH[0] = ''
    if n == 1:
        try:
            sid = f.read_text(encoding='utf-8').strip()
        except OSError:
            sid = ''
        if sid and backend().find_transcript(sid):
            if not (new_run and (k := control_bloated(sid))):
                return sid, True
            CONTROL_FRESH[0] = (f'c1 starts a fresh session: the last one reached {k}k context (over [run] '
                                f'context_warn {C.run["context_warn"]}k); the plan, ledger and since carry on')
            log(f'control: {CONTROL_FRESH[0]}')
    sid = str(uuid.uuid4())
    if n == 1:
        f.write_text(sid + '\n', encoding='utf-8')
    return sid, False


def control_env() -> dict:
    """The environment a control session gets: ours, without a slot's marks (`plan add` treats AGENT_RUNNER=1 as
    one of the runner's agents), with RUNNER_STARTED_ENV: its brief comes through --settings, so the hand hook
    (`hand_hook`) stays quiet."""
    env = {k: v for k, v in os.environ.items() if k not in ('AGENT_RUNNER', 'AGENT_RUNNER_SLOT', 'AGENT_RUNNER_KEEP')}
    return {**env, RUNNER_STARTED_ENV: '1'}


RUNNER_STARTED_ENV = 'AGENT_RUNNER_CONTROL_SESSION'


def hand_hook(root: Path) -> str:
    """F53: a session a person opens by hand in the main checkout (the desktop app, a terminal, an IDE) gets the
    control brief too: a SessionStart hook in `.claude/settings.local.json`, which is per machine and never
    committed, so slot worktrees never have it. Merged into the file, added once. A line for the run log, or ''."""
    f = root / '.claude' / 'settings.local.json'
    cmd = plat.command_text([*runner_cmd(), 'control', '--brief', '--hand'])
    try:
        data = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
    except (OSError, ValueError):
        return ''  # a file we cannot read is the person's: leave it
    starts = data.setdefault('hooks', {}).setdefault('SessionStart', [])
    if any('control --brief --hand' in h.get('command', '') for e in starts for h in e.get('hooks', [])):
        hand_hook_exclude(root)  # B66: a machine that got the hook before the exclude gets it now
        return ''
    starts.append({'hooks': [{'type': 'command', 'command': cmd}]})
    try:
        f.parent.mkdir(exist_ok=True)
        f.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    except OSError:
        return ''
    hand_hook_exclude(root)
    return f'{f.relative_to(root).as_posix()}: sessions opened by hand here get the control brief'


def user_brief(root: Path) -> str:
    """B79: the control brief for a session opened by hand in `root`, a runner repo's main checkout, by the
    user-level SessionStart hook (`config.install_user_hook`): a repo where no run has started yet has no hook
    of its own (`hand_hook`). '' where control sessions are not Claude Code's (`[run] agent` is pi)."""
    import contextlib
    with contextlib.redirect_stderr(io.StringIO()):  # init's git calls and merge driver: nothing on the screen
        init(root)
        return control_brief() if control_ok() else ''


def hand_hook_exclude(root: Path) -> None:
    """B66: `.claude/settings.local.json` ignored in `root`'s repo. Where git has no rule for it (no global
    ignore, as on a fresh Windows machine) it shows as untracked, and a `git add -A` would commit this machine's
    hook, handing every slot worktree the control brief. Added to `info/exclude` in the common git dir, which
    every worktree shares, only when `git check-ignore` says it is not ignored yet."""
    rel = '.claude/settings.local.json'
    if git('check-ignore', '-q', rel, cwd=root).returncode != 1:
        return  # ignored already (0), or not a git repo / git failed (128): nothing to do
    r = git('rev-parse', '--git-common-dir', cwd=root)
    if r.returncode != 0 or not r.stdout.strip():
        return
    common = Path(r.stdout.strip())
    ex = (common if common.is_absolute() else root / common) / 'info' / 'exclude'
    try:
        old = ex.read_text(encoding='utf-8') if ex.exists() else ''
        ex.parent.mkdir(parents=True, exist_ok=True)
        sep = '' if not old or old.endswith('\n') else '\n'
        ex.write_text(f'{old}{sep}/{rel}\n', encoding='utf-8')
    except OSError:
        pass


QUIET_WAIT = 30  # s a starting session stays quiet where its pane cannot be read (no tmux)


def unquiet_when_up(who: str, pane: str = '', log_file: Path | None = None, wait: float | None = None,
                    since: int = 0) -> None:
    """Remove `quiet_file(who)` once its session is up: its claude.ai/code link shows in tmux pane `pane`, or in
    `log_file` past byte `since` (the control server's); or `wait` s (CONTROL_LINK_WAIT) have passed; with
    neither to read, after QUIET_WAIT s."""
    wait = CONTROL_LINK_WAIT if wait is None else wait
    deadline = time.monotonic() + (wait if pane or log_file else QUIET_WAIT)
    linked = None  # B45: did the pane, still open, show its link?
    while time.monotonic() < deadline:
        if pane:
            shown = tmux('capture-pane', '-p', '-J', '-t', pane, '-S', '-200')
            if shown.returncode:
                linked = None
                break
            linked = bool(SESSION_LINK.search(shown.stdout or ''))
            if linked:
                break
        elif log_file:
            try:
                with open(log_file, 'rb') as fh:
                    fh.seek(since)
                    if REMOTE_URL.encode() in fh.read():
                        break
            except OSError:
                pass
        time.sleep(1)
    quiet_file(who, on=False)
    if pane and linked is not None and remote_on():  # B45 spots 2 and 3, for c1 and the other sessions
        if linked:
            remote_answer_drift(who)
        else:
            link_drift(who, wait)


def control_default_command(root: Path) -> str:
    """tmux's default-command for the run's background session: every pane or window a person opens there
    becomes a control session in the main checkout; a shell stays if one cannot start."""
    return (f'cd {shlex.quote(str(root))} && {plat.command_text([*runner_cmd(), "control"])} '
            f'|| exec "${{SHELL:-/bin/sh}}"')


def control_pane_argv(target: str, background: bool, sess: str, root: Path, cmd: str, env: list[str]) -> list[str]:
    """The tmux command opening c1: a pane split under the runner's pane `target` (a run in a terminal), or a
    window of its own, "control-<repo>", in the background session `sess`."""
    envs = [a for e in env for a in ('-e', e)]
    where = (['new-window', '-d', '-t', f'={sess}:', '-n', window('control')] if background else
             ['split-window', '-v', '-d', '-l', '40%', '-t', target])
    return ['tmux', *where, '-c', str(root), *envs, '-P', '-F', '#{pane_id}', cmd]


def start_control() -> None:
    """The run opens control session c1 beside it, unless `[run] control = false` or c1 already runs (it outlives
    a stopped run). With `[run] remote` it opens blank (no opening summary, so no tokens until the person types)
    and local (`--local`: no Remote Control, so no second app entry beside the control server's "<repo> ·
    control" and no start push; no quiet-c1 presence file either). tmux: under the runner's pane, or in the background session's own window, whose
    default-command makes every new pane a control session. Windows: a console of its own (hidden in the
    background run). Linux and macOS with no tmux pane to open it in (a hidden run): a pseudo-terminal with no
    window (`hidden_control`, F59)."""
    mark_board()
    if not C.run['control'] or not control_ok():
        return
    cmd = [*runner_cmd(), 'control', '1', *([] if run_restart() else ['--new-run']),  # F27: a restart resumes c1
           *(['--blank', '--local'] if remote_on() else [])]  # remote: free till you type, terminal only
    here = os.environ.get('TMUX_PANE', '')
    if isinstance(MUX, TmuxMux) and here:
        sess = tmux('display-message', '-p', '-t', here, '#{session_name}').stdout.strip()
        background = sess == background_session()
        env = [e for e in background_env() if not e.startswith(('AGENT_RUNNER=', 'AGENT_RUNNER_SLOT=', 'AGENT_RUNNER_KEEP='))]
        if background:
            tmux('set-option', '-t', f'={sess}', 'default-command', control_default_command(ROOT))
            for e in env:
                tmux('set-environment', '-t', f'={sess}', *e.split('=', 1))
    if pid := control_live(1):
        log(f'control: c1 already runs (pid {pid})')
        return
    if isinstance(MUX, TmuxMux) and here:
        r = sp.run(control_pane_argv(here, background, sess, ROOT, plat.command_text(cmd), env),
                   capture_output=True, text=True)
        if r.returncode or not (pane_id := r.stdout.strip()):
            log(f'control: tmux could not open c1: {r.stderr.strip()}')
            return
        tmux('set-option', '-p', '-t', pane_id, TAG, 'c1')
        tmux('set-option', '-p', '-t', pane_id, REPO_TAG, str(ROOT))
        where = f'window {window("control")}' if background else 'the pane under this one'
        more = '; a new pane in this tmux session is another' if background else ''
    elif plat.WINDOWS:
        plat.spawn_console(cmd, ROOT, control_env(), hidden=HIDDEN[0])
        where, more = 'a console of its own' + (' (hidden)' if HIDDEN[0] else ''), ''
    elif type(MUX).__name__ == 'HiddenMux':  # F59: a hidden run (no tmux, or outside a tmux session): no window
        pid, why = hidden_control(1, cmd)
        if not pid:
            log(f'control: c1 could not start hidden: {why}')
            return
        where, more = f'a hidden terminal (its output in {hidden_control_log(1)})', ''
    else:
        return
    log(f'control: c1 is up in {where} ({shown_cmd()} control opens another{more})')


NO_BOARD = 'no-board'  # F59: <notes>/no-board while the run that is up has no board window (a hidden run)


def mark_board() -> None:
    """F59: say whether this run has a board window, for `feed_on` in the control sessions' own processes: the
    board opens only in a tmux run inside a tmux session (`start_board`). Called once as the run starts."""
    f = C.notes(NO_BOARD)
    if isinstance(MUX, TmuxMux) and os.environ.get('TMUX_PANE'):
        f.unlink(missing_ok=True)
    else:
        f.write_text('this run has no board window, so no runner feed\n', encoding='utf-8')


def hidden_control_log(n: int) -> Path:
    """F59: where a hidden control session's output goes: `<notes>/control<n>.log`."""
    return C.notes(f'control{n}.log')


def hidden_control(n: int, cmd: list[str], wait: float | None = None) -> tuple[int, str]:
    """F59: start control session `n` (`cmd`, a `control N` command line) with no window on Linux and macOS,
    through the F40 pty shim (`run --slot-shim`, `run_pty`) with a job of its own, `<notes>/control<n>.job`:
    its output goes to `hidden_control_log`, its pid to `<notes>/control<n>.live` while it runs, and text
    written to the FIFO beside it (`control<n>.in`) is typed into it. Started detached, so it outlives the run
    the way c1 in a pane does. (pid, '') once it is up, else (0, why)."""
    from agent_runner.slots import SHIM_WAIT
    job, marker = C.notes(f'control{n}.job'), C.notes(f'control{n}.live')
    ended = marker.with_suffix('.exit')
    marker.unlink(missing_ok=True)
    ended.unlink(missing_ok=True)
    job.write_text(json.dumps({'argv': cmd, 'cwd': str(ROOT), 'env': {}, 'marker': str(marker),
                               'log': str(hidden_control_log(n))}), encoding='utf-8')
    shim = [*runner_cmd(), 'run', '--slot-shim', str(job)]
    try:
        with open(C.notes(f'control{n}.shim'), 'ab') as out:  # the shim's own errors, should it fail
            sp.Popen(shim, cwd=str(ROOT), env=control_env(), stdin=sp.DEVNULL, stdout=out, stderr=out,
                     start_new_session=True)
    except OSError as e:
        return 0, f'could not start the shim: {e}'
    end = time.monotonic() + (SHIM_WAIT if wait is None else wait)
    while time.monotonic() < end:
        if pid := marker_pid(marker):
            return pid, ''
        if ended.exists():
            return 0, ended.read_text(encoding='utf-8').strip()[:300] or 'it ended at once'
        time.sleep(0.2)
    return 0, f'it did not start in {SHIM_WAIT if wait is None else wait:g} s (see {C.notes(f"control{n}.shim")})'


def feed_on() -> bool:
    """Does a run here keep the runner feed (the board window, on Remote Control), the one watch that pushes what
    needs the person? Control sessions then start no needs-you watch of their own. Not while the run that is up
    has no board window (F59: a hidden run, with tmux installed or not)."""
    return (remote_on() and control_ok() and not plat.WINDOWS and shutil.which('tmux') is not None
            and not C.notes(NO_BOARD).exists())


CONTROL_LINK_WAIT = 90  # s `control --new` watches the new pane for its claude.ai/code link
SESSION_LINK = re.compile(r'https://claude\.ai/code/session_[A-Za-z0-9_-]+')


def message_text(d: dict) -> str:
    """A transcript entry's text, as the person typed it: a string content as is, else its text blocks joined
    by newlines."""
    c = (d.get('message') or {}).get('content')
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return '\n'.join(x.get('text', '') for x in c if isinstance(x, dict) and x.get('type') == 'text'
                         and isinstance(x.get('text'), str))
    return ''


def person_message(d: dict) -> bool:
    """A transcript entry the person typed (not a tool result or a task notification)."""
    if (d.get('origin') or {}).get('kind', 'human') != 'human':
        return False
    c = (d.get('message') or {}).get('content')
    if isinstance(c, str):
        return not c.startswith('<task-notification>')
    return isinstance(c, list) and any(isinstance(x, dict) and x.get('type') in ('text', 'image') for x in c)


RUNNER_TURN = ('<command-name>', '<command-message>', '<command-args>', '<local-command-', '<system-reminder>',
               '<task-notification>', '<user-prompt-submit-hook>', 'Caveat: ')


def person_turn(d: dict) -> bool:
    """F56: a message the person sent, as counted for a control session's close tiers: `person_message`, but
    not a meta or compact-summary entry, and not a turn that is only a slash command (the runner's `/rename`),
    its output, a hook's or system text (RUNNER_TURN): an image, or any text item that is none of those."""
    if not person_message(d) or d.get('isMeta') or d.get('isCompactSummary'):
        return False
    c = (d.get('message') or {}).get('content')
    items = [c] if isinstance(c, str) else [x.get('text') if x.get('type') == 'text' else x.get('type')
                                            for x in c if isinstance(x, dict) and x.get('type') in ('text', 'image')]
    return any(i == 'image' or (isinstance(i, str) and i.strip() and not i.lstrip().startswith(RUNNER_TURN))
               for i in items)


# --- B26: idle control sessions are closed, so the apps' session list stops piling up ----------------------
#
# Every CONTROL_CLOSE_EVERY s the run reads the transcript of each live control session N (not c1, the kept
# one) and closes it (ends its process, removes controlN.pid; the transcript stays, resumable) when Claude
# spoke last, nothing runs in it, and it has been quiet `[run] control_idle`; or, when its last message is an
# open question or offer (`[run] control_open`), quiet `[run] control_ask_idle`: then the question is filed
# under Needs you as a DECIDE item first (`[run] control_file_asks`). `[run] control_close = false` turns it off.

CONTROL_CLOSE_EVERY = 300  # s between looks
CONTROL_CLOSE_AT = [0.0]
CONTROL_WATCH_CMD = 'since --follow --needs-you'  # a control session's standing watch: not work in progress
TASK_STARTED = re.compile(r'Monitor started \(task (\w+)|running in background with ID: (\w+)')
TASK_ENDED = re.compile(r'<task-id>(\w+)</task-id>|\(task (\w+)\)')
EXPIRES = re.compile(r'expires in (\d+)\s*([smh])')
PLAN_ADD_CMD = re.compile(r'\bplan\s+add\s')  # F56: a control session queueing a task
PLAN_ADDED = re.compile(r'(?m)^added [A-Z]+\d+\w*\b')  # what `plan add` prints when it filed one
DURATION = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$')


def duration(v, default: float = 0.0) -> float:
    """A config time in seconds: a number (seconds) or '90s', '30m', '1h', '2d'; false/0: 0 (off)."""
    if v is True or v is None:
        return default
    if v is False:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    m = DURATION.match(str(v).lower())
    if not m:
        return default
    return float(m[1]) * {'': 1, 's': 1, 'm': 60, 'h': 3600, 'd': 86400}[m[2]]


def _stamp(d: dict) -> float | None:
    try:
        return dt.datetime.fromisoformat(str(d['timestamp']).replace('Z', '+00:00')).timestamp()
    except (KeyError, ValueError, TypeError):
        return None


def _texts(d: dict) -> list[str]:
    """Every piece of text in a transcript entry: its message's text items and tool results, a queued
    notification's content."""
    out = [d['content']] if isinstance(d.get('content'), str) else []
    c = (d.get('message') or {}).get('content')
    if isinstance(c, str):
        return out + [c]
    for x in c if isinstance(c, list) else ():
        if not isinstance(x, dict):
            continue
        if isinstance(x.get('text'), str):
            out.append(x['text'])
        r = x.get('content')
        if isinstance(r, str):
            out.append(r)
        elif isinstance(r, list):
            out += [y['text'] for y in r if isinstance(y, dict) and isinstance(y.get('text'), str)]
    return out


def control_state(rows) -> dict:
    """What a control session's transcript entries `rows` say: {'last': 'person' | 'claude' | 'tool' | '',
    'text': Claude's last message when it spoke last, 'at': when it was last active (epoch s, 0 unknown),
    'running': ids of background tasks and Monitors still live, 'bridge': its Remote Control session id or '',
    'title': the latest name the person gave it in the apps (a custom-title entry, B41) or '',
    'said': how many messages the person sent (`person_turn`, F56), 'queued': whether it added a task (a
    `plan add` that printed "added <ID>", F56)}.
    Activity is a person's message or a turn of Claude's; the standing needs-you watch (CONTROL_WATCH_CMD)
    being re-armed is neither activity nor work in progress, and the events it brings are not activity."""
    st = {'last': '', 'text': '', 'at': 0.0, 'running': set(), 'bridge': '', 'title': '', 'said': 0,
          'queued': False}
    uses: dict[str, dict] = {}  # tool_use id -> its tool call
    expiry: dict[str, float] = {}  # task id -> when a Monitor with a timeout ends on its own
    for d in rows:
        if not isinstance(d, dict):
            continue
        kind, at = d.get('type'), _stamp(d)
        if kind == 'bridge-session' and isinstance(d.get('bridgeSessionId'), str):
            st['bridge'] = d['bridgeSessionId']
            continue
        if kind == 'custom-title':
            st['title'] = str(d.get('customTitle') or '').strip()
            continue
        texts = _texts(d)
        if any('<status>' in t for t in texts) or any('<task-notification>' in t and 'expired' in t.lower()
                                                      for t in texts):
            for t in texts:
                for m in TASK_ENDED.finditer(t):
                    st['running'].discard(m[1] or m[2])
        if kind == 'assistant':
            items = [x for x in (d.get('message') or {}).get('content') or [] if isinstance(x, dict)]
            said = '\n'.join(x['text'] for x in items if x.get('type') == 'text' and isinstance(x.get('text'), str)
                             and x['text'].strip())
            calls = [x for x in items if x.get('type') == 'tool_use']
            work = False
            for x in calls:
                uses[str(x.get('id'))] = x
                inp = x.get('input') or {}
                if x.get('name') in ('TaskStop', 'KillShell', 'KillBash'):
                    st['running'].discard(str(inp.get('task_id') or inp.get('shell_id') or ''))
                if not (x.get('name') == 'Monitor' and CONTROL_WATCH_CMD in str(inp.get('command', ''))):
                    work = True
            if said:
                st['last'], st['text'] = 'claude', said
            elif work:
                st['last'], st['text'] = 'tool', ''
            if (said or work) and at:
                st['at'] = max(st['at'], at)
        elif kind == 'user':
            c = (d.get('message') or {}).get('content')
            for x in c if isinstance(c, list) else ():
                if not (isinstance(x, dict) and x.get('type') == 'tool_result'):
                    continue
                call = uses.get(str(x.get('tool_use_id')), {})
                if call.get('name') == 'Monitor' and CONTROL_WATCH_CMD in str((call.get('input') or {}).get('command', '')):
                    continue
                for t in _texts({'message': {'content': [x]}}):
                    if (call.get('name') == 'Bash' and PLAN_ADD_CMD.search(str((call.get('input') or {}).get('command', '')))
                            and PLAN_ADDED.search(t)):
                        st['queued'] = True
                    if m := TASK_STARTED.search(t):
                        tid = m[1] or m[2]
                        persistent = (call.get('input') or {}).get('persistent')
                        if (e := EXPIRES.search(t)) and at and not persistent:
                            expiry[tid] = at + int(e[1]) * {'s': 1, 'm': 60, 'h': 3600}[e[2]]
                        st['running'].add(tid)
            if person_turn(d):  # F56: not a slash command (the runner's /rename) or a hook's or system turn
                st['last'], st['text'] = 'person', ''
                st['said'] += 1
                if at:
                    st['at'] = max(st['at'], at)
    now = time.time()
    st['running'] = {t for t in st['running'] if not (t in expiry and expiry[t] <= now)}
    return st


def control_cfg() -> dict:
    """`[run] control_close`, `control_idle`, `control_idle_quick` (quick), `control_idle_talked` (talked),
    `control_ask_idle` (seconds; 0 off), `control_open` (lowercase), `control_file_asks`, `control_ask_kind`."""
    r = C.run
    opens = r.get('control_open', ['?', 'want me to', 'should i'])
    return {'close': r.get('control_close', True) is not False,
            'idle': duration(r.get('control_idle', '3h'), 10800.0),
            'quick': duration(r.get('control_idle_quick', '5m'), 300.0),
            'talked': duration(r.get('control_idle_talked', '12h'), 43200.0),
            'ask_idle': duration(r.get('control_ask_idle', '2h'), 7200.0),
            'open': [str(p).lower() for p in ([opens] if isinstance(opens, str) else opens or [])],
            'file_asks': r.get('control_file_asks', True) is not False,
            'kind': str(r.get('control_ask_kind', 'F') or 'F')}


def open_question(text: str, phrases: list[str]) -> str:
    """The open question or offer Claude's last message `text` ends on, as one line ('' for none): its last
    paragraph, when that ends in a phrase that is only punctuation ('?') or holds any other (`want me to`),
    narrowed to the last sentence that does."""
    paras = [p for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
    if not paras:
        return ''
    last = ' '.join(paras[-1].split())
    bare = last.rstrip(' *_`"\')]')

    def hit(s: str) -> bool:
        s2, low = s.rstrip(' *_`"\')]'), s.lower()
        return any(s2.endswith(p) if not re.search(r'\w', p) else p in low for p in phrases if p)
    if not hit(bare) and not hit(last):
        return ''
    sentences = [s for s in re.split(r'(?<=[.!?])\s+', last) if s.strip()]
    q = next((s for s in reversed(sentences) if hit(s)), last).strip(' *_')
    return q if len(q) <= 240 else q[:239].rsplit(' ', 1)[0] + '…'


def control_renamed(st: dict, n: int = 0) -> bool:
    """B41: whether the person renamed control session `n` (state `st`): its custom title is set and is not a
    name the runner gives it: `control_name(n)`, "<repo> · N", or the name it last gave session N (F32:
    `control_given`, its ask's or `control --title`'s), not any "<repo> · N ·" name; with `n` 0 any custom
    title counts."""
    t = st.get('title') or ''
    return bool(t) and not (n and t in (control_name(n), control_base_name(n), control_given(n)))


def control_verdict(st: dict, cf: dict, now: float, n: int = 0, one_ask: bool = False) -> tuple[str, str]:
    """('close' | 'ask' | 'keep', why or the question) for control session `n`'s state `st` (`control_state`).
    One the person renamed is kept (B41): they named it to keep it. F56, which idle time applies: a session the
    person sent more than one message in, `control_idle_talked`; one opened for one ask (`one_ask`: the runner gave it its first message) that the person
    sent nothing more to and that queued a task, with no open question, `control_idle_quick`; else (or with that
    tier off) `control_idle`."""
    if control_renamed(st, n):
        return 'keep', 'renamed by the person'
    if st['last'] != 'claude':
        return 'keep', {'person': 'the person spoke last', 'tool': 'a turn is under way'}.get(st['last'], 'no turn yet')
    if st['running']:
        return 'keep', f'{len(st["running"])} background task(s) still running'
    quiet = now - st['at'] if st['at'] else 0
    talked = st.get('said', 0) > 1 and cf.get('talked')
    if q := open_question(st['text'], cf['open']):
        if cf['ask_idle'] and quiet >= cf['ask_idle']:
            return 'ask', q
        return 'keep', 'its open question is not old enough'
    if talked:
        idle, tier = cf['talked'], ' (talked)'
    elif one_ask and st.get('said', 0) == 1 and st.get('queued') and cf.get('quick'):
        idle, tier = cf['quick'], ' (one ask, queued)'
    else:
        idle, tier = cf['idle'], ''
    if idle and quiet >= idle:
        return 'close', f'idle {int(quiet // 60)} min{tier}'
    return 'keep', 'active lately'


def control_link(bridge: str) -> str:
    """A Remote Control session id (cse_…) as its claude.ai/code link; '' for none."""
    return f'{REMOTE_URL}/session_{bridge[4:]}' if bridge.startswith('cse_') else ''


def control_live_numbers() -> list[int]:
    """The numbers of the control sessions with a pid file and a live process, c1 left out."""
    out = []
    for f in C.notes().glob('control*.pid'):
        if (m := re.fullmatch(r'control(\d+)\.pid', f.name)) and int(m[1]) > 1 and control_live(int(m[1])):
            out.append(int(m[1]))
    return sorted(out)


def file_control_ask(n: int, sid: str, q: str, link: str, branch: str = '') -> str:
    """File control session `n`'s open question under Needs you: a task blocked `DECIDE: <q> <link>`, committed
    as `watch_ci` commits its tasks (MERGE free, TODO.md clean). Its id, or '' when it could not be filed now."""
    if not MERGE.acquire(blocking=False):
        return ''
    hold = ExitStack()
    try:
        if C.plan_external:
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        rel = plan_rel('TODO.md')
        if not C.plan_external and (git('status', '--porcelain', '--', rel).stdout.strip() or branch and
                                    git('branch', '--show-current').stdout.strip() != branch):
            return ''  # somebody mid-edit, or the main checkout on another branch: the next look files it
        where = link or f'resume it with `{plat.exe(C.run["agent"])} --resume {sid}`'
        tid = P.add(control_cfg()['kind'], f'Control session {n} asked the person: "{q}" Carry on from their '
                    f'answer (the session, closed while it waited: {where})', todo=ROOT / rel, pri='normal')
        P.block(tid, f'DECIDE: {q} {link}'.strip(), todo=ROOT / rel, after=[])
        if not commit_plan(f'Plan: {tid}, control {n} asked the person', rel):
            if not C.plan_external:
                git('checkout', '-q', '--', rel)
            return ''
        return tid
    finally:
        hold.close()
        MERGE.release()


def close_controls(branch: str = '', force: bool = False, now: float | None = None) -> list[tuple[int, str, str]]:
    """B26: close the idle control sessions (see above), every CONTROL_CLOSE_EVERY s from the run loop.
    [(n, 'closed' | 'asked', why or the task id filed)] for those closed."""
    cf = control_cfg()
    if not cf['close'] or not control_ok() or (not force and time.time() - CONTROL_CLOSE_AT[0] < CONTROL_CLOSE_EVERY):
        return []
    CONTROL_CLOSE_AT[0] = time.time()
    now = time.time() if now is None else now
    out = []
    for n in control_live_numbers():
        pidf = C.notes(f'control{n}.pid')
        try:
            pid_s, _, sid = pidf.read_text(encoding='utf-8').strip().partition(' ')
            pid = int(pid_s)
        except (OSError, ValueError):
            continue
        if not sid or not transcript(sid):
            continue
        st = control_state(entries(sid, skip_bad=True))
        verdict, why = control_verdict(st, cf, now, n, control_one_ask(n, sid))
        if verdict == 'keep':
            continue
        link = control_link(st['bridge'])
        if verdict == 'ask' and cf['file_asks']:
            if not (tid := file_control_ask(n, sid, why, link, branch)):
                continue  # TODO.md busy: the next look files it
            log(f'{tid}: filed, control {n} asked "{why}" (DECIDE, under {P.needs_cfg()["heading"]})')
            note(f'{tid}: filed, an open question of control {n}')
            why = tid
        plat.terminate(pid)
        pidf.unlink(missing_ok=True)
        log(f'control {n}: closed, ' + (f'its question filed as {why}' if verdict == 'ask' and cf['file_asks']
                                        else why) + f' (transcript kept: {plat.exe(C.run["agent"])} --resume {sid})')
        out.append((n, 'asked' if verdict == 'ask' else 'closed', why))
    return out


# --- B53: control sessions closed online (archived or deleted in claude.ai/code or the apps) end here too ----
#
# Claude Code keeps running when its Remote Control session is archived or deleted elsewhere: it only writes a
# system entry to its transcript, "Remote Control disconnected — this session was ended or archived from
# another device or app (code 4090)" (or "— the server no longer reports this session — it may have been
# deleted …", same code), and goes on locally. So its controlN.pid stays live and control_number() never hands
# N out again. Every CONTROL_CLOSE_EVERY s (and before `control --new` picks a number) each live control
# session N > 1 whose transcript's last word is that disconnect, with no message the person typed since (one
# typed in its terminal after it means they still use it there) and no new Remote Control session since, is
# ended: its process, its tmux pane, controlN.pid and controlN.title. The transcript stays, resumable. c1 is
# left alone: it is the run's kept session (resumed across runs, local-only under [run] remote), as in B26.

RC_CLOSED = re.compile(r'Remote Control disconnected\b.*\(code 4090\)')
CONTROL_GONE_AT = [0.0]


def closed_online(rows) -> bool:
    """Whether a control session's transcript entries `rows` say its Remote Control session was closed online
    (archived or deleted) and nobody used it since: a code-4090 disconnect entry, and after it no message the
    person typed and no bridge-session entry naming another Remote Control session (a reconnect)."""
    closed, bridge = False, ''
    for d in rows:
        if not isinstance(d, dict):
            continue
        kind = d.get('type')
        if kind == 'bridge-session' and isinstance(d.get('bridgeSessionId'), str):
            if closed and d['bridgeSessionId'] != bridge:
                closed = False  # connected again, as another session
            bridge = d['bridgeSessionId']
        elif kind == 'system' and isinstance(d.get('content'), str) and RC_CLOSED.search(d['content']):
            closed = True
        elif kind == 'user' and person_message(d):
            closed = False
    return closed


def control_window(n: int, pid: int) -> str:
    """The tmux pane control session `n` (process `pid`) runs in, found by its c<n> tag for this repository or
    by its pane pid; '' for none. Never $TMUX_PANE: the caller is the run, not that session."""
    if not shutil.which('tmux'):
        return ''
    rows = tmux('list-panes', '-a', '-F', f'#{{session_name}}\t#{{pane_id}}\t#{{{TAG}}}\t#{{{REPO_TAG}}}\t'
                f'#{{{RUN_TAG}}}\t#{{pane_pid}}')
    if rows.returncode:
        return ''
    lines = rows.stdout.splitlines()
    if hit := attach_target([l.rsplit('\t', 1)[0] for l in lines], ROOT, f'c{n}'):
        return hit[1]
    for l in lines:
        f = l.split('\t')
        if len(f) >= 6 and f[5] == str(pid):
            return f[1]
    return ''


def end_closed_controls(force: bool = False) -> list[int]:
    """B53: end the control sessions closed online (see above). The numbers ended."""
    if not control_ok() or (not force and time.time() - CONTROL_GONE_AT[0] < CONTROL_CLOSE_EVERY):
        return []
    CONTROL_GONE_AT[0] = time.time()
    out = []
    for n in control_live_numbers():
        pidf = C.notes(f'control{n}.pid')
        try:
            pid_s, _, sid = pidf.read_text(encoding='utf-8').strip().partition(' ')
            pid = int(pid_s)
        except (OSError, ValueError):
            continue
        try:
            if not sid or not transcript(sid) or not closed_online(entries(sid, skip_bad=True)):
                continue
            pane = control_window(n, pid)
        except Exception as e:  # one unreadable session never stops the run loop or a new session
            log(f'control {n}: could not tell whether it was closed online: {e}')
            continue
        plat.terminate(pid)
        if pane:  # its pane only (a window of its own closes with it); one whose command falls back to a shell too
            tmux('kill-pane', '-t', pane)
        pidf.unlink(missing_ok=True)
        C.notes(f'control{n}.title').unlink(missing_ok=True)
        log(f'control {n}: ended, its Remote Control session was closed online '
            f'(transcript kept: {plat.exe(C.run["agent"])} --resume {sid})')
        out.append(n)
    return out


def free_control_number() -> int:
    """control_number() once the control sessions closed online have ended (B53), so their numbers count free."""
    end_closed_controls(force=True)
    return control_number()


def control_server_argv() -> list[str]:
    """With `[run] remote`: Claude Code's Remote Control server in the main checkout, so new control sessions can
    be started from claude.ai/code and the Claude apps, each with the control settings (its brief)."""
    exe = plat.exe(C.run['agent'])
    return [exe, 'remote-control', '--spawn', 'same-dir', '--name', f'{ROOT.name} · control',
            '--permission-mode', 'bypassPermissions',
            *(['--settings', str(control_settings())] if server_takes_settings(exe) else [])]


_SERVER_SETTINGS: dict[str, bool] = {}


def server_takes_settings(exe: str) -> bool:
    """Whether this agent's `remote-control` takes `--settings` (asked of its --help once a run): an older Claude
    Code exits at once on it, which would crash-loop the control server. An agent whose help cannot be read
    (missing, hangs, prints nothing) is taken to have it, as before."""
    if exe not in _SERVER_SETTINGS:
        try:
            r = sp.run([exe, 'remote-control', '--help'], stdin=sp.DEVNULL, capture_output=True, text=True,
                       errors='replace', timeout=30)
            said = (r.stdout or '') + (r.stderr or '')
            _SERVER_SETTINGS[exe] = '--settings' in said or not said.strip()
        except (OSError, sp.SubprocessError):
            _SERVER_SETTINGS[exe] = True
    return _SERVER_SETTINGS[exe]


def server_last_error(err: Path, since: int) -> str:
    """The last non-blank line the control server wrote to stderr (`err`) after offset `since`, cut to 200."""
    try:
        with open(err, 'rb') as fh:
            fh.seek(since)
            lines = fh.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return ''
    lines = [re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', x).strip() for x in lines]
    return next((x[:200] for x in reversed(lines) if x), '')


def control_server_live() -> int:
    """The pid of the control server a run started (`<notes>/control-server.pid`), still up, or 0."""
    pid = marker_pid(C.notes('control-server.pid'))
    args = plat.cmdline(pid) if pid and plat.alive(pid) else None
    return pid if pid and plat.alive(pid) and (args is None or 'remote-control' in args) else 0


def keep_control_server() -> None:
    """Keep the control server running while the run is up: restarted when it exits (Remote Control quits after
    about 10 minutes offline), after 30 s, doubling to 10 minutes while it keeps failing at once. One a run
    before an upgrade restart left is adopted; the run's end ends it."""
    import atexit
    pidf, out, err = C.notes('control-server.pid'), C.notes('control-server.log'), C.notes('control-server.err')
    atexit.register(lambda: (pid := control_server_live()) and plat.terminate(pid))
    backend().trust(ROOT)  # it asks to trust a new folder, and has no terminal to ask on
    if '--settings' not in control_server_argv():
        log('control: this Claude Code\'s `remote-control` has no --settings, so the control server starts without '
            'it: sessions started from claude.ai/code will not get the control brief. Update Claude Code '
            '(`claude update`) to give them it')
    wait = CONTROL_SERVER_WAIT[0] // 2  # doubled at the first exit
    if (pid := control_server_live()) and server_stale(plat.cmdline(pid)):
        log(f'control: the control server an earlier run left (pid {pid}) has other flags; restarting it')
        plat.terminate(pid)
    while True:
        proc = None
        if not (pid := control_server_live()):
            since = out.stat().st_size if out.exists() else 0
            err_since = err.stat().st_size if err.exists() else 0
            env = control_env()
            if silent() is not False:  # silent while it starts (silent = true: for good)
                env[PRESENCE_ENV] = str(quiet_file('server'))
            with open(out, 'ab') as fh, open(err, 'ab') as eh:
                try:
                    proc = sp.Popen(control_server_argv(), cwd=str(ROOT), env=env, stdin=sp.DEVNULL,
                                    stdout=fh, stderr=eh, start_new_session=not plat.WINDOWS)
                except OSError as e:
                    quiet_file('server', on=False)
                    log(f'control: the control server did not start: {e}')
                    return
            if silent() == 'launch':
                threading.Thread(target=unquiet_when_up, args=('server',), kwargs={'log_file': out, 'since': since},
                                 daemon=True).start()
            pid = proc.pid
            pidf.write_text(str(pid), encoding='utf-8')
            rc_record('server', f'{ROOT.name} · control', pid, os.getpid())  # B12
            log(f'control: control server up as "{ROOT.name} · control" at {REMOTE_URL} (pid {pid})')
        else:  # adopted from an earlier run: this run's now (B12: the start's sweep leaves it to us)
            rc_record('server', f'{ROOT.name} · control', pid, os.getpid())
        began = time.monotonic()
        while (proc.poll() is None) if proc else plat.alive(pid):
            time.sleep(1 if time.monotonic() - began < 30 else 10)
        rc_forget(C.notes(REMOTE_DIR) / f'server-{pid}.json')
        lasted = time.monotonic() - began
        wait = CONTROL_SERVER_WAIT[0] if lasted > 600 else min(wait * 2, CONTROL_SERVER_WAIT[1])
        said = server_last_error(err, err_since) if proc and lasted < 60 else ''
        if said:  # it quit at once: its error says why (an unknown option, a login)
            said = f'after {lasted:.0f} s: {said}'
        else:
            try:
                said = out.read_text(encoding='utf-8', errors='replace').strip().splitlines()[-1][:200]
            except (OSError, IndexError):
                said = ''
        log(f'control: the control server exited{f" ({said})" if said else ""}; restarting it in {wait} s')
        time.sleep(wait)


def server_stale(args: list[str] | None) -> bool:
    """A running control server's argv (None: unreadable, so kept) started with other flags than this run's:
    `--settings` is read once, and the flags apply to every session it starts, so an adopted one must match."""
    return args is not None and [a for a in args if a][1:] != control_server_argv()[1:]


def start_control_server() -> None:
    if remote_on() and C.run['control'] and control_ok():
        threading.Thread(target=keep_control_server, name='control-server', daemon=True).start()


# --- Remote Control sessions a run started (B12) ---------------------------------
# Claude Code offers no command to end or archive a Remote Control session from outside it, and none to list
# them; it archives its own entry in claude.ai/code and the apps when it exits on SIGTERM, SIGHUP or SIGINT
# (its teardown: "archiving session", "environment deregistered"). An entry stays listed only when its
# process dies without that teardown: SIGKILL, a crash, a reboot, or a power-off right after a stop. So the
# run records each Remote Control process it starts, ends them with SIGTERM and waits for the teardown (on a
# stop, and at the next start for those an earlier run left), and never SIGKILLs one.

REMOTE_DIR = 'remote'  # <notes>/remote/<kind>-<pid>.json: a Remote Control process a run started
RC_TEARDOWN = 20  # s a Remote Control process gets after SIGTERM to archive its entry and exit
RC_RUN_KINDS = ('feed', 'server')  # what a run starts for itself; control sessions are the person's, left up
RC_ENDING = [False]  # set by the stop's sweep: keep_board opens no new feed while the run ends


def run_key(pid: int) -> str:
    """One run's identity: its pid and start time (after it ends, its pid can be anyone's)."""
    return f'{pid}:{plat.started(pid) or ""}'


def rc_record(kind: str, name: str, pid: int, run_pid: int, sid: str = '') -> Path:
    """Record Remote Control process `pid` ("<name>" in the apps), started for the run `run_pid`."""
    d = C.notes(REMOTE_DIR)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f'{kind}-{pid}.json'
    rec = {'kind': kind, 'name': name, 'pid': pid, 'run': run_key(run_pid), 'sid': sid}
    if (start := plat.started(pid)) is not None:
        rec['start'] = start
    f.write_text(json.dumps(rec), encoding='utf-8')
    return f


def rc_records() -> list[dict]:
    """The recorded Remote Control processes, each with its file as 'rec'."""
    d = C.notes(REMOTE_DIR)
    out = []
    for f in sorted(d.glob('*.json')) if d.is_dir() else []:
        try:
            out.append({**json.loads(f.read_text(encoding='utf-8')), 'rec': str(f)})
        except (OSError, ValueError):
            f.unlink(missing_ok=True)
    return out


def rc_forget(rec: dict | Path | None, killed: bool = False) -> None:
    """Drop a record whose process ended (its teardown archived its entry); `killed` (SIGKILL: no teardown)
    keeps it, marked, for the next start to name as possibly still listed."""
    if not rec:
        return
    f = Path(rec['rec'] if isinstance(rec, dict) else rec)
    if not killed:
        f.unlink(missing_ok=True)
        return
    try:
        f.write_text(json.dumps({**json.loads(f.read_text(encoding='utf-8')), 'killed': True}), encoding='utf-8')
    except (OSError, ValueError):
        pass


def rc_sweep(run_pid: int, stopping: bool = False, wait: float = RC_TEARDOWN,
             keep_server: bool = False) -> tuple[list[str], list[str]]:
    """End the Remote Control processes the run owns, so the apps list only live sessions: on a run's start,
    those an earlier run left (its feed, its control server unless `keep_server`: this run adopts it, so no new
    entry); with `stopping`, this run's own as well. Each gets SIGTERM and up to `wait` s for its teardown,
    which archives its entry; one still up then is left (the next start tries again), never SIGKILLed.
    Control sessions are the person's and stay up, and nothing the run did not record (a session the person
    started) is touched. A record whose process is gone is dropped, named in run.log when it died killed
    (no teardown: its entry may still be listed). Returns (names ended, names left running)."""
    mine = run_key(run_pid)
    ending = []
    for s in rc_records():
        if not gate_alive(s):
            if s.get('killed'):
                log(f'remote: "{s.get("name")}" was killed before it could archive itself; if it is still listed '
                    f'at {REMOTE_URL}, archive it there')
            rc_forget(s)
        elif s.get('kind') not in RC_RUN_KINDS or s.get('run') == mine and not stopping:
            continue  # a control session, or this run's own while it runs
        elif s.get('kind') == 'server' and keep_server and s.get('run') != mine:
            continue  # keep_control_server adopts it (or restarts it when its flags differ)
        else:
            ending.append(s)
    for s in ending:
        plat.terminate(s['pid'])
    end = time.monotonic() + wait
    while (up := [s for s in ending if gate_alive(s)]) and time.monotonic() < end:
        time.sleep(0.25)
    gone = [s for s in ending if s not in up]
    for s in gone:
        rc_forget(s)
    if gone:
        names = ', '.join(f'"{s["name"]}"' for s in gone)
        log(f'remote: ended {names} '
            f'({"this run" if stopping else "left by an earlier run"}); their entries are archived')
    for s in up:
        log(f'remote: "{s["name"]}" (pid {s["pid"]}) did not end within {wait:g} s of SIGTERM; left running, '
            f'the next start ends it')
    return [s['name'] for s in gone], [s['name'] for s in up]


def rc_sweep_start() -> None:
    """The run's start: end what an earlier run left on Remote Control, in the background (it can wait)."""
    keep = remote_on() and bool(C.run['control']) and control_ok()
    threading.Thread(target=rc_sweep, args=(os.getpid(),), kwargs={'keep_server': keep},
                     name='remote-sweep', daemon=True).start()
