"""Slots and sessions: worktrees, the agent backends (Claude Code, the harness loop), Remote Control, a slot's
environment, starting and resuming a session, disk trimming and the hidden terminals (`HiddenMux`)."""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import shlex
import shutil
import subprocess as sp
import tempfile
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

from agent_runner import plan as P, plat, session_theme, shared_tools
from agent_runner.attach import Viewers, pty_resize, pty_write
from agent_runner.conpty import ConPty, InPipe, pipe_send
from agent_runner.config import finished_mark, runner_cmd, shown_cmd
from agent_runner.gitops import push
from agent_runner.state import C, clean, git, hook, log, note, ROOT, SLOTS_DIR
from agent_runner.state import EV_STARTED
from agent_runner.state import EV_DRIFT
from agent_runner.brief import prompt_for, review_on, subagents
from agent_runner.sched import ahead, blocked_tasks, open_tasks, tasks
from agent_runner.stream import run_stream, stream_message, StreamInput  # noqa: F401 (StreamInput: runner.X)
from agent_runner.tools import end_mark, FENCE_TOOLS


REMOTE_URL = 'https://claude.ai/code'  # every Remote Control session of the account, slots and control alike


# --- worktrees -----------------------------------------------------------------

def worktree(n, branch: str) -> Path:
    """Slot n's worktree (or the merge worktree), created once and kept: a warm build is worth more than a
    clean one. `[run] links` — git-ignored data the work needs — are symlinked in, never copied."""
    d = SLOTS_DIR / (f's{n}' if isinstance(n, int) else str(n))
    if not d.is_dir():
        SLOTS_DIR.mkdir(parents=True, exist_ok=True)
        git('worktree', 'prune')
        git('worktree', 'add', '-q', '--detach', str(d), branch)
    for pat in C.run['copies']:  # git-ignored files a worktree needs its own copy of (a local config)
        for src in map(Path, glob.glob(str(ROOT / pat))):
            if src.is_file() and not (dst := d / src.relative_to(ROOT)).exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    for pat in [*C.run['links'], 'runner.toml']:
        for src in map(Path, glob.glob(str(ROOT / pat))):
            dst = d / src.relative_to(ROOT)
            if src.exists() and not dst.is_symlink() and not dst.exists():
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    plat.link(src, dst)  # a symlink; on Windows without Developer Mode a junction or hard link
                except OSError:
                    pass
    backend().trust(d)
    return d


def session_id(pid: int) -> str | None:
    """The `--session-id` of the agent running as `pid` or its child (a shell may not exec it)."""
    for p in [pid, *plat.children(pid)]:
        if (args := plat.cmdline(p)) is not None and (named := sids(args)):
            return named[0]
    return None


def sids(args: list[str]) -> list[str]:
    """The session ids an agent command line names: `--session-id`'s, then `--resume`'s."""
    return [args[args.index(f) + 1] for f in ('--session-id', '--resume') if f in args[:-1]]


def adopt(branch: str) -> dict[int, tuple]:
    """Sessions an earlier run left going in slots sN: {n: ((pid, sid, since), task)}. A restarted runner
    watches and merges them as its own instead of resetting their worktrees under them. A slot past this run's count is watched until it ends and never refilled."""
    known = {t[0]: t for t in tasks(branch)}
    out = {}
    for name, (_, pid) in MUX.panes().items():
        if not re.fullmatch(r's\d+', name) or not plat.alive(pid) or not (sid := MUX.session_id(pid)):
            continue
        n = int(name[1:])
        tid = git('branch', '--show-current', cwd=SLOTS_DIR / name).stdout.strip().removeprefix('task/')
        if not tid:
            continue
        logfile = C.notes(f'slot{n}.log')
        out[n] = ((pid, sid, logfile.stat().st_size if logfile.exists() else 0),
                  known.get(tid, (tid, '', set(), set())))
        log(f'slot {n}: adopted the running {tid}')
    return out


def unmerged(branch: str, idle: list[int]) -> list[str]:
    """Open tasks whose task/<ID> has commits `branch` lacks: work that finished, or was merging, when no run
    was up to merge it. The idle
    slots in `idle` are detached first, so a slot whose session ended still on its branch neither hides
    that branch from the scan nor keeps start() from taking it later."""
    for n in idle:
        if (SLOTS_DIR / f's{n}').is_dir():
            git('checkout', '-q', '--detach', cwd=SLOTS_DIR / f's{n}')
    held = {l.removeprefix('branch refs/heads/') for l in
            git('worktree', 'list', '--porcelain').stdout.splitlines() if l.startswith('branch ')}
    # blocked too: a session that ended its task blocked (a concept round handing over) still has its journal
    # to merge, and its claim would otherwise be refreshed for as long as the branch sits
    open_ids = open_tasks(branch) | blocked_tasks(branch)
    return [t for t in ahead(branch) if f'task/{t}' not in held and t in open_ids]


def single_run() -> object:
    """Hold `<notes>/run.lock` for this process's life, or exit: two runs would share the slot worktrees
    and reset each other's sessions. The lock goes with the process, however it ends."""
    if not (f := plat.lock(C.notes('run.lock'))):
        raise SystemExit(f'another run is going in this repository ({C.notes("run.lock")} is held); '
                         f'wait for it, or `{C.command} stop` it')
    return f


# --- starting a session --------------------------------------------------------

def lean() -> list[str]:
    """Bash/Read/Edit/Write/Artifact and the repo's own settings only: an unattended agent needs no MCP servers, and a
    user-level setting (a status line, a hook that asks) is something nobody is there to answer."""
    if not C.run['lean']:
        return []
    # Artifact: a task can publish a page or screenshots to claude.ai and link it, seen from any device
    # Agent (F28, F101): the spec review before done, and the docs subagent, run as subagents
    tools = 'Bash,Read,Edit,Write,Artifact' + (',Agent' if review_on() or subagents() else '')
    return ['--tools', tools, '--setting-sources', 'project,local', '--strict-mcp-config']


def fence_hooks() -> list[dict]:
    """F102: the git fence as a PreToolUse hook (`tools.fence`): no push, no reset --hard, clean or checkout -- .,
    no edit in the main checkout or another slot."""
    cmd = [*runner_cmd(), 'fence', str(ROOT), str(SLOTS_DIR), str(C.notes()), '1' if C.push_remote else '0']
    return [{'matcher': FENCE_TOOLS, 'hooks': [{'type': 'command', 'command': plat.command_text(cmd)}]}]


def fence_argv() -> list[str]:
    """F106c: the git fence's command (`fence_hooks`'), which the harness loop runs before every tool call."""
    return [*runner_cmd(), 'fence', str(ROOT), str(SLOTS_DIR), str(C.notes()), '1' if C.push_remote else '0']


STREAM_FLAGS = ['-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose']


def stream_engine() -> bool:
    """F106b `[run] engine = "stream"`: a slot's Claude Code session runs headless (`claude -p`, stream-json in
    and out, `run_stream`) instead of interactive in a pty. The harness loop has its own engine."""
    return C.run.get('engine') == 'stream'


ARG_PROMPT_MAX = 96 * 1024  # Linux's MAX_ARG_STRLEN is 128 KiB for one argument; leave room
ARGV_PROMPT_MAX = 24000  # Windows' CreateProcess takes 32 767 characters, flags and paths included
LONG_BRIEF = 'Your instructions for this session are in your system prompt, under "{marker}". Follow them.'


class Claude:
    """Claude Code: an interactive session ended by its Stop hook once `idle` s at the prompt; the brief is
    the first message; transcripts under ~/.claude/projects, in the shape the rest of the runner reads.

    A backend is everything the runner does differently per agent CLI. To add one, subclass this and
    override what differs, then name it in BACKENDS (and `config.py`'s backend check).
    """
    report_exit = False  # log a session's last words at exit

    def flags(self, sid: str, model: str, idle: int, resume: bool, once: bool) -> list[str]:
        stop = [{'hooks': [{'type': 'command', 'command': plat.command_text(
            [*runner_cmd(), 'run', '--stop-hook', '--idle', str(-1 if stream_engine() else idle)])}]}]
        brief = C.notes(f'{sid}.brief')
        # F106b: a stream session ends at its result event (`run_stream`), so its Stop hook ends nothing (idle -1):
        # it only says once that the context is full (F177)
        ends = {'Stop': stop} if stream_engine() else {'Stop': stop, 'StopFailure': stop}
        return [*(STREAM_FLAGS if stream_engine() else []),
                '--resume' if resume else '--session-id', sid, '--permission-mode', 'bypassPermissions',
                '--disallowedTools', 'AskUserQuestion', '--model', model, *lean(),
                # F101: the review and docs subagents, each on its [models] role, so all of it is plan usage
                *(['--agents', json.dumps(agents)] if (agents := subagents()) else []),
                *(['--append-system-prompt-file', str(brief)] if brief.exists() else []),
                # lean() drops user settings, where the bypass dialog's opt-out lives; nobody is there to answer it
                '--settings', json.dumps({'skipDangerousModePermissionPrompt': True,
                                          **session_theme.settings(),  # F170: the run page's own look
                                          'hooks': {**ends,
                                                    'PreToolUse': fence_hooks()},  # F102: the git fence
                                          # on Remote Control a slot's own PushNotification tool stays off (R2:
                                          # inputNeededNotifEnabled is not here, as Claude Code only sends it to
                                          # the server from /config, so --settings never reaches the push)
                                          **({'agentPushNotifEnabled': False}
                                             if remote_slots_on() and silent() is not False else {})})]

    def cmd(self, prompt: str, pf: Path, sid: str, flags: list[str]) -> str:
        """sh reads the prompt file into the one argument (a long command line is refused). Past
        ARG_PROMPT_MAX bytes even that fails (Linux takes one argument of 128 KB at most, and the agent
        exits at once, "Argument list too long"), so the brief goes in as the system prompt (`long_brief`)."""
        if len(prompt.encode('utf-8')) > ARG_PROMPT_MAX:
            pf = pf.with_suffix('.cmd-prompt')
            pf.write_text(self.long_brief(prompt, sid), encoding='utf-8')
        return shlex.quote(C.run['agent']) + f' "$(cat {shlex.quote(str(pf))})" ' + shlex.join(flags)

    def argv(self, prompt: str, pf: Path, sid: str, flags: list[str]) -> list[str]:
        if stream_engine():  # F106b: the brief is the first stream-json message on stdin (`run_stream`), any length
            return [plat.exe(C.run['agent']), *flags]
        if len(prompt) > ARGV_PROMPT_MAX:
            prompt = self.long_brief(prompt, sid)
        return [plat.exe(C.run['agent']), prompt, *flags]

    @staticmethod
    def long_brief(prompt: str, sid: str) -> str:
        """Keep a brief too long for a command line in `<notes>/<sid>.brief`, which `flags` hands to every
        start and resume of `sid` as the system prompt (a resumed session does not keep the one it started
        with); the short first message that points at it. Read whole, unlike a file the agent would have to
        page through with its Read tool."""
        marker = 'agent-runner task brief'
        C.notes(f'{sid}.brief').write_text(f'# {marker}\n\n{prompt}', encoding='utf-8')
        return LONG_BRIEF.format(marker=marker)

    @staticmethod
    def trust(d: Path) -> None:
        """Accept Claude Code's "do you trust this folder?" dialog for `d` ahead of time: an interactive session
        in a new worktree otherwise waits on it, and no setting turns it off. The answer lives per folder in
        `~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`)."""
        # ponytail: read-modify-replace; a running Claude rewriting the file at the same instant can drop it,
        # and the next start writes it again
        cfg_dir = os.environ.get('CLAUDE_CONFIG_DIR')
        f = Path(cfg_dir) / '.claude.json' if cfg_dir else Path.home() / '.claude.json'
        try:
            data = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
        except (OSError, ValueError):
            return  # unreadable or mid-write: leave it; the dialog shows, as before
        # as_posix: Claude keys a Windows folder C:/Users/..., so C:\Users\... is never found (the slot hangs)
        proj = data.setdefault('projects', {}).setdefault(d.resolve().as_posix(), {})
        if proj.get('hasTrustDialogAccepted'):
            return
        proj['hasTrustDialogAccepted'] = True
        tmp = f.with_name(f'{f.name}.agent-runner.tmp')
        try:
            f.parent.mkdir(parents=True, exist_ok=True)  # a $CLAUDE_CONFIG_DIR not made yet: Claude makes it too
            tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
            os.replace(tmp, f)
        except OSError:
            return  # cannot write there: the dialog shows, as before

    def fix_cmd(self, prompt: str) -> list[str]:
        if on_harness(C.run['fix_model']):  # F106c: [models] fix on another provider runs in the harness loop
            return HARNESS.fix_cmd(prompt)
        return [plat.exe(C.run['agent']), '-p', prompt, '--permission-mode', 'bypassPermissions',
                '--disallowedTools', 'AskUserQuestion', '--model', C.run['fix_model'], *lean()]

    def find_transcript(self, sid: str) -> str | None:
        return next(iter(glob.glob(os.path.expanduser(f'~/.claude/projects/*/{sid}.jsonl'))), None)

    def fork_flags(self, sid: str) -> list[str]:
        """Added to a fix session's flags: it starts as a copy of session `sid` (a task's own), from any folder,
        under an id of its own. [] where the backend cannot: the session starts fresh."""
        if on_harness(C.run['fix_model']):
            return []  # ponytail: the harness could copy a transcript under a new id; its fix starts fresh
        return ['--resume', sid, '--fork-session'] if self.find_transcript(sid) else []

    def entry(self, d: dict) -> dict | None:
        return d


HARNESS_JS = Path(__file__).with_name('harness.mjs')


class Harness(Claude):
    """F106c: the harness loop (`harness.mjs`), our own agent loop on Node, for a session whose model is another
    provider's ('<provider>:<model>', `config.harness_model`), whichever backend `[run] agent` names. Its tools
    are bash, read, edit, write, finish, ask and publish_page; it asks the git fence (`run fence`) before every
    tool call and holds `[run] task_tokens` / `task_usd` before every model call. It ends at finish or ask, or
    after `idle` s with nothing to do and nothing told; `once` (a fix session) ends with its first answer. A
    tell typed into its terminal is its next message. Transcripts in `<notes>/harness-sessions`, in Claude's
    shape."""
    report_exit = True

    @staticmethod
    def trust(d):
        pass  # no folder question

    def flags(self, sid, model, idle, resume, once):
        if resume and not self.find_transcript(sid):
            raise FileNotFoundError(f'harness session {sid} is missing')
        provider = model.partition(':')[0]
        flags = ['--resume' if resume else '--session-id', sid, '--model', model, '--notes', str(C.notes()),
                 '--fence-cmd', json.dumps(fence_argv()),
                 '--runner-cmd', json.dumps(runner_cmd())]
        flags += ['--once'] if once else ['--idle', str(idle)]
        if not once:  # a task's session; a fix session is held by fix_timeout
            flags += ['--task-tokens', str(C.run.get('task_tokens') or 0), '--task-usd', str(C.run.get('task_usd') or 0)]
            if warn := int(C.run.get('context_warn') or 0):  # F177
                from agent_runner.brief import CONTEXT_FULL
                flags += ['--context-warn', str(warn), '--context-text',
                          CONTEXT_FULL.replace('{runner}', C.command).replace('{warn}', str(warn))]
        if provider in C.providers:
            flags += ['--provider', json.dumps(C.providers[provider])]
        if not once and C.fallback:  # F106g: the providers it switches to within the session at a cap
            from agent_runner.fallback import harness_chain
            if chain := harness_chain(model):
                flags += ['--fallback', json.dumps([{'model': m, 'provider': C.providers.get(m.partition(':')[0])}
                                                    for m in chain])]
        if (brief := C.notes(f'{sid}.brief')).exists():
            flags += ['--system-file', str(brief)]
        return flags

    def cmd(self, prompt, pf, sid, flags):
        return shlex.join(self.argv(prompt, pf, sid, flags))

    def argv(self, prompt, pf, sid, flags):
        return [shutil.which('node') or 'node', str(HARNESS_JS), *flags, '--prompt-file', str(pf)]

    def fix_cmd(self, prompt):
        return agent_argv(prompt, str(uuid.uuid4()), C.run['fix_model'], MASTER_IDLE, 'master', once=True)

    def find_transcript(self, sid):
        p = C.notes('harness-sessions') / f'{sid}.jsonl'
        return str(p) if p.exists() else None

    def fork_flags(self, sid):
        return []

    def entry(self, d):
        return d  # written in Claude's shape


HARNESS = Harness()
BACKENDS = {'claude': Claude()}


def backend() -> Claude:
    """Claude Code, the one backend `Config` settles since the Pi backend went (F106d); `backend_for` picks the
    harness loop for another provider's model."""
    return BACKENDS[C.run['backend']]


def on_harness(model: str) -> bool:
    """F106c: `model` (a settled one) is another provider's than claude, so its session runs in the harness loop."""
    from agent_runner.config import harness_model
    return harness_model(model, C.providers)


def backend_for(model: str) -> Claude:
    """The backend a session on `model` runs on: the harness loop for another provider's, else `backend()`."""
    return HARNESS if on_harness(model) else backend()


def agent_flags(sid: str, model: str, idle: int, resume: bool = False, once: bool = False) -> list[str]:
    """The session flags after the prompt. `resume` continues the session `sid` instead of starting it (its
    transcript keeps the id); `once` is a session with no pane, which exits after one answer."""
    return backend_for(model).flags(sid, model, idle, resume, once)


REMOTE_ENV_FLAGS = ('CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')


def remote_off_why(dialog: bool = True) -> str:
    """Why `[run] remote = 'auto'` leaves Remote Control off, or '' when it can work: Remote Control is Claude
    Code on a claude.ai login, so not an API key or token, not Bedrock, Vertex or Foundry,
    not another ANTHROPIC_BASE_URL. `dialog`: also off while Claude Code's one-time "Enable Remote Control?" has
    not been answered yes (`remote_ready` asks it at a terminal), which would hold a session in a hidden pane."""
    for k in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'):
        if os.environ.get(k):
            return f'{k} is set (Remote Control needs a claude.ai login)'
    for k in REMOTE_ENV_FLAGS:
        if os.environ.get(k, '').strip().lower() not in ('', '0', 'false', 'no', 'off'):
            return f'{k} is set (Remote Control needs a claude.ai login)'
    if (base := os.environ.get('ANTHROPIC_BASE_URL', '').strip()) and \
            urllib.parse.urlsplit(base).hostname != 'api.anthropic.com':
        return f'ANTHROPIC_BASE_URL is {base}, not api.anthropic.com'
    if dialog and not remote_dialog_seen():
        return ('Claude Code has not been told yes to Remote Control yet (run `claude remote-control` once, or '
                f'{shown_cmd()} at a terminal, and answer y)')
    return ''


# --- B45: Claude Code drift checks ---------------------------------------------
#
# Where agent-runner reads Claude Code internals rather than a documented interface (its transcripts, the session
# link in a pane, remoteDialogSeen in ~/.claude.json), a reader that finds the shape it expects gone says so once
# per Claude Code version: a run.log line and event (EV_DRIFT) that since --follow, the runner feed and control
# sessions' watch show as needs-you, instead of failing silently. A local warning only: nothing is filed.

DRIFT_FILE = 'claude-drift.json'  # <notes>/claude-drift.json: {spot: the Claude Code version last warned about}
CLAUDE_VERSION: list[str] = []  # `claude --version`, asked once per process (`claude_code_version`)


def claude_code_version() -> str:
    """The installed Claude Code's version ('2.1.330'); '' when it cannot be told (no claude found)."""
    if not CLAUDE_VERSION:
        v = ''
        try:
            r = sp.run([plat.exe(C.run['agent']), '--version'], capture_output=True, text=True, timeout=15)
            m = re.search(r'\d+(?:\.\d+)+', r.stdout or '')
            v = m.group(0) if m else ''
        except (OSError, sp.TimeoutExpired):
            pass
        CLAUDE_VERSION.append(v)
    return CLAUDE_VERSION[0]


def claude_drift(spot: str, changed: str, broke: str, version: str = '') -> bool:
    """Say 'Claude Code `version` changed `changed`; `broke` no longer works' as a needs-you line (EV_DRIFT),
    once per Claude Code version for each `spot` ('transcript', 'link', 'remote-answer'), kept in
    <notes>/claude-drift.json. True when it said it now; False when it was said already for this version."""
    version = version or claude_code_version() or '(version unknown)'
    f = C.notes(DRIFT_FILE)
    try:
        said = json.loads(f.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        said = {}
    said = said if isinstance(said, dict) else {}
    if said.get(spot) == version:
        return False
    said[spot] = version
    try:
        tmp = f.with_name(f'{f.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(said, indent=2), encoding='utf-8')
        os.replace(tmp, f)
    except OSError:
        pass
    log(f'Claude Code {version} changed {changed}; {broke} no longer works', EV_DRIFT, spot=spot, version=version)
    return True


def link_drift(who: str, wait: float) -> bool:
    """B45 spot 2: Remote Control is on and session `who`'s pane, still open, showed no claude.ai/code session
    link in `wait` s (CONTROL_LINK_WAIT): Claude Code shows it differently now."""
    return claude_drift('link', f"how a Remote Control session shows its link ({who} showed no "
                        f"claude.ai/code/session_ link in {wait:g} s)",
                        "reading the session's link from its pane (control --new answering with the link)")


def remote_answer_drift(who: str) -> bool:
    """B45 spot 3: session `who` came up on Remote Control, so Claude Code was asked and answered yes, yet
    ~/.claude.json has no remoteDialogSeen: it keeps that answer under another name now. Nothing when the
    key is there or the file cannot be read."""
    f = claude_json()
    try:
        data = json.loads(f.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or 'remoteDialogSeen' in data:
        return False
    return claude_drift('remote-answer', f'where it keeps the Remote Control answer (no remoteDialogSeen in {f}, '
                        f'though {who} came up on Remote Control)',
                        "telling whether Remote Control was answered ([run] remote = auto keeps it off, "
                        "and a start asks again)")


def remote_dialog_seen() -> bool:
    try:
        return bool(json.loads(claude_json().read_text(encoding='utf-8')).get('remoteDialogSeen'))
    except (OSError, ValueError, AttributeError):
        return False


def remote_on() -> bool:
    """`[run] remote`, resolved: control sessions and the control server on Remote Control. 'auto' is on when
    `remote_off_why` finds nothing; true forces it; false keeps it off."""
    v = C.run['remote']
    if v == 'auto':
        return not remote_off_why()
    return bool(v)


def remote_slots_on() -> bool:
    """`[run] remote_slots = "always"`: the slots on Remote Control too (never under 'auto' alone). F106b: never headless
    slots (`[run] engine = "stream"`), which have no Remote Control."""
    return C.run['remote_slots'] == 'always' and not stream_engine()


def remote_any() -> bool:
    return remote_on() or remote_slots_on()


def remote_line() -> str:
    """The run's one log line on Remote Control: what is on it, or (under 'auto') why it is off."""
    on, slots = remote_on(), remote_slots_on()
    if on or slots:
        what = 'control sessions and the slots' if on and slots else 'control sessions' if on else 'slots'
        return f'remote control on: the {what} show at {REMOTE_URL} and in the Claude apps; Enter here opens it'
    if C.run['remote'] == 'auto':
        return f'remote control off: {remote_off_why()}; [run] remote = true forces it'
    return ''  # false: off, as asked, and nothing to say


def remote_flags(name: str, cwd: Path | None) -> list[str]:
    """`[run] remote_slots = "always"`: the session shows in claude.ai/code and the Claude apps as "<task title> · <repo> s2 ·
    B646" (the title leads, the id stays for referring to it), where a person can watch it and type to it. Claude
    Code only, and only an interactive session.
    (`[run] remote` alone puts only the control sessions there: `control_argv`.)"""
    if not remote_slots_on():  # F68: otherwise only once opened (slot_open)
        return []
    return ['--remote-control', slot_session_name(name, cwd)]


def slot_session_name(name: str, cwd: Path | None) -> str:
    """A slot's name in claude.ai/code and the apps: "<task title> · <repo> s2 · B646"."""
    tid = git('branch', '--show-current', cwd=cwd).stdout.strip().removeprefix('task/') if cwd else ''
    title = P.titles(C.done, C.todo, width=50).get(tid, '') if tid else ''
    return ' · '.join(x for x in (title, f"{ROOT.name} {name.replace('slot', 's')}", tid) if x)


def one_session() -> bool:
    """F68 `[run] remote_slots = 'open'` (the default): the Claude apps list the chats and the runner feed. A slot starts off Remote Control and goes on it only when a person opens it from the run page
    (`slot_open`); the run keeps a claude.ai copy of the run page (page_copy.py). 'always': as before."""
    return C.run['remote_slots'] != 'always'


OPEN_WAIT = 20.0  # s slot_open waits for an opened slot's claude.ai/code link


def slot_open(name: str, wait: float = OPEN_WAIT) -> tuple[str, str]:
    """F68: open slot `name` (s2) in claude.ai/code and the apps: under `[run] remote_slots = 'open'` its session is
    told `/remote-control <its name>`, which puts it on Remote Control from then on (until it ends), so it is
    listed only once a person asked for it. (link, '') once its link shows within `wait` s; ('', why) when it
    cannot: no session runs there, Remote Control cannot work here, or the link did not come up. A slot
    already on Remote Control (opened before, or under 'always') gives its link at once."""
    from agent_runner.ui_model import _bridge_link
    hit = MUX.panes().get(name)
    if not hit or not plat.alive(hit[1]) or not (sid := MUX.session_id(hit[1])):
        return '', f'no session runs in {name}'
    if link := _bridge_link(sid):
        return link, ''
    if getattr(MUX, 'streamed', lambda h: False)(hit):  # F106b: a headless session has no Remote Control
        return '', f'{name} runs headless ([run] engine = "stream"), which has no Remote Control: the run page shows it'
    if why := remote_off_why():
        return '', f'Remote Control is off: {why}'
    wt = SLOTS_DIR / name
    if not getattr(MUX, 'typed', True) or \
            not MUX.send(hit, f'/remote-control {slot_session_name(name, wt if wt.is_dir() else None)}'):
        return '', f'could not type into {name}'
    log(f'{name}: opened on Remote Control (asked from the run page)')
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if link := _bridge_link(sid):
            return link, ''
        time.sleep(0.5)
    return '', f'{name} showed no claude.ai/code link within {wait:g} s'


def agent_cmd(prompt: str, sid: str, model: str, idle: int, name: str, resume: bool = False,
              cwd: Path | None = None) -> str:
    """The agent command line for one task, for sh. The prompt is
    written to `<notes>/<name>.prompt` and goes in from there (`Claude.cmd`, `Harness.cmd`)."""
    pf = C.notes(f'{name}.prompt')
    pf.write_text(prompt, encoding='utf-8')
    b = backend_for(model)  # F106c: the harness loop has no Remote Control
    return b.cmd(prompt, pf, sid, agent_flags(sid, model, idle, resume) +
                 ([] if b is HARNESS or stream_engine() else remote_flags(name, cwd)))


def agent_argv(prompt: str, sid: str, model: str, idle: int, name: str, resume: bool = False,
               once: bool = False, cwd: Path | None = None) -> list[str]:
    """The same command as an argv, for a hidden slot (`HiddenMux`), where no shell stands between us and the
    agent. The prompt is written to `<notes>/<name>.prompt` all the same."""
    pf = C.notes(f'{name}.prompt')
    pf.write_text(prompt, encoding='utf-8')
    b = backend_for(model)  # F106c: the harness loop has no Remote Control
    return b.argv(prompt, pf, sid, agent_flags(sid, model, idle, resume, once) +  # F106b: nor a stream session
                  ([] if once or b is HARNESS or stream_engine() else remote_flags(name, cwd)))


SLOTS = 1  # how many slots this run has; `cmd_run` sets it, for {slots} in `[run] slot_env`


def shared_env() -> list[str]:
    """`[run] slot_env` entries that are not per slot (no {n}), such as a compiler cache, {slots} filled in."""
    return [e.replace('{slots}', str(SLOTS)) for e in C.run['slot_env'] if '{n}' not in e]


def merge_env() -> dict:
    """The merge worktree's gate environment: ours and `shared_env`, so the merge builds the way the slots do."""
    return {**os.environ, **env_vars(shared_env())}


def slot_env(n: int | None) -> list[str]:
    """A slot's environment, as NAME=value: `AGENT_RUNNER=1`, `AGENT_SLOT=<n>`; the config file when it came from
    AGENT_RUNNER_CONFIG and every variable `[run] pass_env` names that is set (a session started elsewhere does
    not inherit the runner's environment, so a wrapper's own variables must be passed on by name); then `[run]
    slot_env` with {n} (the slot) and {slots} filled in. `n=None` is the master window's: `shared_env` in
    place of `[run] slot_env`, so it builds in the merge worktree the way the gate there does."""
    # `finished_mark`; C14: AGENT_SLOT whatever `slot_env` says, which only adds to it
    env = ['AGENT_RUNNER=1'] + ([] if n is None else [f'AGENT_RUNNER_SLOT={n}', f'AGENT_SLOT={n}',
                                                      f'AGENT_RUNNER_WORKTREE={SLOTS_DIR / f"s{n}"}'])  # B103
    env.append(f'CLAUDE_CODE_TMPDIR={session_tmp()}')
    if os.environ.get('AGENT_RUNNER_CONFIG') and C.file:
        env.append(f'AGENT_RUNNER_CONFIG={C.file}')
    env += [f'{k}={os.environ[k]}' for k in C.run['pass_env'] if k in os.environ]
    return env + (shared_env() if n is None else [e.format(n=n, slots=SLOTS) for e in C.run['slot_env']]) + \
        ([f'{PRESENCE_ENV}={quiet_file("slots")}'] if n is not None and remote_slots_on() and silent() is not False
         else [])


# While the file it names exists, Claude Code pulses "client present" just before each push-triggering state
# (needs input, turn done), so the server skips those pushes. It cannot stop the "session ready" push: the server
# sends that as the session registers, before the first pulse (R2, from the Claude Code 2.1.329 binary).
PRESENCE_ENV = 'CLAUDE_CLIENT_PRESENCE_FILE'


def silent() -> bool:
    """`[run] silent`: True (a presence file for good: no push after each session's start push), False (no
    presence file: Claude Code pushes as it would for any session)."""
    return C.run['silent']


def quiet_file(who: str, on: bool = True) -> Path:
    """`<notes>/quiet-<who>`, the file a Remote Control session's CLAUDE_CLIENT_PRESENCE_FILE names: made (`on`) or
    removed. Kept for good while it is named, so the session's later pushes stay quiet; never its start push
    (see PRESENCE_ENV)."""
    f = C.notes(f'quiet-{who}')
    try:
        f.touch() if on else f.unlink(missing_ok=True)
    except OSError:
        pass
    return f


def env_vars(env) -> dict[str, str]:
    """NAME=value entries as a dict."""
    return dict(e.split('=', 1) for e in env)


def save_leftovers(d: Path, tid: str, branch: str) -> str | None:
    """Keep what a slot's session left uncommitted on a branch before anything resets the worktree.

    A session can end before its `done` commits (killed, or stopped mid-gate), and the next `start` resets
    the slot. With no commits of its own the work goes to wip/<tid>, where the task's next attempt is told
    to look; otherwise (or with a wip/<tid> already there) to leftover/<tid>, so the merge never takes in
    untested edits. The branch's own index and files are left as they are. Returns the branch, '' when
    there was nothing to keep, or None when the save failed."""
    if not git('status', '--porcelain', cwd=d).stdout.strip():
        return ''
    fd, idx = tempfile.mkstemp(prefix='agent-runner-index-')
    os.close(fd)
    env = {**os.environ, 'GIT_INDEX_FILE': idx}
    try:
        g = lambda *a: git(*a, cwd=d, env=env)
        if g('read-tree', 'HEAD').returncode or g('add', '-A').returncode:
            return None
        tree = g('write-tree').stdout.strip()
        if tree and tree == git('rev-parse', 'HEAD^{tree}', cwd=d).stdout.strip():
            return ''  # only what a commit can't hold changed (a submodule's own edits, say): nothing to keep
        msg = f'{tid} wip: uncommitted when the session ended (saved by the runner before the slot was reset)'
        c = g('commit-tree', tree, '-p', 'HEAD', '-m', msg).stdout.strip()
    finally:
        os.unlink(idx)
    if not c:
        return None
    mine = git('rev-list', '--count', f'{branch}..HEAD', cwd=d).stdout.strip()
    wip = not git('rev-parse', '--verify', '-q', f'refs/heads/wip/{tid}', cwd=d).returncode
    to = f'wip/{tid}' if mine == '0' and not wip else free_branch(f'leftover/{tid}')
    if git('branch', to, c, cwd=d).returncode:
        return None
    files = git('diff', '--name-only', 'HEAD', c, cwd=d).stdout.split()
    many = f'{len(files)} file{"s" if len(files) != 1 else ""}'
    note(f'{tid}: the session left {many} uncommitted; saved on {to}')
    log(f'{tid}: the session left {many} uncommitted ({", ".join(files)[:200]}); saved on {to}')
    if out := push(ROOT, to):
        log(out)
    return to


def free_branch(name: str) -> str:
    """`name`, or `name-2`, `name-3`, … when an earlier attempt already holds it: a ref is never overwritten."""
    k, out = 1, name
    while not git('rev-parse', '--verify', '-q', f'refs/heads/{out}').returncode:
        k += 1
        out = f'{name}-{k}'
    return out


def edited_elsewhere(files) -> list[str]:
    """Checkouts outside the runner's own slots (the main checkout, a person's or a chat session's worktree)
    with uncommitted edits to any of `files`, as 'path (file, file)'. Work there is invisible to the runner
    until it is committed, so a task started on the same files is likely to redo it or to conflict."""
    files = set(files)
    if not files:
        return []
    out = []
    listed = git('worktree', 'list', '--porcelain', cwd=ROOT).stdout.splitlines()
    for d in (Path(l[len('worktree '):]) for l in listed if l.startswith('worktree ')):
        if d.parent == SLOTS_DIR and re.fullmatch(r's\d+|merge\d*|fix\d+', d.name):
            continue
        if not d.is_dir():  # a worktree whose folder was deleted (git lists it as prunable)
            continue
        st = git('status', '--porcelain', '--untracked-files=no', cwd=d)
        if st.returncode:
            continue
        hit = sorted(files & {l[3:].split(' -> ')[-1] for l in st.stdout.splitlines()})
        if hit:
            out.append(f'{d} ({", ".join(hit[:4])}{", …" if len(hit) > 4 else ""})')
    return out


def vacate(n: int, d: Path, head: str, branch: str, what: str) -> bool:
    """Slot n's worktree `d` (on branch `head`) reset clean, what its session left uncommitted saved first
    (`save_leftovers`); False, and nothing reset, when that save failed."""
    if save_leftovers(d, head.removeprefix('task/') if head.startswith('task/') else f's{n}', branch) is None:
        log(f'slot {n}: uncommitted edits there could not be saved; not resetting it {what}')
        return False
    clean(d)
    return True


def slot_header(n: int, what: str) -> tuple[Path, int]:
    """A session's header line in slot n's log: (the log, its size before the line)."""
    logfile = C.notes(f'slot{n}.log')
    since = logfile.stat().st_size if logfile.exists() else 0  # in append mode tell() is not that
    with open(logfile, 'a', encoding='utf-8') as f:
        f.write(f'\n=== {dt.datetime.now().isoformat(timespec="seconds")} {what}\n')
    return logfile, since


# --- disk: worktrees keep their builds warm, within limits ----------------------

GB = 1 << 30
DISK_AT = [0.0]  # when `low_disk` last cleaned
DISK_SAID = [False]


def usage(p: Path) -> tuple[int, float]:
    """(bytes on disk, newest write) under `p`, symlinks not followed (a `links` target is not the slot's)."""
    total, newest = 0, 0.0
    walk = os.walk(p) if p.is_dir() and not p.is_symlink() else [(str(p.parent), [], [p.name])]
    for root, _, files in walk:
        for f in files:
            try:
                st = os.lstat(os.path.join(root, f))
            except OSError:
                continue
            total += getattr(st, 'st_blocks', 0) * 512 or st.st_size
            newest = max(newest, st.st_mtime)
    return total, newest


def du(d: Path) -> int:
    return usage(d)[0]


def stale_first(d: Path, split: int, least: int) -> list[tuple[float, int, Path]]:
    """`d`'s git-ignored files and folders, least recently written first: (newest write, bytes, path). A folder
    bigger than `split` is broken into what is in it (three levels at most), so a build tree's stale parts go
    one by one and its live ones stay: target/debug/incremental before target/debug/deps. Nothing under `least`
    bytes: small ignored files free nothing and may be someone's notes or settings."""
    out: list[tuple[float, int, Path]] = []

    def add(p: Path, depth: int) -> None:
        if p.is_symlink():
            return  # `links`, runner.toml: put there by `worktree`, not build output
        size, newest = usage(p)
        if p.is_dir() and size > split and depth < 3:
            for k in p.iterdir():
                add(k, depth + 1)
        elif size >= least:
            out.append((newest, size, p))

    for rel in git('ls-files', '--others', '--ignored', '--exclude-standard', '--directory', '-z',
                   cwd=d).stdout.split('\0'):
        if rel:
            add(d / rel.rstrip('/'), 0)
    return sorted(out, key=lambda t: t[0])


def trim(d: Path, what: str, why: str = '') -> bool:
    """Shrink worktree `d` when it is over `[run] slot_max_gb`, or clean it whole when `why` says it must be (the
    disk is nearly full). Only ever for a worktree nobody works in: a free slot before its next task, the merge
    worktree under MERGE. True when it removed anything (`worktree` puts `links` back).

    Over the cap, by default the least recently written git-ignored parts go until it is at half the cap: the
    build folders recent tasks used stay warm, the ones old tasks left behind go. `[run] slot_clean`, when set,
    is run instead, in both cases."""
    cap = C.run['slot_max_gb'] * GB
    size = du(d)
    if not why:
        if not cap or size <= cap:
            return False
        why = f'over [run] slot_max_gb ({C.run["slot_max_gb"]} GB)'
        if not C.run['slot_clean']:
            gone, names = 0, []
            for _, n, p in stale_first(d, cap // 4, cap // 500):  # 50 GB: folders over 12 GB split, none under 100 MB
                if size - gone <= cap // 2:
                    break
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
                for q in p.parents:  # no empty folders left behind
                    if q == d or any(q.iterdir()):
                        break
                    q.rmdir()
                gone += n
                names.append(p.relative_to(d).as_posix())
            more = f' and {len(names) - 5} more' if len(names) > 5 else ''
            log(f'{what}: {size / GB:.1f} GB, {why}: removed the least recently written build output '
                f'({", ".join(names[:5])}{more}), now {du(d) / GB:.1f} GB')
            return bool(names)
    cmd = C.run['slot_clean'] or 'git clean -ffdXq'
    hook(what, cmd, d)
    log(f'{what}: {size / GB:.1f} GB, {why}: cleaned with `{cmd}`, now {du(d) / GB:.1f} GB')
    return True


def free_gb() -> float:
    return shutil.disk_usage(SLOTS_DIR if SLOTS_DIR.is_dir() else ROOT).free / GB


def task_model(tid: str, model: str, branch: str, ls: list[str] | None = None) -> str:
    """F105: the model `tid`'s own session runs on: the task's `model:` field (`plan add --model`), else the
    model the run was given on its command line (`run --model`), else its kind's (`[models.kinds]`), else
    `model` (`[models] code`). Read afresh on every start and resume: a changed field or setting applies.
    `branch` '' reads the plan file itself, not the branch's copy; `ls`: the plan's lines, when already read."""
    from agent_runner.state import plan_text
    try:
        ls = ls if ls is not None else plan_text(branch) if branch else P.lines(C.todo)
        own = next((P.fields(rest).get('model', [''])[0] for _, _, t, rest, _ in P.iter_tasks(ls) if t == tid), '')
    except (OSError, IndexError):
        own = ''
    if not own and (flag := C.run.get('model_flag')):
        return flag
    return C.task_model(tid, own) or model


def start(n: int, task, branch: str, model: str, idle: int, slots: int, held: frozenset = frozenset()):
    """Start `task` in slot n. `held` (F142): the providers past a usage cap, not to start it on."""
    from agent_runner.fallback import note_model, start_model
    tid = task[0]
    model = start_model(task_model(tid, model, branch), held)  # F106g: a capped provider's task starts on the chain
    finished_mark(n, C).unlink(missing_ok=True)  # the last task's `done`, not this one's
    C.notes(f'{tid}.budget').unlink(missing_ok=True)  # F103: an earlier attempt's budget stop, not this one's
    C.notes(f'{tid}.fallback').unlink(missing_ok=True)  # F106g: an earlier attempt's cap stop
    d = worktree(n, branch)
    head = git('symbolic-ref', '-q', '--short', 'HEAD', cwd=d).stdout.strip()
    if not vacate(n, d, head, branch, f'for {tid}'):
        return None
    if trim(d, f'slot {n}'):
        worktree(n, branch)  # the `links` the clean took
    end_mark(n, C).unlink(missing_ok=True)  # F102: the last session's finish or ask, read when it ended
    ask = asked(tid)  # F102: it asked the person, and the answer is in: its own session goes on
    wait = {} if ask else shared_tools.waited(tid)  # F168: it gave up its slot for a shared tool, free now
    base = f'asked/{tid}' if ask else f'waiting/{tid}' if wait else branch
    if not wait:
        shared_tools.forget(tid)
    co = git('checkout', '-q', '-B', f'task/{tid}', base, cwd=d)
    if co.returncode:  # e.g. another worktree still holds task/<ID>: never start an agent on the wrong branch
        log(f'slot {n}: checkout task/{tid} failed: {co.stderr.strip()[:200]}')
        return None
    if ask:
        if ask.get('dirty'):
            git('reset', '-q', 'HEAD~1', cwd=d)  # its edits are uncommitted again, as the session left them
        git('branch', '-D', base)
        C.notes(f'{tid}.ask').unlink(missing_ok=True)
        if p := answer_ask(n, tid, d, ask, model, idle):
            return p
        log(f'slot {n}: {tid}\'s asking session cannot be resumed; a new one starts on the work it left')
    if wait:
        if wait.get('dirty'):
            git('reset', '-q', 'HEAD~1', cwd=d)  # its edits are uncommitted again, as the session left them
        if p := shared_tools.wake(n, tid, d, wait, model, idle):
            shared_tools.resumed(tid, wait)
            return p
        log(f'slot {n}: {tid}\'s waiting session cannot be resumed; a new one starts on the work it left')
    sid = str(uuid.uuid4())
    prompt = prompt_for(tid, n, slots, d, branch, model)  # F132: the harness loop's brief has no subagents
    logfile, since = slot_header(n, f'{tid} session {sid}')
    note_model(sid, model)
    if not (pid := MUX.open(n, d, prompt, sid, model, idle, slot_env(n), logfile)):
        log(f'slot {n}: the session for {tid} did not start in {MUX.where(n)}')
        shared_tools.not_started(tid, d, wait)
        return None
    shared_tools.resumed(tid, wait)
    log(f'slot {n}: {tid} ({task[1]}; {", ".join(sorted(task[2])) or "no files listed"})', EV_STARTED, tid)
    for where in edited_elsewhere(task[2]):
        log(f'slot {n}: {tid} heads into uncommitted edits outside the runner, in {where}: '
            f'if that is the same work, stop the slot; if not, commit it before {tid} lands')
    return pid, sid, since


ANSWERED = """The person answered the question you asked with `run ask` ("{question}"):

{answer}

The runner resumed this session {where}; whatever you had running in the background ended with it. Look at \
`git status`, then carry on with task {tid} as the first message of this session says."""


def asked(tid: str) -> dict:
    """F102: `<notes>/<tid>.ask`, kept while the task waits on the person's answer ({sid, question, slot, dirty}),
    when its work is still there on asked/<tid>; {} otherwise."""
    try:
        ask = json.loads(C.notes(f'{tid}.ask').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(ask, dict) or not ask.get('blocked') or \
            git('rev-parse', '--verify', '-q', f'asked/{tid}').returncode:
        return {}  # not blocked yet: no answer can have come (`block_asks` blocks it first)
    return ask


def claude_project_dir(d: Path) -> str:
    """The folder name Claude Code keeps a working folder's transcripts under, in ~/.claude/projects."""
    return re.sub(r'[^A-Za-z0-9]', '-', str(d.resolve()))


def move_transcript(sid: str, d: Path) -> bool:
    """Claude Code finds a session to `--resume` only among its working folder's transcripts: one that asked in
    another slot has its transcript moved under `d`'s. False when there is no transcript to resume."""
    if HARNESS.find_transcript(sid):
        return True  # F106c: the harness loop's sessions live in one folder for every slot
    if not (t := backend().find_transcript(sid)):
        return False
    dest = Path(t).parent.parent / claude_project_dir(d) / f'{sid}.jsonl'
    if Path(t) != dest:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(t, dest)
        except OSError:
            return False
    return True


def answer_ask(n: int, tid: str, d: Path, ask: dict, model: str, idle: int):
    """F102: resume the session that ran `run ask` in slot n, the person's answer its next message. None when it
    cannot be resumed (no session id, no transcript, or the session did not start)."""
    sid = ask.get('sid') or ''
    if not sid or sid == '(unknown)' or not move_transcript(sid, d):
        return None
    if on_harness(model) != bool(HARNESS.find_transcript(sid)):
        return None  # F142: the chain starts it on the other kind of agent, which cannot read this session
    answer = P.last_answer(tid, todo=C.todo, about=ask.get('question', '')) or '(no answer was noted: decide yourself, and say why in the journal)'
    where = shared_tools.where_now(n, d, ask.get('slot'))
    logfile, since = slot_header(n, f'{tid} answered {sid}')
    prompt = ANSWERED.format(question=ask.get('question', ''), answer=answer, where=where, tid=tid)
    if not (pid := MUX.open(n, d, prompt, sid, model, idle, slot_env(n), logfile, resume=True)):
        log(f'slot {n}: the session for {tid} did not resume in {MUX.where(n)}')
        return None
    log(f'slot {n}: {tid} resumed with the person\'s answer', EV_STARTED, tid)
    return pid, sid, since


RESUME = """The runner resumed this session: it was cut off ({why}). Whatever you had running in the \
background ended with it, and so did anything `[run] on_exit` stops. Look at `git status` and at what you \
did last, then carry on with task {tid} where you left off and finish it as the first message of this \
session says."""


def resume(n: int, tid: str, sid: str, why: str, branch: str, model: str, idle: int, fallback: str = '',
           slots: int = 1):
    """Continue the session `sid` of task `tid` in slot n, where it ran: its transcript names that worktree's
    paths, so no other slot will do. A slot still on task/<tid> is used as it is; one that moved on gets the
    task back from wip/<tid> (the edits the session left, saved when the slot was reset), uncommitted again.
    F106g: with `fallback` (the next model in [models] fallback, its provider having hit its cap), a new session
    on that model goes on with the work in the worktree instead, told to read it and the journal first.
    """
    from agent_runner.fallback import FALLBACK, note_model, session_model
    model = fallback or task_model(tid, model, branch)  # F105: on its task's model, as at its start
    if not fallback and on_harness(model) != bool(HARNESS.find_transcript(sid)):
        model = session_model(sid)  # F142: the chain started it on the other kind of agent: only that can resume it
    d = worktree(n, branch)
    head = git('symbolic-ref', '-q', '--short', 'HEAD', cwd=d).stdout.strip()
    if head != f'task/{tid}':
        if not vacate(n, d, head, branch, f'to resume {tid}'):
            return None
        saved = git('log', '-1', '--format=%s', f'wip/{tid}', '--').stdout.startswith(f'{tid} wip: uncommitted')
        src = f'wip/{tid}' if saved else f'task/{tid}'
        if git('rev-parse', '--verify', '-q', src).returncode:
            log(f'slot {n}: nothing of {tid} to resume from (no task/{tid}, and no wip/{tid} the runner saved)')
            return None
        if git('checkout', '-q', '-B', f'task/{tid}', src, cwd=d).returncode:
            log(f'slot {n}: checkout task/{tid} failed; not resuming it')
            return None
        if saved:
            git('reset', '-q', 'HEAD~1', cwd=d)  # the saved edits are uncommitted again, as the session left them
            git('branch', '-M', src, free_branch(f'resumed/{tid}'))  # kept, but no longer read as an earlier attempt
    if fallback:  # F106g: a new session on the next provider, the old one's work in the worktree
        sid = str(uuid.uuid4())
        prompt = FALLBACK.format(model=model, tid=tid, why=why, branch=branch) + \
            prompt_for(tid, n, slots, d, branch, model)
        logfile, since = slot_header(n, f'{tid} session {sid} (fallback: {why})')
        note_model(sid, model)
        if not (pid := MUX.open(n, d, prompt, sid, model, idle, slot_env(n), logfile)):
            log(f'slot {n}: the session for {tid} on {model} did not start in {MUX.where(n)}')
            return None
        log(f'slot {n}: {tid} goes on with {model} ({why})', EV_STARTED, tid)
        return pid, sid, since
    logfile, since = slot_header(n, f'{tid} resume {sid} ({why})')
    if not (pid := MUX.open(n, d, RESUME.format(why=why, tid=tid), sid, model, idle, slot_env(n), logfile,
                            resume=True)):
        log(f'slot {n}: the session for {tid} did not resume in {MUX.where(n)}')
        return None
    log(f'slot {n}: {tid} resumed ({why})')
    return pid, sid, since


# --- terminals: one per slot -----------------------------------------------------

SHIM_WAIT = 30.0  # s a hidden slot's shim gets to start its agent (a busy machine is slow to start Python)


class HiddenMux:
    """F40: a slot with no window, on every OS. Watched through Remote Control (with `[run] remote_slots = "always"`),
    status, the slot's log and control sessions; steered by `plan tell`.

    Each slot runs through a shim (`run --slot-shim <job>`, `slot_shim`), started detached so the session
    outlives a restarted runner and the next run adopts it: it reads the argv, directory and environment
    from `<notes>/slotN.job`, starts the agent, and keeps the agent's pid in `<notes>/slotN.live` while it
    runs. The loop, a restart's adopt and the Stop hook all read that marker. POSIX: the agent runs in a
    pseudo-terminal of the standard library's `pty` (it needs a TTY), the shim copies its output to the
    slot log and types into it what arrives on the FIFO `<notes>/slotN.in` (`send`); `attach sN` puts a
    terminal on it through the socket `<notes>/slotN.sock` (F88, Ctrl-b d leaves). Windows (F145):
    the agent runs in a ConPTY pseudo-console (`run_conpty`), its output in the slot log too, and
    `<notes>/slotN.in` names the pipe, open to this user alone, that typed text comes in by, and
    `<notes>/slotN.sock` the port on 127.0.0.1 and the token `attach sN` reaches it with (F114). Before Windows 10 1809, which has no ConPTY, a console of
    its own whose window starts hidden (`attach sN` shows it): nothing captures its output, so the slot log
    has only the header lines, and nothing can be typed into it.
    """
    name = 'hidden'

    @property
    def typed(self) -> bool:  # Windows' hidden console (no ConPTY there) takes no typed text
        return not plat.WINDOWS or plat.has_conpty()

    def open(self, n, cwd, prompt, sid, model, idle, env, logfile, resume=False):
        job, marker = C.notes(f'slot{n}.job'), C.notes(f'slot{n}.live')
        ended = marker.with_suffix('.exit')
        for f in (marker, ended, marker.with_suffix('.in')):  # .in: a killed shim's
            f.unlink(missing_ok=True)
        envd = env_vars(env)
        # F106b: a headless session gets its brief (or resume message) as the first stream-json message
        stream = {'stream': True, 'brief': prompt, 'sid': sid, 'events': str(stream_file(sid))} \
            if stream_engine() and backend_for(model) is not HARNESS else {}
        job.write_text(json.dumps({'argv': agent_argv(prompt, sid, model, idle, f'slot{n}', resume, cwd=cwd), 'cwd': str(cwd),
                                   'env': envd, 'marker': str(marker), 'log': str(logfile), **stream}), encoding='utf-8')
        shim = [*runner_cmd(), 'run', '--slot-shim', str(job)]
        if plat.WINDOWS and (stream or not plat.has_conpty()):
            plat.spawn_console(shim, cwd, {**os.environ, **envd}, hidden=True)
        else:
            plat.spawn_detached(shim, out=C.notes(f'slot{n}.shim'))  # its own errors, should it fail
        end = time.monotonic() + SHIM_WAIT
        while time.monotonic() < end:
            if pid := marker_pid(marker):
                return pid
            if ended.exists():  # the agent ended before the marker was seen, or never started
                said = ended.read_text(encoding='utf-8').strip()
                if m := re.match(r'exit code -?\d+ \(pid (\d+)\)', said):
                    return int(m.group(1))  # it ran, and ended between two looks: reaped as any ended session
                log(f'slot {n}: the agent ended at once: {said[:300]}')
                return None
            time.sleep(0.3)
        return None

    def panes(self) -> dict[str, tuple[str, int]]:
        """{sN: (marker, pid)} for every slot whose marker is there; the caller checks the pid is alive."""
        out = {}
        for m in C.notes().glob('slot*.live'):
            if re.fullmatch(r'slot\d+', m.stem) and (pid := marker_pid(m)):
                out[f's{m.stem[4:]}'] = (str(m), pid)
        return out

    def session_id(self, pid: int) -> str | None:
        for m in C.notes().glob('slot*.live'):
            if marker_pid(m) == pid:
                try:
                    args = json.loads(m.with_suffix('.job').read_text(encoding='utf-8'))['argv']
                except (OSError, ValueError, KeyError):
                    return None
                return (sids(args) or [None])[0]
        return None

    def where(self, n: int) -> str:
        return (f'the hidden console of slot {n} ({shown_cmd()} attach s{n} shows it)'
                if plat.WINDOWS and not logged(C.notes(f'slot{n}.live')) else
                f'slot {n}\'s log, {C.notes(f"slot{n}.log")}')

    def streamed(self, hit: tuple[str, int]) -> bool:
        """F106b: the slot whose marker is `hit[0]` runs headless (`run_stream`)."""
        try:
            return bool(json.loads(Path(hit[0]).with_suffix('.job').read_text(encoding='utf-8')).get('stream'))
        except (OSError, ValueError, AttributeError):
            return False

    def send(self, hit: tuple[str, int], text: str) -> bool:
        """Type `text` into the slot whose marker is `hit[0]`, through its shim's FIFO, and press Enter. F106b: a
        headless session gets it as its next stream-json user message instead (Windows: not at all)."""
        inbox = Path(hit[0]).with_suffix('.in')
        return send_fifo_raw(inbox, stream_message(text)) if self.streamed(hit) else send_fifo(inbox, text)


def hidden_line() -> str:
    """The run's log line for hidden slots: where to watch and steer them."""
    see = [f'{shown_cmd()} status', f'the slot logs ({C.notes("slotN.log")})', f'{shown_cmd()} control']
    if remote_slots_on():
        see.insert(0, f'Remote Control ({REMOTE_URL}, the Claude apps)')
    if plat.WINDOWS and not plat.has_conpty():
        see.append(f'{shown_cmd()} attach sN (shows its console)')
    if stream_engine():  # F106b
        return 'slots run headless (claude -p, stream-json; [run] engine = "stream"), with no Remote Control: watch ' \
               'their event streams through ' + ', '.join(see)
    return 'slots run hidden, with no window: watch them through ' + ', '.join(see)


PASTE = b'\x1b[200~%s\x1b[201~'  # a bracketed paste


def logged(marker: Path) -> bool:
    """Windows: what the session of `marker` prints goes to its log, so there is no console window to show: it
    runs in a ConPTY pseudo-console, or headless."""
    try:
        spec = json.loads(marker.with_suffix('.job').read_text(encoding='utf-8'))
        return bool(spec.get('conpty') or spec.get('stream'))
    except (OSError, ValueError, AttributeError):
        return False


def send_fifo(inbox: Path, text: str) -> bool:
    """F40: type `text` into a hidden session through the FIFO its shim reads (`run_pty`): a bracketed paste
    (so a newline in it does not send early), then Enter. False when no shim reads it (the session ended)."""
    if plat.WINDOWS:
        return pipe_send(inbox, [PASTE % text.encode('utf-8'), b'\r'], 0.3)
    try:
        fd = os.open(inbox, os.O_WRONLY | os.O_NONBLOCK)  # ENXIO with no reader, rather than hang
    except OSError:
        return False
    try:
        for chunk in (PASTE % text.encode('utf-8'), b'\r'):
            end = time.monotonic() + 10
            while chunk:
                try:
                    chunk = chunk[os.write(fd, chunk):]
                except BlockingIOError:
                    if time.monotonic() > end:
                        return False
                    time.sleep(0.05)
            time.sleep(0.3)  # let the TUI take the paste before Enter, or Enter lands inside it
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def send_fifo_raw(inbox: Path, data: bytes) -> bool:
    """F89: `data` written to a hidden session's FIFO as is, with no bracketed paste and no Enter: a key such
    as Escape (b'\\x1b') reaches the agent the way a key press would. False when no shim reads it."""
    if plat.WINDOWS:
        return pipe_send(inbox, [data])
    try:
        fd = os.open(inbox, os.O_WRONLY | os.O_NONBLOCK)  # ENXIO with no reader, rather than hang
    except OSError:
        return False
    try:
        end = time.monotonic() + 10
        while data:
            try:
                data = data[os.write(fd, data):]
            except BlockingIOError:
                if time.monotonic() > end:
                    return False
                time.sleep(0.05)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


PTY_SIZE = (50, 200)  # rows, columns of a hidden slot's terminal: wide enough that the log reads


def run_pty(argv: list[str], cwd: str, env: dict, marker: Path, logfile: Path | None) -> tuple[int, int]:
    """POSIX: run one agent session in a pseudo-terminal with no window (see HiddenMux), its pid in `marker`
    while it runs; what it prints goes to `logfile`, and what arrives on the FIFO beside the marker (slotN.in)
    is typed into it. F88: it also listens on the socket beside the marker (slotN.sock) for clients that attach
    to the terminal (`attach_session`), removed when the session ends. Returns its exit code and pid once it
    has ended. OSError when the agent cannot be started."""
    import fcntl
    import pty
    import select
    import struct
    import termios
    exe = shutil.which(argv[0], path=env.get('PATH') or os.environ.get('PATH'))
    if not exe:
        raise FileNotFoundError(f'{argv[0]} is not on PATH')
    full = {**os.environ, **env, 'AGENT_RUNNER_MARKER': str(marker)}
    if full.get('TERM', 'dumb') == 'dumb':
        full['TERM'] = 'xterm-256color'
    pid, fd = pty.fork()
    if pid == 0:  # the child: its own session, the pty its controlling terminal
        try:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack('HHHH', *PTY_SIZE, 0, 0))
            os.chdir(cwd)
            os.execve(exe, argv, full)
        except BaseException as e:
            os.write(2, f'could not start {argv[0]}: {e}\n'.encode())
        os._exit(127)
    marker.write_text(str(pid), encoding='utf-8')
    inbox = marker.with_suffix('.in')
    inbox.unlink(missing_ok=True)
    try:
        os.mkfifo(inbox, 0o600)
        inq = os.open(inbox, os.O_RDWR | os.O_NONBLOCK)  # read-write: no EOF when a writer closes it
    except OSError:
        inq = -1
    out = open(logfile, 'ab') if logfile else None
    viewers = Viewers(marker.with_suffix('.sock'), pty_write(fd), pty_resize(fd), PTY_SIZE)  # F88: attached
    code = None
    try:
        while True:
            watch = [fd] + ([inq] if inq >= 0 else []) + viewers.watched()
            r, _, _ = select.select(watch, [], [], viewers.wait(1.0))
            viewers.tick()
            if fd in r:
                try:
                    data = os.read(fd, 65536)
                except OSError:  # EIO: nothing holds the terminal open any more
                    data = b''
                if not data:
                    break
                if out:
                    out.write(data)
                    out.flush()
                viewers.out(data)
            viewers.take(r)
            if inq in r:
                try:
                    os.write(fd, os.read(inq, 65536))
                except OSError:
                    pass
            if not r:
                done, status = os.waitpid(pid, os.WNOHANG)
                if done:  # it ended, but something it started still holds the terminal: stop reading
                    code = os.waitstatus_to_exitcode(status)
                    break
    finally:
        if code is None:
            code = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
        if out:
            out.close()
        viewers.close()
        os.close(fd)
        if inq >= 0:
            os.close(inq)
        inbox.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
    return code, pid


def run_conpty(argv: list[str], cwd: str, env: dict, marker: Path, logfile: Path | None) -> tuple[int, int]:
    """F145, Windows: `run_pty` in a ConPTY pseudo-console: one agent session with no window, its pid in `marker`
    while it runs; what it prints goes to `logfile`, and what arrives on the pipe that slotN.in beside the marker
    names (`conpty.InPipe`) is typed into it; `attach` reaches it as on POSIX (F114). Returns its exit code and pid once it has ended; what it
    started and left in its console ends with it. OSError when the agent cannot be started."""
    exe = shutil.which(argv[0], path=env.get('PATH') or os.environ.get('PATH'))
    if not exe:
        raise FileNotFoundError(f'{argv[0]} is not on PATH')
    out = open(logfile, 'ab', buffering=0) if logfile else None
    inbox = marker.with_suffix('.in')
    inbox.unlink(missing_ok=True)
    pty = typed = viewers = code = None

    def printed(data: bytes) -> None:
        if out:
            out.write(data)
        if viewers:
            viewers.out(data)
    try:
        pty = ConPty([exe, *argv[1:]], cwd, {**os.environ, **env, 'AGENT_RUNNER_MARKER': str(marker)}, PTY_SIZE,
                     printed)
        viewers = Viewers(marker.with_suffix('.sock'), pty.write, pty.resize, PTY_SIZE)
        threading.Thread(target=viewers.serve, daemon=True).start()
        try:
            typed = InPipe(inbox, pty.write)
        except OSError as e:
            print(f'{marker.stem}: no typed input: {e}', flush=True)  # in slotN.shim; it runs all the same
        marker.write_text(str(pty.pid), encoding='utf-8')
        while code is None:
            code = pty.wait(1.0)
    finally:
        if typed:
            typed.close()
        if viewers:
            viewers.close()  # before the console it resizes
        if pty:
            pty.close()
        if out:
            out.close()
        marker.unlink(missing_ok=True)
    return code, pty.pid


def marker_pid(marker: Path) -> int:
    try:
        return int(marker.read_text(encoding='utf-8').strip() or 0)
    except (OSError, ValueError):
        return 0


def run_session(argv: list[str], cwd: str, env: dict, marker: Path) -> tuple[int, int]:
    """Windows with no ConPTY: run one agent session in this (hidden) console, its pid in `marker` while it runs (see
    HiddenMux); its exit code and pid. The agent gets AGENT_RUNNER_MARKER, which is how the Stop hook finds
    the pid to end."""
    proc = sp.Popen(argv, cwd=cwd, env={**os.environ, **env, 'AGENT_RUNNER_MARKER': str(marker)})
    marker.write_text(str(proc.pid), encoding='utf-8')
    try:
        while True:
            try:
                return proc.wait(), proc.pid
            except KeyboardInterrupt:
                continue  # Ctrl-C in the tab is for the agent (it interrupts a turn), not for the shim
    finally:
        marker.unlink(missing_ok=True)


def stream_file(sid: str) -> Path:
    """`<notes>/streams/<sid>.jsonl`: a headless session's event stream (its resumes append to it), which its
    spend is read from (`task_spend`)."""
    d = C.notes('streams')
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{sid}.jsonl'


def slot_shim(job: str) -> int:
    """`run --slot-shim <job>`: what runs a hidden slot (see HiddenMux): a pseudo-terminal on POSIX
    (`run_pty`), a pseudo-console on Windows (`run_conpty`; this console where there is no ConPTY, `run_session`). How the agent ended goes to `slotN.exit`.

    Always exits 0; and a job runs once, so a shim started again does not resume a finished session behind
    the runner's back."""
    f = Path(job)
    spec = json.loads(f.read_text(encoding='utf-8'))
    if spec.get('started'):
        print('This slot\'s session has ended; the runner starts the next one.')
        return 0
    conpty = not spec.get('stream') and plat.has_conpty()
    f.write_text(json.dumps({**spec, 'started': True, **({'conpty': True} if conpty else {})}), encoding='utf-8')
    ended = Path(spec['marker']).with_suffix('.exit')
    try:
        if spec.get('stream'):  # F106b: headless, stream-json in and out
            code, pid = run_stream(spec['argv'], spec['cwd'], spec['env'], Path(spec['marker']),
                                   Path(spec['log']) if spec.get('log') else None, spec.get('brief') or '',
                                   Path(spec['events']) if spec.get('events') else None)
        elif conpty:
            code, pid = run_conpty(spec['argv'], spec['cwd'], spec['env'], Path(spec['marker']),
                                   Path(spec['log']) if spec.get('log') else None)
        elif plat.WINDOWS:
            code, pid = run_session(spec['argv'], spec['cwd'], spec['env'], Path(spec['marker']))
        else:
            code, pid = run_pty(spec['argv'], spec['cwd'], spec['env'], Path(spec['marker']),
                                Path(spec['log']) if spec.get('log') else None)
        ended.write_text(f'exit code {code} (pid {pid})', encoding='utf-8')  # HiddenMux.open reads the pid
    except OSError as e:
        ended.write_text(f'could not start {spec["argv"][0]}: {e}', encoding='utf-8')
        print(f'could not start the agent: {e}')
    return 0


MUX: HiddenMux = HiddenMux()  # every slot runs hidden (C26: on every OS)
MASTER_IDLE = 90     # s a master session sits at its prompt, its answer given, before the Stop hook ends it


# --- watching a session --------------------------------------------------------

TRANSCRIPTS: dict[str, str] = {}  # sid -> its transcript, once found: `stalled` asks every 10 s per slot


def transcript(sid: str) -> str | None:
    if (t := TRANSCRIPTS.get(sid)) and os.path.exists(t):
        return t
    t = backend().find_transcript(sid) or HARNESS.find_transcript(sid)  # F106c: or the harness loop's
    if t:
        TRANSCRIPTS[sid] = t
    return t


def entries(sid: str, skip_bad: bool = False):
    """Session `sid`'s transcript entries, in order; none without a transcript. A line that is not JSON ends
    them (the one being written), or with `skip_bad` is passed over. Every backend's come in Claude's shape."""
    shape = backend().entry
    try:
        with open(transcript(sid) or os.devnull, encoding='utf-8', errors='replace') as f:
            for l in f:
                try:
                    d = json.loads(l)
                except ValueError:
                    if skip_bad:
                        continue
                    return
                if (d := shape(d)) is not None:
                    yield d
    except OSError:
        return


def tmp_roots() -> list[Path]:
    """Where Claude Code keeps its per-session temp folders, `<root>/claude-<uid>/<project>/<session>/`
    (the scratchpad and background tasks' output). It never deletes them, and agents build in them: one
    tmpfs with a per-user quota filled to EDQUOT with 40 GB of finished sessions' cargo target dirs."""
    roots = [os.environ.get('CLAUDE_CODE_TMPDIR'), C.home / 'tmp', tempfile.gettempdir(), '/tmp']
    return list(dict.fromkeys(Path(r) for r in roots if r))


def session_tmp() -> Path:
    """The CLAUDE_CODE_TMPDIR a slot's agent gets: the person's own, else `<home>/tmp` on disk. Claude Code's
    default is /tmp, often a small tmpfs: 12 GB of sessions' scratch there filled a 16 GB one and every
    tool call of every agent failed."""
    d = Path(os.environ.get('CLAUDE_CODE_TMPDIR') or C.home / 'tmp')
    d.mkdir(parents=True, exist_ok=True)
    return d


def claude_json() -> Path:
    cfg_dir = os.environ.get('CLAUDE_CONFIG_DIR')
    return Path(cfg_dir) / '.claude.json' if cfg_dir else Path.home() / '.claude.json'



# --- per-task budgets (F103: [run] task_tokens / task_usd) ------------------------------------------------------

SPEND: dict[str, object] = {}  # sid -> its cost.Spend, read on from where the last look stopped
SPENT: dict[str, list] = {}  # slot -> [tokens, dollars] of its task's session, for STATE and `status`
BUDGET_AT = [0.0]
BUDGET_EVERY = 15  # seconds between two looks at the running sessions' transcripts
BUDGET_HARD = 1.25  # times the cap: a session told to stop that is still spending past this is ended
BUDGET_ENDED: set[str] = set()


def budget_mark(tid: str) -> str:
    """Why the budget stopped `tid` while it ran, for `_finish` (which parks it, unless its done passed)."""
    try:
        return C.notes(f'{tid}.budget').read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def task_spend(sid: str) -> tuple[int, float]:
    """(tokens, dollars) session `sid` and its subagents have used so far; (0, 0.0) without a transcript."""
    from agent_runner.cost import Spend, session_files
    s = SPEND.setdefault(sid, Spend())
    t = transcript(sid)
    for p in session_files(t) if t else []:
        s.add(p)
    if not (ev := C.notes('streams') / f'{sid}.jsonl').exists():
        return s.total() if t else (0, 0.0)
    # F106b: a headless session's event stream, which carries its subagents' turns too. B151: a task begun on
    # the terminal engine and resumed on the stream engine also counts its transcript's earlier turns; claude -p
    # writes the transcript as well, so a turn whose message id is in the stream counts only there (a transcript
    # turn with no id cannot be matched, so it is left out rather than risk counting it twice).
    st = SPEND.setdefault(f'{sid}:stream', Spend())
    st.add(ev)
    seen = {k.rsplit(':', 1)[-1] for k in st.turns}
    tokens, usd = st.total()
    for k, (tk, d) in s.turns.items():
        if (mid := k.rsplit(':', 1)[-1]) not in seen and not mid.startswith('#'):
            tokens, usd = tokens + tk, usd + d
    return tokens, usd


def budgets(procs: dict, running: dict, type_into) -> None:
    """Each running task's spend, kept in SPENT for `status`; one past `[run] task_tokens` or `task_usd` is told
    to stop at a clean point, commit and write its journal (its branch is parked as wip/<ID> when the session
    ends), and ended if it goes on spending to BUDGET_HARD times the cap. One whose `done` passed is left to
    land. `type_into(n, procs, text)` types into slot n's session: None when it went in, else why not."""
    if time.time() - BUDGET_AT[0] < BUDGET_EVERY:
        return
    BUDGET_AT[0] = time.time()
    from agent_runner.brief import BUDGET_STOP
    from agent_runner.cost import over_budget, spend_text
    caps = C.run.get('task_tokens') or 0, C.run.get('task_usd') or 0
    for k in [k for k in SPENT if not k.isdigit() or int(k) not in procs]:
        SPENT.pop(k)
    for n, (pid, sid, _) in list(procs.items()):
        if n not in running:
            continue
        tid = running[n][0]
        tokens, usd = task_spend(sid)
        SPENT[str(n)] = [tokens, round(usd, 2)]
        if not (why := over_budget(tokens, usd, *caps)) or ((m := finished_mark(n)) and m.exists()):
            continue
        mark = C.notes(f'{tid}.budget')
        if not mark.exists():
            mark.write_text(why + '\n', encoding='utf-8')
            if (said := type_into(n, procs, BUDGET_STOP.format(tid=tid, why=why, runner=C.command))) is None:
                log(f'slot {n}: {tid} {why}: told it to stop at a clean point, commit and write its journal; '
                    f'its branch is parked as wip/{tid} when the session ends', None, tid)
            else:
                BUDGET_ENDED.add(sid)
                plat.terminate(pid)
                log(f'slot {n}: {tid} {why}; {said}, so its session is ended and what it did is parked as '
                    f'wip/{tid}', None, tid)
        elif sid not in BUDGET_ENDED and over_budget(tokens, usd, caps[0] * BUDGET_HARD, caps[1] * BUDGET_HARD):
            BUDGET_ENDED.add(sid)
            plat.terminate(pid)
            log(f'slot {n}: {tid} went on to {spend_text(tokens, usd)} after it was told to stop; its session is '
                f'ended and what it did is parked as wip/{tid}', None, tid)
