"""Control sessions: a person runs the run from an interactive session (briefs, names, asks, panes), idle
ones are closed, the control server, and the Remote Control processes a run started."""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import subprocess as sp
import sys
import threading
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

from agent_runner import pitch, plan as P, plansync, plat, session_theme
from agent_runner.plan import decide_question  # F135: a control session's last line `DECIDE: …`
from agent_runner.control_settled import LEAD  # F160: how the runner's own typed line starts
from agent_runner.config import RUNNER, runner_cmd
from agent_runner.state import C, commit_plan, git, init, log, MERGE, note, plan_rel, ROOT
from agent_runner.brief import has_sheet
from agent_runner.slots import (backend, entries, marker_pid, PRESENCE_ENV, quiet_file, remote_on,
    REMOTE_URL, silent, transcript)
from agent_runner.merge import gate_alive


# --- control sessions: a person runs the run from an interactive session in the main checkout -------------

CONTROL_SERVER_WAIT = (30, 600)  # s before the control server restarts after it exits, doubling to the second


def control_cmd() -> str:
    """B93: the command a control session's brief, opening, skills and hints name: `[run] command` (e.g. openmx's
    `./kit`, which forwards every runner command once it has loaded the kit's settings), else the runner. The bare runner in a wrapped repo would skip the kit's config."""
    return C.command


def control_brief() -> str:
    """What every control session is told, through its SessionStart hook (`control --brief` prints it).
    B98: kept under BRIEF_MAX chars: Claude Code shows a model only a 2KB preview of SessionStart output over
    ~10KB, so the core rules are inline and the long ones behind `guide <topic>` (guide.CONTROL_TOPICS); the
    glossary's and the wording's paragraphs are pointers too (glossary.brief_fit, voice.brief_fit)."""
    from agent_runner.guide import CONTROL, CONTROL_ANSWER
    notes = Path(C.run['notes']).expanduser()
    logf = (notes / 'run.log').as_posix() if not notes.is_absolute() else str(notes / 'run.log')
    cmd = control_cmd()  # B93: [run] command, not the bare runner (B71's partial ./kit is outdated)
    cf = P.needs_cfg()  # B27: the heading's words
    answer = CONTROL_ANSWER.format(cmd=cmd)
    from agent_runner import glossary  # F22: the glossary paragraph (and the seed ask), or none when it is off
    from agent_runner.guide import grill_fit  # F20: the grilling line fitted to [run] grill
    from agent_runner import voice  # F21: the person's wording, read fresh by every session's brief
    core = grill_fit(glossary.brief_fit(CONTROL.format(repo=ROOT.name, cmd=cmd, log=logf,
                                                       needs=cf['heading'], answer=answer), cmd, C), cmd, C)
    out = voice.brief_fit(core, cmd, C)
    if len(out) >= BRIEF_MAX:  # B104: a long [run] command (Windows: python.exe and the run path) first
        core = bare_commands(core, cmd)
        out = voice.brief_fit(core, cmd, C)
    # B98: a long voice file would push the brief past what Claude Code shows: point at its lines instead
    return out if len(out) < BRIEF_MAX else voice.brief_fit(core, cmd, C, inline=False)


def bare_commands(core: str, cmd: str) -> str:
    """B104: the control brief with every runner command after its Guide pages line (`{cmd}` is the runner: a
    bare runner command below means `{cmd} <that command>`) in that bare form (`plan add …`, `guide take`), so a
    long `[run] command` repeated in every line does not push the brief past BRIEF_MAX and the wording out of it.
    C21: the mark is that line's end, so it changes with the line's wording."""
    mark = f'`{cmd} <that command>`'
    at = core.find(mark)
    if at < 0:
        return core
    at += len(mark)
    return core[:at] + core[at:].replace(f'`{cmd} ', '`')


# B98: Claude Code saves SessionStart output over ~10KB to a file and shows the model a 2KB preview of it
BRIEF_MAX = 9500


def control_settings_data() -> dict:
    """`<notes>/control-settings.json`, given to every control session and the control server with --settings:
    a SessionStart hook (every source: startup, resume, clear, compact) that prints the control brief, so each
    one gets it the same way however it started; and the runner's commands, Read and Monitor allowed without a
    prompt. Control sessions run with bypassPermissions (`control_argv`, `control_server_argv`), so a person on a
    phone never waits on a permission question; the bypass dialog is skipped here for the same reason. No Stop
    hook: a control session is never ended on idle."""
    hook = plat.command_text([*runner_cmd(), 'control', '--brief'])
    return {'hooks': {'SessionStart': [{'hooks': [{'type': 'command', 'command': hook}]}]},
            'skipDangerousModePermissionPrompt': True, **session_theme.settings(),  # F170: the run page's look
            'permissions': {'additionalDirectories': [str(control_skills_dir())]}}


CONTROL_SKILL = 'control'  # the slash command: Claude Code's /new is /clear's alias, so not that


def control_skills_dir() -> Path:
    """`<notes>/control-skills`: a directory only control sessions add (`--add-dir`, and the settings'
    additionalDirectories), holding `.claude/skills/control/SKILL.md`, the /control slash command that opens
    another control session. Never in the person's repo files."""
    from agent_runner.guide import control_skills  # /control, and the opening hints line's /run /since …
    for name, text in control_skills(control_cmd(), CONTROL_SKILL).items():  # B93: [run] command
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


# F93: Talk, the run page's spoken chat: its own control session, titled Talk, whose first message
# (`talk_ask`) says how to answer so a reply reads well aloud; each later message carries TALK_TAG.
TALK_TITLE = 'Talk'
TALK_LEAD = 'Talk mode:'
TALK_BRIEF = (
    f"{TALK_LEAD} the person is talking to you by voice, maybe on a phone or walking, and hears every reply read "
    "aloud by their browser. Answer as you would speak: short plain sentences, a few at most, one thing at a time. "
    "Never say task IDs, branch names, file paths, commands, links or session numbers, and use no markdown, "
    "lists, tables, code or emoji. Say what a task is in words (\"the merge retry fix\", not its ID), round "
    "numbers (\"about twenty minutes\"), and name only what matters most; offer more if there is more. When "
    "something needs a page or a link, say you will put it in the chat instead of reading it out. Do everything "
    "else your brief says, but this session is already named Talk: do not run control --title. Each later "
    "message starts with a short reminder of this.")
TALK_SAID = 'They said: '
TALK_TAG = '(Talk: answer as speech.) '


def talk_ask(words: str) -> str:
    """F93: the first message of the Talk session: TALK_BRIEF, then the person's first words."""
    return f'{TALK_BRIEF}\n\n{TALK_SAID}{words.strip()}'


def talk_message(words: str) -> str:
    """F93: a later Talk message: TALK_TAG, then the person's words."""
    return TALK_TAG + words.strip()


def control_title(ask: str = '', images: list[str] | tuple = ()) -> str:
    """A short title for a control session opened with `--ask`: the ask's first words (up to 5, trimmed at a word
    to about 40 characters, trailing punctuation dropped); for a files-only ask "screenshot" when they are all
    images, else the first file's name (B30); "" without one. F93: a Talk ask (`talk_ask`) is titled Talk."""
    if (ask or '').startswith(TALK_BRIEF):  # the whole brief, so a typed "Talk mode: …" is not taken for Talk
        return TALK_TITLE
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
        control_keep_sid(n, new)  # B121: a reopen after a shutdown resumes the conversation it has now
    if old and transcript(old) and control_renamed(control_state(entries(old, skip_bad=True)), n):
        return ''  # the person named it: never overwritten
    base, given = control_base_name(n), control_given(n)
    if not given or given in (base, control_name(n)):
        return ''
    if not control_type(n, f'/rename {base}'):
        return ''
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


def control_type(n: int, text: str) -> bool:
    """Type `text` into control session `n` and press Enter, through its hidden shim's FIFO
    (`<notes>/control<n>.in`); False when it has none (a hidden console, or a session opened in a terminal)."""
    from agent_runner.slots import send_fifo
    inbox = C.notes(f'control{n}.in')
    return inbox.exists() and send_fifo(inbox, text)


def control_set_title(n: int, summary: str) -> int:
    """F29 `control --title SUMMARY`: control session `n` (its own $AGENT_RUNNER_CONTROL) names itself for what
    it is for, once it has read its first message. C26: the name is kept in state (`control_give`), which the
    TUI, the run page and `list` read; a hidden session also gets `/rename <repo> · N · SUMMARY` typed in
    (queued until its turn ends), so the Claude apps show it. Not over a name the person gave it (B41)."""
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
    st = control_state(entries(sid, skip_bad=True)) if sid and transcript(sid) else {}
    if control_renamed(st, n):
        print(f'control {n} keeps the name the person gave it')
        return 0
    control_give(n, name)
    if control_type(n, f'/rename {name}'):
        print(f'control {n} is renamed "{name}" when this turn ends')
    else:
        print(f'control {n} is named "{name}" on the run page and in the TUI (it runs in a terminal of its own, '
              f'so the Claude apps keep its name)')
    return 0


def control_ask(ask: str, images: list[str] | tuple = ()) -> str:
    """The first message a handed-on request opens a control session with: `ask`, and for each `--file PATH`
    (`--image`: an alias) a line saying the person attached that file, by name and saved path, and to Read or open
    it before answering (a message carries text only, so a screenshot or an upload reaches the new session
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
            f'\nSettle one by its id (`{control_cmd()} plan confirm|change|shelve ID`, not only a new task) only if the '
            'words above answer it; else say nothing of these.\n</runner-waiting>')


def ask_waiting() -> str:
    """The items under Needs you, one '- ID: ask' line each, for a handed-on request (B47); '' when none or the
    plan cannot be read (opening the session matters more)."""
    try:
        return '\n'.join(f'- {a[1]}: {P.plain_ask(a[0], a[3], a[5], a[0] == "DECIDE" and has_sheet(a[1]))}'
                         + (f' {a[4]}' if a[4] and a[0] == 'DECIDE' and has_sheet(a[1]) else '') for a in P.asks() + pitch.rows(C))
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


def control_model() -> str:
    """F101: `[models] control` (opus by default), else `[run] model`."""
    return (C.raw.get('models') or {}).get('control') or C.run['model']


def control_argv(n: int, sid: str, resume: bool, ask: str = '', images: list[str] | tuple = (),
                 typed: bool | None = None) -> list[str]:
    """Control session `n`: interactive, on `[models] control`, the brief from its settings
    file; with `[run] remote` on Remote Control as "<repo> · control N". F176: with no `ask` it gets no first
    message and stays blank until the person types, its brief still loaded by the SessionStart hook.
    bypassPermissions, as the slots: it is driven from a phone or the web as often as from here, and a permission
    prompt there stalls it. Not lean: a person is there (all tools, so /statusline and the like work). `ask`
    (`control --new --ask TEXT`, from the runner feed): TEXT is its first message; `images` (`--file
    PATH`, alias `--image`, repeatable) adds a line per attached file to it (`control_ask`). B147: on Remote
    Control a positional first message runs before the bridge connects, so the claude.ai/code thread would start
    at the reply; there (`typed`, by default `first_typed`) it is left off the command line and kept in
    CONTROL_FIRST for `type_first` to type in once Remote Control is up (control_first.py)."""
    from agent_runner.control_first import CONTROL_FIRST, first_typed
    CONTROL_FIRST[0] = ''
    ask_text, ask = ask, control_ask(ask, images)
    first = [ask] if ask else []
    remote = remote_on()
    if first and remote and (first_typed(n) if typed is None else typed):  # B147: typed in once RC is up
        CONTROL_FIRST[0], first = first[0], []
    return [plat.exe(C.run['agent']), *first,
            '--resume' if resume else '--session-id', sid, '--model', control_model(),
            '--permission-mode', 'bypassPermissions',
            '--settings', str(control_settings()), '--add-dir', str(control_skills_dir()),
            *(['--remote-control', control_name(n, ask_text, images)] if remote else [])]


def control_live(n: int) -> int:
    """The pid control session `n` runs as (`<notes>/control<n>.pid`: "pid sid"), or 0. The sid in its command
    line tells it from a process that got the pid since (where the command line can be read: /proc, or the
    process itself on Windows, B87). B59: after /clear
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


FIRST_CONTROL = 2  # F176: numbers start here; 1 was the kept session's, and what it left is never a new chat's


def control_number() -> int:
    """The first control number, from FIRST_CONTROL, with no live session."""
    n = FIRST_CONTROL
    while control_live(n):
        n += 1
    return n


def control_sid(n: int, reopen: bool = False) -> tuple[str, bool]:
    """(session id, resume?) control session `n` starts with. F176: always a new session, never one an earlier run
    left: its id is kept in `<notes>/control<N>.sid` (`control_sid_file`) only so that `reopen` (`control N
    --reopen`, from `reopen_controls` after a shutdown, or Resume) can carry that conversation on (B121)."""
    if reopen:
        sid = control_kept_sid(n)
        if sid and backend().find_transcript(sid):
            return sid, True
    sid = str(uuid.uuid4())
    control_keep_sid(n, sid)
    return sid, False


def drop_kept_chat() -> None:
    """F176: what a run start leaves behind of earlier runs' sessions, before anything opens: the id of the kept c1
    an older runner resumed in every run (control.sid) and the runner feed's (B195: no run starts one)."""
    C.notes('control.sid').unlink(missing_ok=True)
    from agent_runner.feed import feed_forget_session
    feed_forget_session()


def control_sid_file(n: int) -> Path:
    """B121: where control session `n` keeps its session id: `<notes>/control<n>.sid`."""
    return C.notes(f'control{n}.sid')


def control_keep_sid(n: int, sid: str) -> None:
    """B121: record `sid` as control session `n`'s conversation, for `reopen_controls` after a shutdown."""
    try:
        control_sid_file(n).write_text(sid + '\n', encoding='utf-8')
    except OSError:
        pass


def control_kept_sid(n: int) -> str:
    """B121: control session `n`'s kept session id: the one its pid file names (it follows /clear), else
    control<n>.sid; '' for none."""
    try:
        sid = C.notes(f'control{n}.pid').read_text(encoding='utf-8').strip().partition(' ')[2].strip()
    except OSError:
        sid = ''
    if sid:
        return sid
    try:
        return control_sid_file(n).read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def control_open(n: int, ask: str = '', images: list[str] | tuple = (),
                 reopen: bool = False) -> tuple[str, bool, list[str]]:
    """(session id, resume?, argv) control session `n` starts with (`control N`). A fresh session gets the name the runner gives it
    (F32: never an earlier session N's or a task's) and, opened for an ask, the one-ask mark (F56). B121:
    `reopen` resumes session N's kept conversation under the name it had (`reopen_name`)."""
    sid, resume = control_sid(n, reopen=reopen and not (ask or images))
    argv = control_argv(n, sid, resume, ask=ask, images=images)
    if resume and '--remote-control' in argv:
        from agent_runner.control_reopen import reopen_name
        argv[argv.index('--remote-control') + 1] = reopen_name(n, sid)
    if not resume:
        C.notes(f'control{n}.name').unlink(missing_ok=True)  # F129: the name was an earlier session N's
        control_give(n, control_name(n, ask, images))
        control_mark_ask(n, sid if ask else '')
    return sid, resume, argv


def control_env() -> dict:
    """The environment a control session gets: ours, without a slot's marks (`plan add` treats AGENT_RUNNER=1 as
    one of the runner's agents), with RUNNER_STARTED_ENV: its brief comes through --settings, so the hand hook
    (`hand_hook`) stays quiet. B108: with ARTIFACT_ENV on, so a session started headless (the control server
    spawns them with entrypoint sdk-cli, where Claude Code leaves the Artifact tool off by default) can still
    publish a page and hand over its claude.ai link; a value the person set (0 to turn it off) is kept."""
    env = {k: v for k, v in os.environ.items() if k not in ('AGENT_RUNNER', 'AGENT_RUNNER_SLOT', 'AGENT_RUNNER_KEEP', CONTROL_N_ENV)}
    return {ARTIFACT_ENV: '1', **env, RUNNER_STARTED_ENV: '1'}


RUNNER_STARTED_ENV = 'AGENT_RUNNER_CONTROL_SESSION'
ARTIFACT_ENV = 'CLAUDE_CODE_ARTIFACT'  # Claude Code 2.1.3xx: turns the Artifact tool on for sdk-cli sessions


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
    of its own (`hand_hook`)."""
    import contextlib
    with contextlib.redirect_stderr(io.StringIO()):  # init's git calls and merge driver: nothing on the screen
        init(root)
        return control_brief()


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


def start_control() -> None:
    """The run's start. F176: it opens no control session and resumes none (`drop_kept_chat`): each prompt opens one
    of its own. B121: the ones a shutdown cut off are reopened (`reopen_controls`), unless `[run] control = false`."""
    try:
        drop_kept_chat()
    except OSError as e:  # never stops the run from starting
        log(f'control: could not forget the sessions an earlier run kept: {e}')
    if C.run['control']:
        try:
            from agent_runner.control_reopen import reopen_controls
            reopen_controls()
        except Exception as e:  # never stops the run from starting
            log(f'control: could not reopen the control sessions a shutdown ended: {e}')


def hidden_control_log(n: int) -> Path:
    """F59: where a hidden control session's output goes: `<notes>/control<n>.log`."""
    return C.notes(f'control{n}.log')


def hidden_control(n: int, cmd: list[str], wait: float | None = None) -> tuple[int, str]:
    """F59: start control session `n` (`cmd`, a `control N` command line) with no window, through
    the F40 pty shim (`run --slot-shim`: `run_pty`, `run_conpty`) with a job of its own, `<notes>/control<n>.job`:
    its output goes to `hidden_control_log`, its pid to `<notes>/control<n>.live` while it runs, and text
    written to the FIFO beside it (`control<n>.in`) is typed into it. Started detached, so it outlives the run
    the run. (pid, '') once it is up, else (0, why)."""
    return hidden_shim(f'control{n}', cmd, wait)


SHIM_ALREADY = 'it was already up'  # B131: hidden_shim's why beside the pid of a session it found running


def hidden_shim(stem: str, cmd: list[str], wait: float | None = None) -> tuple[int, str]:
    """`hidden_control` for any hidden session named `stem` (control3): its job, marker, log, FIFO and
    attach socket are `<notes>/<stem>.job|.live|.log|.in|.sock`. (pid, '') once it is up, else (0, why).
    B131: when `<stem>.live` already names a live pid (two `control --new` that picked the same number), that
    session is left as it is, its job, marker and log untouched, and the answer is (its pid, SHIM_ALREADY)."""
    from agent_runner.slots import SHIM_WAIT
    job, marker = C.notes(f'{stem}.job'), C.notes(f'{stem}.live')
    if (up := marker_pid(marker)) and up != os.getpid() and plat.alive(up):
        return up, SHIM_ALREADY
    ended = marker.with_suffix('.exit')
    marker.unlink(missing_ok=True)
    ended.unlink(missing_ok=True)
    job.write_text(json.dumps({'argv': cmd, 'cwd': str(ROOT), 'env': {}, 'marker': str(marker), 'look': session_theme.settings().get('theme', ''),
                               'log': str(C.notes(f'{stem}.log'))}), encoding='utf-8')
    shim = [*runner_cmd(), 'run', '--slot-shim', str(job)]
    try:
        plat.spawn_detached(shim, C.notes(f'{stem}.shim'), ROOT, control_env())  # .shim: its own errors
    except OSError as e:
        return 0, f'could not start the shim: {e}'
    end = time.monotonic() + (SHIM_WAIT if wait is None else wait)
    while time.monotonic() < end:
        if pid := marker_pid(marker):
            return pid, ''
        if ended.exists():
            return 0, ended.read_text(encoding='utf-8').strip()[:300] or 'it ended at once'
        time.sleep(0.2)
    return 0, f'it did not start in {SHIM_WAIT if wait is None else wait:g} s (see {C.notes(f"{stem}.shim")})'


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
    if isinstance(c := (d.get('message') or {}).get('content'), str):
        return not c.startswith(('<task-notification>', LEAD))
    return isinstance(c, list) and any(isinstance(x, dict) and x.get('type') in ('text', 'image') and not str(x.get('text') or '').startswith(LEAD) for x in c)


RUNNER_TURN = ('<command-name>', '<command-message>', '<command-args>', '<local-command-', '<system-reminder>',
               '<task-notification>', '<user-prompt-submit-hook>', 'Caveat: ', LEAD)


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
# Every CONTROL_CLOSE_EVERY s the run reads the transcript of each live control session N
# and closes it (ends its process, removes controlN.pid; the transcript stays, resumable) when Claude
# spoke last, nothing runs in it, and it has been quiet `[run] control_idle`; or, when its last line is
# `DECIDE: <question>` (F135; an offer is not filed), quiet `[run] control_ask`: then the question is filed under
# Needs you as a DECIDE item (an F task) first. `control_idle = false` closes none for idleness, `control_ask =
# false` keeps one waiting on its question open; both false turn it off.

CONTROL_CLOSE_EVERY = 300  # s between looks
CONTROL_CLOSE_AT = [0.0]
CONTROL_ASK_KIND = 'F'  # C14: the id prefix an open question's task gets (was [run] control_ask_kind)
CONTROL_WATCH_CMD = 'since --follow --needs-you'  # an older version's standing watch (B195), or one asked for: not work in progress
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


QUICK_IDLE, TALKED_IDLE = 300.0, 43200.0  # F166: s; a one-ask session that queued, and a talked one, close after it
# an offer or unmarked question: not filed (F135), only named in the log; punctuation must end it, words may stand anywhere
OPEN_PHRASES = ('?', 'want me to', 'should i', 'shall i', 'would you like', 'do you want')


def control_cfg() -> dict:
    """`[run] control_idle` (idle), QUICK_IDLE (quick), TALKED_IDLE (talked), `[run] control_ask` (ask_idle), in
    seconds, 0 off (control_idle off turns the quick and talked tiers off too), and OPEN_PHRASES (open)."""
    r = C.run
    idle = duration(r.get('control_idle', '3h'), 10800.0)
    return {'idle': idle, 'quick': QUICK_IDLE if idle else 0.0, 'talked': TALKED_IDLE if idle else 0.0,
            'ask_idle': duration(r.get('control_ask', '2h'), 7200.0), 'open': list(OPEN_PHRASES)}


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
    from agent_runner.control_names import person_name
    if n and person_name(n, t):  # F129: renamed on the run page or in the TUI
        return True
    return bool(t) and not (n and t in (control_name(n), control_base_name(n), control_given(n)))


def control_verdict(st: dict, cf: dict, now: float, n: int = 0, one_ask: bool = False) -> tuple[str, str]:
    """('close' | 'ask' | 'keep', why or the question) for control session `n`'s state `st` (`control_state`).
    One the person renamed is kept (B41): they named it to keep it. F56, which idle time applies: a session the
    person sent more than one message in, TALKED_IDLE; one opened for one ask (`one_ask`: the runner gave it its first message) that the person
    sent nothing more to and that queued a task, with no open question, QUICK_IDLE; else (or with that
    tier off) `control_idle`. F57: an open question is filed after `control_ask`, or in a talked session after the
    longer of that and TALKED_IDLE. F135: only a `decide_question` is; an offer (`open_question`) closes
    when idle (never quick), its why naming it."""
    if control_renamed(st, n):
        return 'keep', 'renamed by the person'
    if st['last'] != 'claude':
        return 'keep', {'person': 'the person spoke last', 'tool': 'a turn is under way'}.get(st['last'], 'no turn yet')
    if st['running']:
        return 'keep', f'{len(st["running"])} background task(s) still running'
    quiet = now - st['at'] if st['at'] else 0
    talked = st.get('said', 0) > 1 and cf.get('talked')
    if q := decide_question(st['text']):
        # F57: a talked session's question waits TALKED_IDLE too, so it stays open as long as any talk
        ask = max(cf['ask_idle'], cf['talked']) if talked and cf['ask_idle'] else cf['ask_idle']
        if ask and quiet >= ask:
            return 'ask', q
        return 'keep', 'its DECIDE question is not old enough' if cf['ask_idle'] else 'a DECIDE question (control_ask = false)'
    offer = open_question(st['text'], cf['open'])  # F135: not filed, only named in the close's run.log line
    if talked:
        idle, tier = cf['talked'], ' (talked)'
    elif one_ask and st.get('said', 0) == 1 and st.get('queued') and cf.get('quick') and not offer:
        idle, tier = cf['quick'], ' (one ask, queued)'
    else:
        idle, tier = cf['idle'], ''
    if idle and quiet >= idle:
        return 'close', f'idle {int(quiet // 60)} min{tier}' + (f', "{offer}" not filed (no DECIDE line)' * bool(offer))
    return 'keep', 'active lately'


def control_link(bridge: str) -> str:
    """A Remote Control session id (cse_…) as its claude.ai/code link; '' for none."""
    return f'{REMOTE_URL}/session_{bridge[4:]}' if bridge.startswith('cse_') else ''


def control_live_numbers() -> list[int]:
    """The numbers of the control sessions with a pid file and a live process (F176: none is special, so one an
    older runner started as c1 counts too)."""
    out = []
    for f in C.notes().glob('control*.pid'):
        if (m := re.fullmatch(r'control(\d+)\.pid', f.name)) and control_live(int(m[1])):
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
        tid = P.add(CONTROL_ASK_KIND, f'Control session {n} asked the person: "{q}" Carry on from their '
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
    """B26: close the idle ones (see above) every CONTROL_CLOSE_EVERY s: [(n, 'closed' | 'asked', why or task id)]."""
    from agent_runner import control_held
    cf = control_cfg()
    if not (cf['idle'] or cf['ask_idle']) or (not force and time.time() - CONTROL_CLOSE_AT[0] < CONTROL_CLOSE_EVERY):
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
        if verdict == 'keep' or control_held.holds(sid):  # B170
            continue
        link = control_link(st['bridge'])
        if verdict == 'ask':
            if not (tid := file_control_ask(n, sid, why, link, branch)):
                continue  # TODO.md busy: the next look files it
            log(f'{tid}: filed, control {n} asked "{why}" (DECIDE, under {P.needs_cfg()["heading"]})')
            note(f'{tid}: filed, an open question of control {n}')
            why = tid
        plat.terminate(pid)
        pidf.unlink(missing_ok=True)
        log(f'control {n}: closed, ' + (f'its question filed as {why}' if verdict == 'ask' else why) + f' (transcript kept: {plat.exe(C.run["agent"])} --resume {sid})')
        out.append((n, 'asked' if verdict == 'ask' else 'closed', why))
    return out


# --- B53: control sessions closed online (archived or deleted in claude.ai/code or the apps) end here too ----
#
# Claude Code keeps running when its Remote Control session is archived or deleted elsewhere: it only writes a
# system entry to its transcript, "Remote Control disconnected — this session was ended or archived from
# another device or app (code 4090)" (or "— the server no longer reports this session — it may have been
# deleted …", same code), and goes on locally. So its controlN.pid stays live and control_number() never hands
# N out again. Every CONTROL_CLOSE_EVERY s (and before `control --new` picks a number) each live control
# session whose transcript's last word is that disconnect, with no message the person typed since (one
# typed in its terminal after it means they still use it there) and no new Remote Control session since, is
# ended: its process, controlN.pid and controlN.title. The transcript stays, resumable.

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


def end_closed_controls(force: bool = False) -> list[int]:
    """B53: end the control sessions closed online (see above). The numbers ended."""
    if not force and time.time() - CONTROL_GONE_AT[0] < CONTROL_CLOSE_EVERY:
        return []
    CONTROL_GONE_AT[0] = time.time()
    from agent_runner.control_reopen import forget_ended_controls
    forget_ended_controls()  # B121: one the person ended while the machine stays up is not reopened later
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
        except Exception as e:  # one unreadable session never stops the run loop or a new session
            log(f'control {n}: could not tell whether it was closed online: {e}')
            continue
        if end_control(n, 'its Remote Control session was closed online'):  # F118: the one close path
            out.append(n)
    return out


def free_control_number() -> int:
    """control_number() once the control sessions closed online have ended (B53), so their numbers count free."""
    end_closed_controls(force=True)
    return control_number()


def control_taken(n: int) -> bool:
    """B131: control number `n` is in use: its session is live (`control_live`), or its hidden shim's marker
    (`<notes>/control<n>.live`) names a live pid, as it does before `control N` has written its pid file."""
    up = marker_pid(C.notes(f'control{n}.live'))
    return bool(control_live(n) or (up and up != os.getpid() and plat.alive(up)))


def control_claim(n: int) -> bool:
    """B131: claim control number `n` for this `control --new` (`<notes>/control<n>.claim`, made only if it is
    not there, holding this pid), so that two asks that arrive together never both start control n. A claim
    whose process has ended is stale and is taken over. False when another live `control --new` holds it."""
    f = C.notes(f'control{n}.claim')
    for _ in range(2):
        try:
            fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            holder = marker_pid(f)
            if holder and holder != os.getpid() and plat.alive(holder):
                return False
            f.unlink(missing_ok=True)
            continue
        except OSError:
            return True  # no claim can be made here: go on as before B131
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(str(os.getpid()))
        return True
    return False


def control_unclaim(n: int) -> None:
    """B131: drop this process's claim on control number `n` (`control_claim`)."""
    f = C.notes(f'control{n}.claim')
    if marker_pid(f) == os.getpid():
        f.unlink(missing_ok=True)


def claim_control_number() -> int:
    """B131: the first free control number (`free_control_number`) that is not taken (`control_taken`) and
    that this process could claim (`control_claim`). Tested again once claimed: the claim is held until the
    session's marker is up, so one that started and let go of its claim meanwhile shows as taken."""
    n = free_control_number()
    while True:
        if not control_taken(n) and control_claim(n):
            if not control_taken(n):
                return n
            control_unclaim(n)
        n += 1


def end_control(n: int, why: str) -> bool:
    """F118: end control session `n` on purpose, as closing it does (B26, B53): its process, controlN.pid and
    controlN.title go, so it leaves the chat list and no run start reopens it (B121); the transcript stays,
    resumable. Whether it was there to end."""
    pidf = C.notes(f'control{n}.pid')
    try:
        pid_s, _, sid = pidf.read_text(encoding='utf-8').strip().partition(' ')
    except OSError:
        return False
    if control_live(n):
        try:
            plat.terminate(int(pid_s))  # its hidden shim ends with it
        except ValueError:
            pass
    from agent_runner import control_held
    control_held.drop(sid.strip())  # B170: closed on purpose, so what it held is not put in
    pidf.unlink(missing_ok=True)
    C.notes(f'control{n}.title').unlink(missing_ok=True)
    C.notes(f'control{n}.name').unlink(missing_ok=True)  # F129
    log(f'control {n}: ended, {why}' + (f' (transcript kept: {plat.exe(C.run["agent"])} --resume {sid})' if sid else ''))
    return True


def close_from_tui(n: int) -> dict:
    """F116: d on control session cN in agent-runner ui's Sessions: close it through `end_control` (its process,
    controlN.pid and controlN.title go; the transcript stays) and log 'control N: closed from the TUI'. An action result: {'ok', 'code', 'out', 'argv'}."""
    if not end_control(n, 'as agent-runner ui asked'):
        return {'ok': False, 'code': 1, 'out': f'c{n} was already closed', 'argv': []}
    log(f'control {n}: closed from the TUI')
    return {'ok': True, 'code': 0, 'out': f'c{n} closed (its transcript is kept)', 'argv': []}


def control_server_argv() -> list[str]:
    """With `[run] remote`: Claude Code's Remote Control server in the main checkout, so new control sessions can
    be started from claude.ai/code and the Claude apps, each with the control settings (its brief). F176: it
    pre-creates no session (NO_PRECREATE): Claude Code keeps that one when the server stops, and every later
    server in the same folder adopts it, so one old chat would come back in every run."""
    exe = plat.exe(C.run['agent'])
    return [exe, 'remote-control', '--spawn', 'same-dir', '--name', f'{ROOT.name} · control',
            '--permission-mode', 'bypassPermissions',
            *([NO_PRECREATE] if server_can(exe, '[no-]create-session-in-dir', NO_PRECREATE) else []),
            *(['--settings', str(control_settings())] if server_takes_settings(exe) else [])]


NO_PRECREATE = '--no-create-session-in-dir'
_SERVER_HELP: dict[str, str] = {}


def server_help(exe: str) -> str:
    """What this agent's `remote-control --help` prints (asked once a run); '' when it cannot be read."""
    if exe not in _SERVER_HELP:
        try:
            r = sp.run([exe, 'remote-control', '--help'], stdin=sp.DEVNULL, capture_output=True, text=True,
                       errors='replace', timeout=30)
            _SERVER_HELP[exe] = ((r.stdout or '') + (r.stderr or '')).strip()
        except (OSError, sp.SubprocessError):
            _SERVER_HELP[exe] = ''
    return _SERVER_HELP[exe]


def server_can(exe: str, *flags: str) -> bool:
    """Whether this agent's `remote-control` takes one of `flags` (as its help spells it): an older Claude Code
    exits at once on one it does not know, which would crash-loop the control server. An agent whose help cannot
    be read (missing, hangs, prints nothing) is taken to have it, as before."""
    said = server_help(exe)
    return not said or any(x in said for x in flags)


def server_takes_settings(exe: str) -> bool:
    """Whether this agent's `remote-control` takes `--settings` (`server_can`)."""
    return server_can(exe, '--settings')


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
            err_since = err.stat().st_size if err.exists() else 0
            env = control_env()
            if silent():  # no push after its start push (that one cannot be stopped)
                env[PRESENCE_ENV] = str(quiet_file('server'))
            with open(out, 'ab') as fh, open(err, 'ab') as eh:
                try:
                    proc = sp.Popen(control_server_argv(), cwd=str(ROOT), env=env, stdin=sp.DEVNULL,
                                    stdout=fh, stderr=eh, start_new_session=not plat.WINDOWS)
                except OSError as e:
                    quiet_file('server', on=False)
                    log(f'control: the control server did not start: {e}')
                    return
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
    if remote_on() and C.run['control']:
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
RC_RUN_KINDS = ('feed', 'server')  # what a run ends (a feed: an older version's); control sessions are the person's


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
    those an earlier run left (its control server unless `keep_server`: this run adopts it, so no new entry) and any
    runner feed (B195: an older version started it, under this run's own key when the run restarted in place);
    with `stopping`, this run's own as well. Each gets SIGTERM and up to `wait` s for its teardown,
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
        elif s.get('kind') not in RC_RUN_KINDS or s.get('run') == mine and not stopping and s.get('kind') != 'feed':
            continue  # a control session, or this run's own while it runs (a feed is never: B195)
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
            f'({"this run" if stopping else "left by an earlier run or version"}); their entries are archived')
    for s in up:
        log(f'remote: "{s["name"]}" (pid {s["pid"]}) did not end within {wait:g} s of SIGTERM; left running, '
            f'the next start ends it')
    return [s['name'] for s in gone], [s['name'] for s in up]


def rc_sweep_start() -> None:
    """The run's start: end what an earlier run left on Remote Control, and an older version's board (B195), in the
    background (it can wait)."""
    keep = remote_on() and bool(C.run['control'])

    def sweep() -> None:
        from agent_runner.feed import end_board
        rc_sweep(os.getpid(), keep_server=keep)
        end_board()
    threading.Thread(target=sweep, name='remote-sweep', daemon=True).start()
