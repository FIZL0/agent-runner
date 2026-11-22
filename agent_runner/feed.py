"""The board and the runner feed, and handing a feed message on to a new control session."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import signal
import subprocess as sp
import sys
import threading
import time
import uuid
from pathlib import Path

from agent_runner import plan as P, plat
from agent_runner.config import RUNNER, main_checkout, runner_cmd, shown_cmd
from agent_runner.state import BOARD_TAG, C, log, REPO_TAG, ROOT, RUN_TAG, run_up, TAG
from agent_runner.slots import link_drift, remote_answer_drift
from agent_runner.slots import (attach_target, background_env, background_session, MUX, remote_off_why, remote_on,
    REMOTE_URL, tmux, TmuxMux, transcript, window)
from agent_runner.land import wip_main_info
from agent_runner.control import (control_env, CONTROL_LINK_WAIT, control_live, CONTROL_N_ENV, control_name,
    control_title, feed_on, free_control_number, hidden_control, hidden_control_log, message_text, person_message, RC_ENDING, rc_forget, rc_record,
    rc_records, rc_sweep, REMOTE_DIR, SESSION_LINK)
from agent_runner.status import follow, read_events, since_text, waiting_ok


BOARD_EVERY = 30  # s between the run's checks that the board window is still there


def board_header() -> str:
    """The board's top lines: it only shows, and where to steer the run from."""
    where = (f'claude.ai/code: "{ROOT.name} · control" opens a control session' if remote_on() else
             f'{shown_cmd()} control (or a new pane in this tmux session)')
    return (f'{ROOT.name} board: what lands and what needs you, no tokens used. Steer from a control session:\n'
            f'    {where}\n' + '-' * 78)


def board(run_pid: int = 0) -> int:
    """`since --board`: the header, the last 6 hours, then the feed; the since mark is left for the person.
    With `run_pid` (the run that opened it) it ends once that process has, however the run ended."""
    print(board_header())
    now = dt.datetime.now().replace(microsecond=0)
    print(since_text(read_events(), now - dt.timedelta(hours=6), P.titles(C.done, C.todo), now, waiting=waiting_ok(),
                     wips=wip_main_info())[0], flush=True)
    return follow(mark=False, end=(lambda: not plat.alive(run_pid)) if run_pid else None)


def board_held() -> bool:
    """Does the runner feed hold its lines (B13)? While the run is idle, or paused or stopping with nothing
    running or merging, nothing more lands until the run starts something or a task is added: the feed then
    prints nothing, so its Haiku session takes no turn and pushes nothing. No run up: nothing to hold for."""
    try:
        st = json.loads(C.notes('STATE').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if not isinstance(st, dict):
        return False
    held = bool(st.get('idle') or (st.get('paused') or st.get('stopping'))
                and not st.get('running') and not st.get('merging'))
    return held and run_up()  # STATE first: the lock is only probed when STATE would hold (a stale one, too)


BOARD_POLL = 2.0  # s between the board guard's looks at the run
BOARD_TERM = 10  # s the feed gets to end on SIGTERM before it is killed


def board_feed(run_pid: int = 0, poll: float = BOARD_POLL) -> int:
    """`since --board --feed`: the runner feed (`feed_argv`) as a child, ended once the run that opened it
    (`run_pid`) has: a plain stop once its tasks are done, a force stop, or a crash. The feed then goes
    offline in the apps and the board window closes. The feed ending on its own ends this too (`keep_board`
    opens it again while the run is up). Ctrl-C is the feed's own (it asks before it exits)."""
    sid, resume = feed_session(feed_cmd()) if run_pid else ('', False)  # B15: the run's feed carries on its one session
    try:
        proc = sp.Popen([*feed_argv(), *feed_session_args(sid, resume)])
    except OSError as e:
        print(f'board: could not start the runner feed: {e}', file=sys.stderr)
        return 1
    t0 = time.monotonic()
    # B12: one by hand is not the run's
    rec = rc_record('feed', feed_name(), proc.pid, run_pid, sid) if run_pid else None
    killed = False
    try:
        old = signal.signal(signal.SIGINT, signal.SIG_IGN)  # after the spawn: the child keeps its own Ctrl-C
    except ValueError:  # not the main thread (tests)
        old = None
    try:
        while True:
            try:
                rc = proc.wait(timeout=poll)
                if resume and rc and time.monotonic() - t0 < FEED_RESUME_FAIL:
                    feed_forget_session()  # its transcript is gone, say: the next start is a fresh session
                    print(f'board: the runner feed could not resume session {sid} (exit {rc}); the next start '
                          f'opens a new one', file=sys.stderr)
                return rc
            except sp.TimeoutExpired:
                pass
            if run_pid and not plat.alive(run_pid):
                proc.terminate()
                try:
                    proc.wait(timeout=BOARD_TERM)
                except sp.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    killed = True
                return 0
    finally:
        rc_forget(rec, killed=killed)
        if old is not None:
            signal.signal(signal.SIGINT, old)


FEED_SID = 'feed.sid'  # <notes>/remote/feed.sid: the runner feed's Claude session id, kept until a real stop
FEED_RESUME_FAIL = 15  # s: a resumed feed failing sooner than this could not resume; the next start is fresh
SID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def feed_session(cmd: str = '') -> tuple[str, bool]:
    """(session id, resume) for the run's runner feed (B15). The id is kept in <notes>/remote/ from the feed's
    first start until a real stop (`rc_sweep_stop`), so any restart that is not one (an upgrade's, a board
    window replaced or closed, the feed exiting, a crashed run started again) resumes the same Claude session:
    its history and its app entry carry on. None kept yet: a new id, recorded, and a fresh session.
    B91: the runner command the feed may run (`cmd`, default RUNNER) is kept on the line after the id; a kept
    session whose command differs (or that names none: one from before B91, which may still say only
    `./kit` is allowed, from before B71) is not resumed, so the feed's history never contradicts its rules."""
    cmd = cmd or RUNNER
    f = C.notes(REMOTE_DIR, FEED_SID)
    sid, kept = feed_sid_parts()
    if SID_RE.fullmatch(sid) and kept == cmd:
        return sid, True
    sid = str(uuid.uuid4())
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f'{sid}\n{cmd}\n', encoding='utf-8')
    except OSError:
        pass
    return sid, False


def feed_sid_parts() -> tuple[str, str]:
    """(session id, runner command) as <notes>/remote/feed.sid holds them (B91); '' for either one missing."""
    try:
        lines = C.notes(REMOTE_DIR, FEED_SID).read_text(encoding='utf-8').splitlines()
    except OSError:
        return '', ''
    lines = [ln.strip() for ln in lines] + ['', '']
    return lines[0], lines[1]


def feed_session_args(sid: str, resume: bool) -> list[str]:
    """The agent flags that start the feed's session `sid`, or resume it."""
    return ['--resume', sid] if resume and sid else ['--session-id', sid] if sid else []


def feed_forget_session() -> None:
    """A real stop (or a resume that failed): the next feed starts a fresh session."""
    C.notes(REMOTE_DIR, FEED_SID).unlink(missing_ok=True)


def board_argv(sess: str, root: Path, cmd: str) -> list[str]:
    """Open the board window in the background session `sess`, without taking focus."""
    return ['tmux', 'new-window', '-d', '-t', f'={sess}:', '-n', window('board'), '-c', str(root),
            '-P', '-F', '#{pane_id}', cmd]


FEED_MODEL = 'haiku'  # ponytail: fixed; the feed only echoes lines and runs one command, a knob if that ever falls short


def feed_name() -> str:
    return f'{ROOT.name} · runner'


def feed_cmd() -> str:
    """B92: the command the runner feed's prompt names: `[run] command` (e.g. openmx's `./kit`, which forwards
    every runner command once it has loaded the kit's settings), else the runner. The run's own output and hints
    say that command, so the feed copies it; the bare runner in a wrapped repo would skip the kit's config."""
    return C.command


def feed_allowed_bash() -> list[str]:
    """B92: the Bash rules the feed's dontAsk allows: `[run] command` and the runner itself when they differ,
    so neither one a line or hint names is refused."""
    return list(dict.fromkeys(f'Bash({c} *)' for c in (feed_cmd(), RUNNER)))


def feed_argv() -> list[str]:
    """With `[run] remote`: the runner feed, a lean Claude session on Remote Control as "<repo> · runner" that
    posts what lands (Monitor on `since --follow --keep-mark`), runs status/pause/stop/slots, and hands anything
    else to a new control session; the one watch that pushes what needs the person (PushNotification), so
    control sessions start none. Haiku; Bash (only the runner's command, dontAsk refuses the rest), Monitor;
    its own short system prompt instead of Claude Code's, no settings sources or MCP servers: ~6k tokens a turn.
    `board_feed` adds the session flags: one session from the run's first start to a real stop (`feed_session`)."""
    from agent_runner.guide import FEED_ANSWER, RUNNER_BRIEF, RUNNER_START
    cmd = feed_cmd()
    cf = P.needs_cfg()  # B27: a reply to an item under Needs you is mapped to its id and answered here
    answer = FEED_ANSWER.format(cmd=cmd, needs=cf['heading'])
    from agent_runner import voice  # F21: the person's wording, in the prompt: the feed has no file tools
    system = voice.feed(RUNNER_BRIEF.format(cmd=cmd, repo=ROOT.name, answer=answer), C)
    return [plat.exe(C.run['agent']), RUNNER_START.format(cmd=cmd, repo=ROOT.name),
            '--model', FEED_MODEL, '--system-prompt', system,
            '--tools', 'Bash,Monitor,PushNotification', '--permission-mode', 'dontAsk',
            '--allowedTools', *feed_allowed_bash(), 'Monitor', 'PushNotification', '--strict-mcp-config',
            '--setting-sources', '', '--settings', json.dumps({'autoMemoryEnabled': False}),  # ~6k tokens a turn
            '--remote-control', feed_name()]


def board_command() -> str:
    """What the board window runs: the runner feed with `[run] remote` (in the apps too), else the free text feed;
    either one ends once this run's process has (B13)."""
    return plat.command_text([*runner_cmd(), 'since', '--board', *(['--feed'] if feed_on() else []),
                              '--run-pid', str(os.getpid())])


def keep_board(sess: str) -> None:
    """Keep the board window up in the background session while the run is: opened again when it is closed or
    its feed exits. It ends with the run (its `--run-pid`), and the next run opens its own."""
    cmd = board_command()
    kind = ('feed' if ' --feed' in cmd else 'text') + '/run'
    said = False
    while True:
        rows = tmux('list-panes', '-s', '-t', f'={sess}', '-F',
                    f'#{{session_name}}\t#{{pane_id}}\t#{{{TAG}}}\t#{{{REPO_TAG}}}\t#{{{RUN_TAG}}}')
        hit = attach_target(rows.stdout.splitlines(), ROOT, 'board') if rows.returncode == 0 else ('', '')
        if hit and hit[1] and tmux('show-options', '-p', '-v', '-t', hit[1], BOARD_TAG).stdout.strip() != kind:
            tmux('kill-pane', '-t', hit[1])  # an earlier run's other kind (remote turned on or off): this run's instead
            hit = None
        if not hit and not RC_ENDING[0]:  # found by tag, not name: a rename keeps it; none once the run ends
            r = sp.run(board_argv(sess, ROOT, cmd), capture_output=True, text=True)
            if pane := r.stdout.strip():  # `attach board` finds it by these
                tmux('set-option', '-p', '-t', pane, TAG, 'board')
                tmux('set-option', '-p', '-t', pane, REPO_TAG, str(ROOT))
                tmux('set-option', '-p', '-t', pane, BOARD_TAG, kind)
            if not said or r.returncode:
                what = f'the runner feed, "{feed_name()}" in the apps too' if kind.startswith('feed') else 'the text feed'
                log(f'board: window {window("board")} is up with {what} ({shown_cmd()} attach board)' if not r.returncode
                    else f'board: tmux could not open it: {r.stderr.strip()}')
            said = True
        time.sleep(BOARD_EVERY)


def start_board() -> None:
    """The board window, in the tmux session the run is in (the background one, or yours): with `[run] remote`
    it is the runner feed, which must be there however the run was started."""
    here = os.environ.get('TMUX_PANE', '')
    if not (isinstance(MUX, TmuxMux) and here):
        return
    if sess := tmux('display-message', '-p', '-t', here, '#{session_name}').stdout.strip():
        threading.Thread(target=keep_board, args=(sess,), name='board', daemon=True).start()


def control_new_session() -> str:
    """The tmux session `control --new` opens its window in: the one this pane is in (a control session beside
    the run), else the run's background session while it is up; '' when there is none."""
    if here := os.environ.get('TMUX_PANE', ''):
        r = tmux('display-message', '-p', '-t', here, '#{session_name}')
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    sess = background_session()
    return sess if tmux('has-session', '-t', f'={sess}').returncode == 0 else ''


def feed_files() -> list[str]:
    return feed_scan()[0]


def feed_scan() -> tuple[list[str], int, str]:
    """(`feed_files`, images the message shows that no saved path came for, its Claude Code version). The middle
    one is the drift check: when Claude Code changes how it records an image's path again, the new control
    session is told so (`image_drift_note`) instead of the pictures vanishing without a word.

    The files and images attached to the person's latest message in the runner feed, the one being handed on, in
    display order: Claude Code records their saved paths in the feed's transcript (an `inlined_image_paths`
    attachment after the message, since 2.1.329 an isMeta entry with '[Image: source: PATH]' text, B24, and for any
    other file, saved to ~/.claude/uploads/<sid>/<id>-<name> and @-mentioned, an attachment of type file with that
    path as filename, B30). `control --new --ask` passes them on itself, so a feed on an older brief, or a Haiku
    that drops or mangles the @-mention, still forwards them, and a later text-only message forwards none. File
    attachments after a compaction summary are Claude Code re-reading files, not the person attaching them, so
    they are left out. The session is the one running this command (Claude Code's CLAUDE_CODE_SESSION_ID: the
    feed handing the message on), else <notes>/remote/feed.sid (a feed started by an older runner never wrote that
    file, B22)."""
    return feed_latest()[:3]


def feed_sid() -> str:
    """The feed session handing a message on: the one running this command (CLAUDE_CODE_SESSION_ID), else
    <notes>/remote/feed.sid, else the live feed's own session (`feed_record_sid`, B83); '' when none names one."""
    sid = os.environ.get('CLAUDE_CODE_SESSION_ID', '').strip()
    if not SID_RE.fullmatch(sid):
        sid = feed_sid_file()
    if not SID_RE.fullmatch(sid):
        sid = feed_record_sid()
    return sid if SID_RE.fullmatch(sid) else ''


def feed_sid_file() -> str:
    """The session id <notes>/remote/feed.sid holds (its first line, B91), stripped; '' without one."""
    return feed_sid_parts()[0]


def claude_sessions_dir() -> Path:
    """Where Claude Code keeps one <pid>.json per live session, its sessionId among the fields."""
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'sessions'


def feed_record_sid() -> str:
    """The session id of the live runner feed (B83): its Remote Control record's sid, else the sessionId Claude Code
    wrote for its pid (`claude_sessions_dir`). A feed started by a runner from before B15 has no feed.sid and no
    sid in its record, and a Bash call of its own may not carry CLAUDE_CODE_SESSION_ID, so a hand-off from it read
    no transcript and dropped the person's pictures. '' when no live feed is recorded or none names its session."""
    for rec in rc_records():
        if rec.get('kind') != 'feed' or not isinstance(rec.get('pid'), int) or not plat.alive(rec['pid']):
            continue
        if SID_RE.fullmatch(str(rec.get('sid') or '')):
            return rec['sid']
        try:
            d = json.loads((claude_sessions_dir() / f'{rec["pid"]}.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or (rec.get('start') and d.get('procStart')
                                       and str(d['procStart']) != str(rec['start'])):
            continue  # another process now has that pid
        if SID_RE.fullmatch(str(d.get('sessionId') or '')):
            return d['sessionId']
    return ''


def queued_message(d: dict) -> dict | None:
    """B106: a message the person sent while the feed was busy (handling a Monitor event, a command), as Claude
    Code records it: no type=user entry but an attachment {type: queued_command, prompt: <text or content
    blocks, images too>, commandMode: prompt}. Given back in a type=user entry's shape, so the feed's readers
    take it like any other person message, in transcript order; None for any other entry, and for a queued
    task notification (commandMode task-notification) or one not from the person."""
    att = d.get('attachment') if isinstance(d, dict) else None
    if not isinstance(att, dict) or att.get('type') != 'queued_command':
        return None
    if att.get('commandMode', 'prompt') != 'prompt':
        return None
    prompt = att.get('prompt')
    if not isinstance(prompt, (str, list)):
        return None
    out = {'type': 'user', 'uuid': d.get('uuid') or att.get('source_uuid'),
           'timestamp': d.get('timestamp') or att.get('timestamp'), 'version': d.get('version'),
           'origin': att.get('origin') or d.get('origin') or {'kind': 'human'}, 'message': {'content': prompt}}
    return out if person_message(out) else None


def feed_latest(sid: str | None = None) -> tuple[list[str], int, str, str | None]:
    """`feed_scan`, plus the text of that latest person message (None: no feed transcript to read), so
    `control_new` can tell whether Claude Code has written the message being handed on yet (B46). `sid`: the
    feed session to read (default `feed_sid`)."""
    sid = feed_sid() if sid is None else sid
    FEED_LOOK.clear()
    FEED_LOOK.update(sid=sid, transcript=None, lines=0, shown=0)
    if not sid:
        return [], 0, '', None
    t = transcript(sid) if SID_RE.fullmatch(sid) else None
    FEED_LOOK['transcript'] = t
    if not t:
        return [], 0, '', None
    paths: list[str] = []
    rereads = False
    shown = found = 0  # images in the latest message; image paths recorded for it (B24's two forms count twice)
    version = said = ''
    try:
        with open(t, encoding='utf-8') as f:
            for line in f:
                FEED_LOOK['lines'] += 1
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                d = queued_message(d) or d  # B106: a message sent while the feed was busy
                att = d.get('attachment') or {}
                if att.get('type') == 'inlined_image_paths':
                    got = [p for p in att.get('paths', []) if isinstance(p, str)]
                    found += len(got)
                    paths += [p for p in got if p not in paths]
                elif att.get('type') == 'file':
                    p = att.get('filename')
                    if not rereads and isinstance(p, str) and p and p not in paths:
                        paths.append(p)
                elif d.get('type') == 'user' and d.get('isCompactSummary'):
                    rereads = True
                elif d.get('type') == 'user' and d.get('isMeta'):
                    got = meta_image_paths(d)
                    found += len(got)
                    paths += [p for p in got if p not in paths]
                elif d.get('type') == 'user' and person_message(d):
                    paths, rereads, found = [], False, 0
                    c = (d.get('message') or {}).get('content')
                    shown = sum(isinstance(x, dict) and x.get('type') == 'image' for x in c) if isinstance(c, list) else 0
                    pasted = d.get('imagePasteIds')  # B74: the images Claude Code says came with it, block or not
                    shown = max(shown, len(pasted) if isinstance(pasted, list) else 0)
                    version = str(d.get('version') or '')
                    said = c if isinstance(c, str) else ' '.join(
                        x.get('text', '') for x in c if isinstance(x, dict) and x.get('type') == 'text') \
                        if isinstance(c, list) else ''
    except OSError:
        return [], 0, '', None
    FEED_LOOK.update(shown=shown, said=said)
    return paths, max(shown - found, 0), version, said


FEED_LOOK: dict = {}  # what the last `feed_latest` read: sid, transcript, lines, shown, said (B74's hand-off log)
FEED_WAIT = 5.0  # s control --new --ask waits for the feed's transcript to hold the message it hands on (B46)
FEED_LATE_WAIT = 60.0  # s the new `control N` then keeps waiting for it before starting claude (B57)
FEED_LOG = 'handoff.log'  # <notes>/remote/handoff.log: what feed_wait saw at each hand-off (B74)


def feed_wait(ask: str, wait: float, sid: str | None = None,
              where: str = 'control --new') -> tuple[bool, list[str], int, str]:
    """Wait up to `wait` s for the feed transcript (`sid`, default `feed_sid`) to hold the message `ask` hands on
    with every image's saved path: (found it, its files, images with no path, Claude Code version). With no feed
    session at all, found is True: there is nothing to wait for (a typed --ask). A feed session whose transcript
    cannot be found or read yet is waited for like a message not written yet, never taken as found with no
    files (B74). What it saw is logged (`feed_log`), `where` naming the step."""
    t0 = time.monotonic()
    sid = feed_sid() if sid is None else sid
    looks = 0
    while True:
        got, lost, version, said = feed_latest(sid)
        looks += 1
        if said is None and not sid:
            out = True, [], 0, ''
            break
        match = said is not None and same_words(said, ask)
        if (match and not lost) or time.monotonic() - t0 >= wait:
            out = match, (got if match else []), (lost if match else 0), version
            break
        time.sleep(0.2)
    feed_log(where, sid, ask, time.monotonic() - t0, looks, out)
    return out


def feed_log(where: str, sid: str, ask: str, took: float, looks: int, out: tuple) -> None:
    """One line in <notes>/remote/handoff.log for a hand-off: the feed session and where its id came from, the
    transcript and how much of it was read, the latest person message there and its images, and what was
    handed on, so a picture that went missing can be traced (B74). Never fails the hand-off."""
    found, got, lost, version = out
    look = FEED_LOOK
    src = ('none' if not sid else '--feed-sid' if '--feed-sid' in where
           else 'env' if os.environ.get('CLAUDE_CODE_SESSION_ID', '').strip() == sid
           else 'feed.sid' if feed_sid_file() == sid else 'feed record')
    said = look.get('said')
    head = lambda s: json.dumps(re.sub(r'\s+', ' ', s)[:60], ensure_ascii=False)
    line = (f'{dt.datetime.now().isoformat(timespec="seconds")} {where}: ask {head(ask)}; sid {sid or "-"} ({src}),'
            f' transcript {look.get("transcript") or "none"} ({look.get("lines", 0)} lines); latest '
            f'{head(said) if isinstance(said, str) else "none"} with {look.get("shown", 0)} image(s); '
            f'{looks} look(s) in {took:.1f} s -> {"found" if found else "NOT found"}, {len(got)} file(s)'
            f'{" " + " ".join(got) if got else ""}, {lost} lost, Claude Code {version or "?"}')
    try:
        with open(C.notes(REMOTE_DIR, FEED_LOG), 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def feed_unread_note() -> str:
    """Added to a handed-on ask when the feed transcript never showed the message (B57)."""
    return ('The person may have attached images or files to this message, but agent-runner could not read them '
            "from the runner feed's transcript in time. If the message refers to a picture or file you don't "
            'have, ask them to send it here again.')


def control_late_files(ask: str, images: list[str], sid: str, wait: float | None = None) -> tuple[str, list[str]]:
    """`control N --ask … --feed-sid SID` (B57): the feed's transcript did not hold the message being handed on
    when `control --new` started this session, so wait here (FEED_LATE_WAIT) for it before claude starts. The
    ask and files to start with: its files added, or a note that attachments may have been lost."""
    found, got, lost, version = feed_wait(ask, FEED_LATE_WAIT if wait is None else wait, sid, 'control N --feed-sid')
    images = [*images, *(i for i in got if i not in images)]
    if not found:
        return f'{ask}\n\n{feed_unread_note()}', images
    if note := image_drift_note(lost, version):
        ask = f'{ask}\n\n{note}'
    return ask, images


def same_words(said: str, ask: str) -> bool:
    """The feed hands the person's message on word for word, give or take quoting and spacing: compare letters
    and digits only, either one holding the other. A short one must be all of it (B74): an earlier "openmx" is not
    the new "openmx is failing again", whose pictures may not be written yet."""
    a, b = (re.sub(r'\W+', '', x).lower() for x in (said, ask))
    short, long_ = sorted((a, b), key=len)
    return bool(a and b) and short in long_ and (short == long_ or len(short) >= SAME_WORDS_MIN)


SAME_WORDS_MIN = 16  # letters: a message shorter than this matches only in full (B74)


def image_drift_note(lost: int, version: str) -> str:
    """Added to a handed-on ask when `lost` attached images came with no saved path (`feed_scan`)."""
    if not lost:
        return ''
    return (f'The person attached {lost} image(s) that could not be passed on: Claude Code '
            f'{version or "(this version)"} no longer records where it saves them in a way agent-runner reads. '
            'Ask them to send the picture(s) here again, and tell them agent-runner needs a fix for this '
            "Claude Code change (its runner feed reads the saved paths from the feed's transcript).")


# --- B72: the feed hands a message on with `control --new --forward`, no text of the person's in a shell -------
#
# A long pasted message (quotes, backticks, $(...), newlines) retyped as `--ask "<words>"` by the feed's model
# made a broken shell command. So the feed runs a fixed command, and the message is read here, word for word,
# from the feed's own transcript: its latest person message, the one the feed is answering.

FEED_FORWARDED = 'feed.forwarded'  # <notes>/remote/feed.forwarded: "<sid> <uuid>" of the message last handed on
FORWARD_FLAG = '--forward'


def feed_pending(sid: str) -> tuple[str, str, bool] | None:
    """The feed's latest person message: (its text word for word, its id, ready). None when the transcript holds
    none. Ready means it is the message the feed is answering now: it is not the one last handed on
    (FEED_FORWARDED), and nothing the feed did after it is a tool call other than `control … --forward`, so a
    transcript that has not caught up yet (B46) does not hand on the previous message, which the feed answered
    with a command of its own (status, pause, …)."""
    t = transcript(sid) if SID_RE.fullmatch(sid or '') else None
    if not t:
        return None
    text = mid = None
    other = False
    try:
        with open(t, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                d = queued_message(d) or d  # B106: a message sent while the feed was busy
                if d.get('type') == 'user' and not d.get('isMeta') and not d.get('isCompactSummary') \
                        and person_message(d):
                    text, mid, other = message_text(d), str(d.get('uuid') or d.get('timestamp') or ''), False
                elif d.get('type') == 'assistant' and text is not None:
                    c = (d.get('message') or {}).get('content')
                    for x in c if isinstance(c, list) else []:
                        if isinstance(x, dict) and x.get('type') == 'tool_use' and x.get('name') == 'Bash':
                            cmd = str((x.get('input') or {}).get('command', ''))
                            if not ('control' in cmd and FORWARD_FLAG in cmd) and ' since' not in cmd:
                                other = True  # a run command of its own (status, pause…); not a Monitor re-arm
    except OSError:
        return None
    if text is None:
        return None
    try:
        last = C.notes(REMOTE_DIR, FEED_FORWARDED).read_text(encoding='utf-8').split()
    except OSError:
        last = []
    done = bool(mid) and last == [sid, mid]
    return text, mid, not done and not other


def feed_forwarded(sid: str, mid: str) -> None:
    """Mark message `mid` of feed `sid` handed on, so a second `--forward` before the next one waits."""
    if not mid:
        return
    try:
        f = C.notes(REMOTE_DIR, FEED_FORWARDED)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f'{sid} {mid}\n', encoding='utf-8')
    except OSError:
        pass


def feed_take(sid: str, wait: float) -> str | None:
    """Wait up to `wait` s for the feed's message being handed on (`feed_pending` ready) and take it: its text,
    marked handed on. None when it did not show: never a guess at an older message."""
    t0 = time.monotonic()
    deadline = t0 + wait
    FEED_TAKE.clear()
    FEED_TAKE.update(looks=0, latest=None)
    while True:
        got = feed_pending(sid)
        FEED_TAKE['looks'] += 1
        FEED_TAKE.update(latest=got, took=time.monotonic() - t0)
        if got and got[2]:
            feed_forwarded(sid, got[1])
            return got[0]
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.2)


FEED_TAKE: dict = {}  # what the last `feed_take` saw: looks, took (s), latest (`feed_pending`), for its log line


def feed_take_log(where: str, sid: str, out: tuple[str, list[str], bool] | None) -> None:
    """B106: one line in <notes>/remote/handoff.log for a `--forward` take (`feed_take_files`), as `feed_log`
    writes for `feed_wait`: the feed session, its transcript, the latest person message there (its words, id,
    and whether it was ready to hand on), and what was taken, so a message that went missing can be traced.
    Never fails the hand-off."""
    head = lambda s: json.dumps(re.sub(r'\s+', ' ', s)[:60], ensure_ascii=False)
    latest = FEED_TAKE.get('latest')
    seen = (f'{head(latest[0])} ({latest[1] or "no id"}, {"ready" if latest[2] else "not ready"})'
            if latest else 'none')
    took = ('NOT found' if out is None else
            f'found {head(out[0])}, {len(out[1])} file(s){" " + " ".join(out[1]) if out[1] else ""}'
            f'{", alone" if out[2] else ""}')
    line = (f'{dt.datetime.now().isoformat(timespec="seconds")} {where}: sid {sid or "-"}, transcript '
            f'{(transcript(sid) if SID_RE.fullmatch(sid or "") else None) or "none"}; latest {seen}; '
            f'{FEED_TAKE.get("looks", 0)} look(s) in {FEED_TAKE.get("took", 0.0):.1f} s -> {took}')
    try:
        log_file = C.notes(REMOTE_DIR, FEED_LOG)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except (Exception, SystemExit):  # no notes folder to find (C.notes ends on a git that names none): no line
        pass


def feed_photo(sid: str, wait: float) -> tuple[list[str], int, str]:
    """BUG1: the files of the feed's latest person message when it has no words (a photo or file sent alone):
    (their saved paths, images shown with no path, Claude Code version), waited for up to `wait` s until every
    image's path is recorded. `feed_wait` cannot find such a message: it matches the words, and there are none."""
    deadline = time.monotonic() + wait
    while True:
        got, lost, version, said = feed_latest(sid)
        alone = said is not None and not said.strip()
        if (alone and got and not lost) or time.monotonic() >= deadline:
            return (got, lost, version) if alone else ([], 0, version)
        time.sleep(0.2)


def feed_photo_unsent(sid: str) -> str | None:
    """BUG1: the id of the feed's latest person message when it is a photo with no words that was not handed on
    yet, though `feed_pending` does not call it ready (the feed ran a command of its own about it first); else None."""
    got = feed_pending(sid)
    if not got or got[0].strip() or not got[1]:
        return None
    try:
        last = C.notes(REMOTE_DIR, FEED_FORWARDED).read_text(encoding='utf-8').split()
    except OSError:
        last = []
    return None if last == [sid, got[1]] else got[1]


def feed_take_files(sid: str, wait: float, photo_wait: float | None = None, final: bool = True,
                    where: str = 'control --new --forward') -> tuple[str, list[str], bool] | None:
    """`feed_take_files_now`, its outcome logged to handoff.log (`feed_take_log`, B106), `where` naming the step."""
    FEED_TAKE.clear()
    out = feed_take_files_now(sid, wait, photo_wait, final)
    feed_take_log(where, sid, out)
    return out


def feed_take_files_now(sid: str, wait: float, photo_wait: float | None = None,
                        final: bool = True) -> tuple[str, list[str], bool] | None:
    """BUG1: `feed_take`, and for a message with no words its files: (text, files, alone). A message with words
    gives its text, no files (`feed_wait` finds those by its words) and False; a photo alone gives '', its saved
    paths (`feed_photo`) and True, and when no path shows, the note that says so (`image_drift_note`, else
    `feed_lost_note`) as its text. A photo is taken even when the feed ran a command about it first
    (`feed_photo_unsent`). None when no message shows at all, and, not `final`, also for a photo whose paths did
    not show in `photo_wait` s (default FEED_WAIT): it is left not handed on, for a later, longer wait."""
    f = None if final else C.notes(REMOTE_DIR, FEED_FORWARDED)
    try:
        before = f.read_text(encoding='utf-8') if f else None
    except OSError:
        before = None
    text = feed_take(sid, wait)
    if text is None and (mid := feed_photo_unsent(sid)):
        feed_forwarded(sid, mid)
        text = ''
    if text is None or text.strip():
        return None if text is None else (text, [], False)
    got, lost, version = feed_photo(sid, FEED_WAIT if photo_wait is None else photo_wait)
    if got:
        return '', got, True
    if not final:
        try:  # not handed on after all: the later wait takes it
            f.write_text(before, encoding='utf-8') if before is not None else f.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return image_drift_note(lost, version) or feed_lost_note(), [], True


def feed_lost_note() -> str:
    """The first message of a session `--forward` opened when the feed's message could not be read at all."""
    return ('The runner feed handed a message on to this session, but agent-runner could not read it from the '
            "feed's transcript. Ask the person to send it here again.")


def forward_ask_file(n: int, text: str) -> Path:
    """Where `control --new --forward` leaves the message for `control N --ask-file` (read and removed there):
    a file, so the text never passes through a shell or tmux command line."""
    f = C.notes(f'control{n}.ask')
    f.write_text(text, encoding='utf-8')
    return f


def forward_late(n: int, sid: str, wait: float | None = None) -> str:
    """`control N --forward --feed-sid SID` (B72): the feed's message was not in its transcript when `control
    --new --forward` ran, so wait here (FEED_LATE_WAIT) before claude starts, holding number N. The message, or,
    when no message shows at all, a first message saying it could not be read."""
    return forward_late_files(n, sid, wait)[0]


def forward_late_files(n: int, sid: str, wait: float | None = None) -> tuple[str, list[str], bool]:
    """`forward_late` with the files of a photo sent alone (BUG1): (the message or a note, its files, done: no
    files left to wait for, as for a photo alone or a message that never showed)."""
    print('waiting for the runner feed to record the message…', flush=True)
    try:
        C.notes(f'control{n}.pid').write_text(f'{os.getpid()}', encoding='utf-8')
    except OSError:
        pass
    late = FEED_LATE_WAIT if wait is None else wait
    got = feed_take_files(sid, late, photo_wait=late, where='control N --forward --feed-sid')
    return (feed_lost_note(), [], True) if got is None else got


def read_ask_file(path: str) -> str:
    """`control N --ask-file PATH`: the handed-on message, the file removed once read."""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except OSError:
        return ''
    try:
        Path(path).unlink()
    except OSError:
        pass
    return text







IMAGE_SOURCE_RE = re.compile(r'\[Image: source: ([^\]\n]+?)\]')


def meta_image_paths(d: dict) -> list[str]:
    """The image paths in a Claude Code isMeta companion entry: 2.1.329 records a phone/remote image as
    '[Image: source: /tmp/claude-<uid>/<proj>/<sid>/images/1.png]' text, with no inlined_image_paths attachment (B24)."""
    c = (d.get('message') or {}).get('content')
    texts = [c] if isinstance(c, str) else [x.get('text', '') for x in c or [] if isinstance(x, dict)] \
        if isinstance(c, list) else []
    return [m.strip() for t in texts if isinstance(t, str) for m in IMAGE_SOURCE_RE.findall(t)]


def control_new(n: int | None = None, wait: float = CONTROL_LINK_WAIT, ask: str = '',
                images: list[str] | tuple = (), forward: bool = False, handed: bool = False) -> int:
    """`control --new`: another control session, opened without taking focus (a window of its own in the run's
    tmux session; Windows: a hidden console), on Remote Control as "<repo> · control N" with `[run] remote`.
    Prints its claude.ai/code link once its pane shows it, so the session that ran it can answer with a link.
    `forward` (`control --new --forward`, B72): its first message is the runner feed's latest person message,
    read word for word from the feed's transcript (`feed_take`) and handed to `control N` in a file, never on a
    command line; when it has not reached the transcript in FEED_WAIT s, `control N --forward --feed-sid` waits
    for it itself."""
    n = n or free_control_number()
    if pid := control_live(n):
        print(f'control {n} already runs (pid {pid})', file=sys.stderr)
        return 1
    images = [str(Path(i).resolve()) for i in images]
    late = ''
    fwd: list[str] = []
    alone = False  # BUG1: a photo sent alone, its files (or a note that they could not be read) already taken
    if forward:
        sid = feed_sid()
        took = feed_take_files(sid, FEED_WAIT, final=not transcript(sid)) if sid else None
        text = None if took is None else took[0]
        if took:
            images += [i for i in took[1] if i not in images]
            alone = took[2]
        if text is None and sid and transcript(sid):
            fwd, ask = [FORWARD_FLAG, '--feed-sid', sid], ''
        else:
            ask = feed_lost_note() if text is None else text
    if ask and ask != feed_lost_note() and not handed and not alone:  # B54 handed: another feed read it already
        # Claude Code writes the feed's transcript lazily: the message being handed on, and the saved paths of
        # its pictures, can land a while after this command starts (B46, B57: more than FEED_WAIT), so wait
        # briefly for them here, and when they are still missing let the new session's own process wait longer
        # (--feed-sid) instead of taking the previous message's files.
        sid = feed_sid()
        found, got, lost, version = feed_wait(ask, FEED_WAIT, sid,
                                              'control --new --forward' if forward else 'control --new')
        images += [i for i in got if i not in images]
        if not found:
            late = sid
        elif note := image_drift_note(lost, version):
            ask = f'{ask}\n\n{note}'
    if (forward or handed) and ask:
        given = ['--ask-file', str(forward_ask_file(n, ask))]
    else:
        given = ['--ask', ask] if ask else []
    cmd = [*runner_cmd(), 'control', str(n), *given, *fwd,
           *[x for i in images for x in ('--file', i)], *(['--feed-sid', late] if late else [])]
    name = control_name(n, ask, images)
    if plat.WINDOWS:
        plat.spawn_console(cmd, ROOT, control_env(), hidden=True)
        print(f'control {n} is up in a hidden console' +
              (f': "{name}" at {REMOTE_URL}' if remote_on() else f' ({shown_cmd()} attach c{n} shows it)'))
        return 0
    if not shutil.which('tmux') or not (sess := control_new_session()):
        return control_new_hidden(n, cmd, name, wait)  # F59: no tmux session to open a window in
    env = [e for e in background_env() if not e.startswith(('AGENT_RUNNER=', 'AGENT_RUNNER_SLOT=', 'AGENT_RUNNER_KEEP='))]
    envs = [x for e in env for x in ('-e', e)]
    win = name if control_title(ask, images) else window(f'control{n}')
    r = tmux('new-window', '-d', '-t', f'={sess}:', '-n', win, '-c', str(ROOT), *envs, '-P', '-F', '#{pane_id}',
             plat.command_text(cmd))
    if r.returncode or not (pane := r.stdout.strip()):
        print(f'tmux could not open control {n}: {r.stderr.strip()}', file=sys.stderr)
        return 1
    tmux('set-option', '-p', '-t', pane, TAG, f'c{n}')
    tmux('set-option', '-p', '-t', pane, REPO_TAG, str(ROOT))
    where = f'window {win} of tmux session {sess} ({shown_cmd()} attach c{n} goes there)'
    if not remote_on():
        why = remote_off_why() if C.run['remote'] == 'auto' else ''
        print(f'control {n} is up in {where}; it is local' +
              (f' ({why})' if why else ': [run] remote = true puts control sessions on claude.ai/code'))
        return 0
    deadline = time.monotonic() + wait
    while True:
        shown = tmux('capture-pane', '-p', '-J', '-t', pane, '-S', '-200')
        if m := SESSION_LINK.search(shown.stdout or ''):
            print(f'control {n} is up: {m.group(0)}\n("{name}", in {where})')
            remote_answer_drift(f'control {n}')  # B45: it came up on Remote Control, so the answer is kept
            return 0
        if shown.returncode or time.monotonic() >= deadline:
            break
        time.sleep(1)
    if not shown.returncode:  # B45: the pane is still open, Remote Control on, and no link in all that time
        link_drift(f'control {n}', wait)
    print(f'control {n} is up in {where}, but showed no link in {wait:g} s: find "{name}" at {REMOTE_URL}')
    return 0


def control_new_hidden(n: int, cmd: list[str], name: str, wait: float = CONTROL_LINK_WAIT) -> int:
    """F59: `control --new` on Linux and macOS with no tmux session to open a window in (a hidden run, or no
    tmux): control session `n` in a pseudo-terminal with no window (`hidden_control`). With `[run] remote` it
    prints its claude.ai/code link once its log shows it, as a window's pane would."""
    out = hidden_control_log(n)
    since = out.stat().st_size if out.exists() else 0
    pid, why = hidden_control(n, cmd)
    if not pid:
        print(f'control {n} could not start hidden: {why}', file=sys.stderr)
        return 1
    where = f'a hidden terminal, its output in {out}'
    if not remote_on():
        why = remote_off_why() if C.run['remote'] == 'auto' else ''
        print(f'control {n} is up in {where}; it is local' +
              (f' ({why})' if why else ': [run] remote = true puts control sessions on claude.ai/code'))
        return 0
    deadline = time.monotonic() + wait
    while True:
        try:
            with open(out, 'rb') as fh:
                fh.seek(since)
                shown = fh.read().decode('utf-8', 'replace')
        except OSError:
            shown = ''
        if m := SESSION_LINK.search(shown):
            print(f'control {n} is up: {m.group(0)}\n("{name}", in {where})')
            remote_answer_drift(f'control {n}')  # B45: it came up on Remote Control, so the answer is kept
            return 0
        if not plat.alive(pid) or time.monotonic() >= deadline:
            break
        time.sleep(1)
    if plat.alive(pid):  # B45: still running, Remote Control on, and no link in all that time
        link_drift(f'control {n}', wait)
    print(f'control {n} is up in {where}, but showed no link in {wait:g} s: find "{name}" at {REMOTE_URL}')
    return 0


# --- B54: the feed hands an ask about agent-runner itself to agent-runner's own control session ---------------

RUNNER_REPO_MARK = Path('agent_runner', 'runner.py')  # what tells agent-runner's checkout from another repo


def runner_checkout() -> Path | None:
    """agent-runner's own main checkout: the clone this install runs from (its `run`), else the main checkout of a
    worktree under agent-runner's `[run] home` (the `{repo}` in it read as agent-runner); None when neither is
    one (an installed package with no runs of agent-runner on this machine)."""
    from agent_runner.config import CLONE_ENTRY
    cands = [CLONE_ENTRY.parent] if CLONE_ENTRY.exists() else []
    for t in (os.environ.get('AGENT_RUNNER_HOME') or '', str(C.raw.get('run', {}).get('home') or ''), '~/runs/{repo}'):
        if '{repo}' not in t:  # a home without {repo} is one project's own, not agent-runner's
            continue
        home = ROOT / Path(t.replace('{repo}', 'agent-runner')).expanduser()
        if home.is_dir():
            cands += [home / 'merge', *sorted(p for p in home.iterdir() if re.fullmatch(r's\d+', p.name))]
    for c in cands:
        if not c.is_dir():
            continue
        try:
            root = main_checkout(c)
        except (SystemExit, OSError):
            continue
        if (root / RUNNER_REPO_MARK).is_file():
            return root
    return None


def runner_label(ask: str, repo: str) -> str:
    """The handed-on ask as agent-runner's control session gets it: the person's words, then where they came from."""
    return (f'{ask}\n\n(Handed on from the {repo} runner feed: the person asked this there, about agent-runner '
            f'itself, not {repo}.)')


def control_new_runner(n: int | None = None, images: list[str] | tuple = ()) -> int:
    """`control --new --forward --runner`: the feed's latest person message (read as `--forward` does) opens a
    control session in agent-runner's own checkout (`runner_checkout`), labelled with this project and carrying
    none of this project's waiting items; in this project itself, or with no checkout found, a plain `--forward`."""
    root = runner_checkout()
    if root is None or root == ROOT:
        if root is None:
            print("agent-runner's own checkout was not found on this machine, so this opens here")
        return control_new(n, images=images, forward=True)
    sid = feed_sid()
    took = feed_take_files(sid, FEED_LATE_WAIT, where='control --new --forward --runner') if sid else None
    if took is None:  # still agent-runner's: its session asks the person to send it again
        text, found, got, lost, version = feed_lost_note(), False, [], 0, ''
    elif took[2]:  # BUG1: a photo sent alone: its files, or the note that they could not be read
        text, found, got, lost, version = took[0], False, list(took[1]), 0, ''
    else:
        text = took[0]
        found, got, lost, version = feed_wait(text, FEED_WAIT, sid, 'control --new --runner')
    images = [str(Path(i).resolve()) for i in images]
    images += [i for i in got if i not in images]
    ask = runner_label(text, ROOT.name).strip()
    if found and (note := image_drift_note(lost, version)):
        ask = f'{ask}\n\n{note}'
    env = {k: v for k, v in os.environ.items() if k not in ('AGENT_RUNNER_REPO', 'AGENT_RUNNER_CONFIG', CONTROL_N_ENV)}
    cmd = [*runner_cmd(), 'control', '--new', '--from-feed', ROOT.name, f'--ask={ask}',
           *[x for i in images for x in ('--file', i)]]
    try:
        p = sp.run(cmd, cwd=str(root), env=env, capture_output=True, text=True, timeout=CONTROL_LINK_WAIT + 120)
    except (OSError, sp.TimeoutExpired) as e:
        print(f"agent-runner's control session did not open: {e}", file=sys.stderr)
        return 1
    if out := p.stdout.strip():
        print(f'agent-runner {out}')
    if err := p.stderr.strip():
        print(f'agent-runner: {err}', file=sys.stderr)
    return p.returncode


def rc_sweep_stop() -> None:
    """The run's stop: end its feed and control server now and wait for their teardown, so their entries are
    archived before the run exits (and before a suspend or power-off)."""
    RC_ENDING[0] = True
    feed_forget_session()  # B15: a real stop ends the feed's session; any other restart resumes it
    rc_sweep(os.getpid(), stopping=True)
