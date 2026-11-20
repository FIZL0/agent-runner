"""Slots and sessions: worktrees and panes, the agent backends (Claude Code, Pi), Remote Control, a
slot's environment, starting and resuming a session, disk trimming and the terminals (`TmuxMux`, `ShimMux`)."""

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
import time
import urllib.parse
import uuid
from pathlib import Path

from agent_runner import plan as P, plat
from agent_runner.config import finished_mark, runner_cmd, shown_cmd
from agent_runner.gitops import push
from agent_runner.state import C, clean, git, HIDDEN, hook, log, note, REPO_TAG, ROOT, SLOTS_DIR, TAG
from agent_runner.brief import NO_PUSH_URLS, prompt_for, review_on
from agent_runner.sched import ahead, blocked_tasks, open_tasks, tasks


REMOTE_URL = 'https://claude.ai/code'  # every Remote Control session of the account, slots and control alike


def send_to_pane(pane_id: str, text: str) -> bool:
    """F16: type `text` into tmux pane `pane_id` and press Enter: a bracketed paste (so a newline in it does
    not send early) then Enter, which an interactive Claude Code (or Pi) queues for its next turn while busy."""
    buf = f'agent-runner-{os.getpid()}'
    if tmux('load-buffer', '-b', buf, '-', input=text).returncode:
        return False
    if tmux('paste-buffer', '-d', '-p', '-b', buf, '-t', pane_id).returncode:
        tmux('delete-buffer', '-b', buf)
        return False
    time.sleep(0.3)  # let the TUI take the paste before Enter, or Enter lands inside it
    return not tmux('send-keys', '-t', pane_id, 'Enter').returncode


# --- worktrees and panes -------------------------------------------------------

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


def tmux(*a: str, **kw) -> sp.CompletedProcess:
    return sp.run(['tmux', *a], capture_output=True, text=True, **kw)


def window(kind: str) -> str:
    """This repo's window of `kind` ("agents" or "master"): "agents-openmx", so two repos' runners in one
    tmux session neither share a window nor lay out each other's panes."""
    return f"{kind}-{re.sub(r'[^A-Za-z0-9_-]', '-', ROOT.name)}"


def window_id(name: str) -> str | None:
    """The id (@N) of this tmux session's window called exactly `name`: a name as a target also matches a
    longer one by prefix (agents-openmx would find agents-openmx-mods)."""
    for l in tmux('list-windows', '-F', '#{window_id}\t#{window_name}').stdout.splitlines():
        wid, _, wname = l.partition('\t')
        if wname == name:
            return wid
    return None


def pane(name: str, cwd: Path, cmd: str, env=(), logfile: Path | None = None) -> int:
    """Open cmd in a pane of this repo's window "agents-<repo>", tagged @runner=name and @runner-repo=the
    main checkout, in slot order; returns its pid. The fix and repair sessions (name "master") get a
    window of their own, "master-<repo>", so the slots' layout does not squeeze them to a column.

    Panes are found by their tag rather than their position, so you can break them out, join them or swap
    them around while the run goes on. The pane's output is piped to `logfile`. Raises RuntimeError when
    tmux will not open it.
    """
    envs = [a for e in env for a in ('-e', e)]
    w = window('master' if name == 'master' else 'agents')
    where = ['new-window', '-n', w]
    if name == 'master':
        pass  # a window per session (fixes ahead of the lock run side by side); it closes with it
    elif wid := window_id(w):
        here = sorted((int(h[1:]), p) for p, h in
                      (l.split('\t') for l in tmux('list-panes', '-t', wid, '-F',
                                                   f'#{{pane_id}}\t#{{{TAG}}}').stdout.splitlines())
                      if re.fullmatch(r's\d+', h))
        k = int(name[1:])
        lower = [p for i, p in here if i < k]
        where = (['split-window', '-h', '-t', lower[-1]] if lower else
                 ['split-window', '-h', '-b', '-t', here[0][1] if here else wid])
    r = tmux(*where, '-d', '-c', str(cwd), *envs, '-P', '-F', '#{pane_id} #{pane_pid} #{window_id}', cmd)
    if r.returncode or not r.stdout.split():
        raise RuntimeError(f'tmux could not open a pane: {r.stderr.strip()}')
    pane_id, pid, w = (r.stdout.split() + [w])[:3]
    tmux('set-option', '-p', '-t', pane_id, TAG, name)
    tmux('set-option', '-p', '-t', pane_id, REPO_TAG, str(ROOT))
    tmux('set-option', '-w', '-t', w, 'pane-border-status', 'top')
    tmux('set-option', '-w', '-t', w, 'pane-border-format', f' #{{{TAG}}} ')
    tmux('select-layout', '-t', w, 'even-horizontal')
    if logfile:
        tmux('pipe-pane', '-t', pane_id, '-o', f'cat >> {shlex.quote(str(logfile))}')
    return int(pid)


def panes() -> dict[str, tuple[str, int]]:
    """{name: (pane id, pid)} of this repo's tagged panes in this tmux session: another repo's runner may
    share the session, with slots of the same names, so a pane is ours only when its @runner-repo is this
    main checkout."""
    out = {}
    for l in tmux('list-panes', '-s', '-F', f'#{{pane_id}}\t#{{pane_pid}}\t#{{{TAG}}}\t#{{{REPO_TAG}}}').stdout.splitlines():
        pane_id, pid, name, repo = (l.split('\t') + [''] * 3)[:4]
        if name and pid.isdigit() and repo and Path(repo) == ROOT:
            out[name] = (pane_id, int(pid))
    return out


def session_id(pid: int) -> str | None:
    """The `--session-id` of the agent running as `pid` or its child (the pane's shell may not exec it)."""
    for p in [pid, *plat.children(pid)]:
        if (args := plat.cmdline(p)) is not None and (named := sids(args)):
            return named[0]
    return None


def sids(args: list[str]) -> list[str]:
    """The session ids an agent command line names: `--session-id`'s, then `--resume`'s."""
    return [args[args.index(f) + 1] for f in ('--session-id', '--resume') if f in args[:-1]]


def adopt(branch: str) -> dict[int, tuple]:
    """Sessions an earlier run left going in panes sN: {n: ((pid, sid, since), task)}. A restarted runner
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

def pi() -> bool:
    """`[run] agent` is the Pi coding agent (pi.dev)."""
    return Path(C.run['agent']).stem.lower() == 'pi'


def lean() -> list[str]:
    """Bash/Read/Edit/Write/Artifact and the repo's own settings only: an unattended agent needs no MCP servers, and a
    user-level setting (a status line, a hook that asks) is something nobody is there to answer."""
    if not C.run['lean']:
        return []
    if pi():
        return ['--no-mcp']
    # Artifact: a task can publish a page or screenshots to claude.ai and link it, seen from any device
    # Agent (F28): the spec review before done runs in a fresh subagent
    tools = 'Bash,Read,Edit,Write,Artifact' + (',Agent' if review_on() else '')
    return ['--tools', tools, '--setting-sources', 'project,local', '--strict-mcp-config']


ARG_PROMPT_MAX = 96 * 1024  # Linux's MAX_ARG_STRLEN is 128 KiB for one argument; leave room
ARGV_PROMPT_MAX = 24000  # Windows' CreateProcess takes 32 767 characters, flags and paths included
LONG_BRIEF = 'Your instructions for this session are in your system prompt, under "{marker}". Follow them.'


class Claude:
    """Claude Code: an interactive session ended by its Stop hook once `idle` s at the prompt; the brief is
    the first message; transcripts under ~/.claude/projects, in the shape the rest of the runner reads.

    A backend is everything the runner does differently per agent CLI. To add one, subclass this and
    override what differs, then name it in BACKENDS (and `config.py`'s backend check).
    """
    report_exit = False  # log a session's last words at exit, and fail a sequential run on a nonzero exit

    def flags(self, sid: str, model: str, idle: int, resume: bool, once: bool) -> list[str]:
        stop = [{'hooks': [{'type': 'command', 'command': plat.command_text(
            [*runner_cmd(), 'run', '--stop-hook', '--idle', str(idle)])}]}]
        brief = C.notes(f'{sid}.brief')
        return ['--resume' if resume else '--session-id', sid, '--permission-mode', 'bypassPermissions',
                '--disallowedTools', 'AskUserQuestion', '--model', model, *lean(),
                *(['--append-system-prompt-file', str(brief)] if brief.exists() else []),
                # lean() drops user settings, where the bypass dialog's opt-out lives; nobody is there to answer it
                '--settings', json.dumps({'skipDangerousModePermissionPrompt': True,
                                          'hooks': {'Stop': stop, 'StopFailure': stop},
                                          # on Remote Control a slot's own PushNotification tool stays off (R2:
                                          # inputNeededNotifEnabled is not here, as Claude Code only sends it to
                                          # the server from /config, so --settings never reaches the push)
                                          **({'agentPushNotifEnabled': False}
                                             if remote_slots_on() and silent() is not False else {})})]

    def cmd(self, prompt: str, pf: Path, sid: str, flags: list[str]) -> str:
        """sh reads the prompt file into the one argument (tmux refuses a command over about 16 KB). Past
        ARG_PROMPT_MAX bytes even that fails (Linux takes one argument of 128 KB at most, and the agent
        exits at once, "Argument list too long"), so the brief goes in as the system prompt (`long_brief`)."""
        if len(prompt.encode('utf-8')) > ARG_PROMPT_MAX:
            pf = pf.with_suffix('.cmd-prompt')
            pf.write_text(self.long_brief(prompt, sid), encoding='utf-8')
        return shlex.quote(C.run['agent']) + f' "$(cat {shlex.quote(str(pf))})" ' + shlex.join(flags)

    def argv(self, prompt: str, pf: Path, sid: str, flags: list[str]) -> list[str]:
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
        return [plat.exe(C.run['agent']), '-p', prompt, '--permission-mode', 'bypassPermissions',
                '--disallowedTools', 'AskUserQuestion', '--model', C.run['fix_model'], *lean()]

    def find_transcript(self, sid: str) -> str | None:
        return next(iter(glob.glob(os.path.expanduser(f'~/.claude/projects/*/{sid}.jsonl'))), None)

    def fork_flags(self, sid: str) -> list[str]:
        """Added to a fix session's flags: it starts as a copy of session `sid` (a task's own), from any folder,
        under an id of its own. [] where the backend cannot: the session starts fresh."""
        return ['--resume', sid, '--fork-session'] if self.find_transcript(sid) else []

    def entry(self, d: dict) -> dict | None:
        return d


def pi_argv0() -> list[str]:
    """Pi itself. On Windows its npm `.cmd` shim is skipped: cmd.exe would cut a multi-line prompt short and
    ask "Terminate batch job?" on Ctrl-C, so node runs the CLI the shim names."""
    exe = plat.exe(C.run['agent'])
    if plat.WINDOWS and exe.lower().endswith('.cmd'):
        cli = Path(exe).parent / 'node_modules' / '@earendil-works' / 'pi-coding-agent' / 'dist' / 'bundle' / 'cli.js'
        node = Path(exe).parent / 'node.exe'
        if cli.exists():
            return [str(node) if node.exists() else (shutil.which('node') or 'node'), str(cli)]
    return [exe]


class Pi(Claude):
    """Pi: interactive too, ended by the bundled `pi_idle.ts` extension after `idle` s settled at the prompt
    with nothing in the editor; `once` is print mode (exits after its turn), for a fix session with no pane.
    `pi_hooks.ts` runs the repo's Claude PreToolUse hooks. Pi reads the prompt file itself (`@file`), at any size. Sessions live in `<notes>/pi-sessions`, their
    entries turned into Claude's shape (`entry`)."""
    report_exit = True

    @staticmethod
    def trust(d):
        pass  # Pi asks no folder question

    def flags(self, sid, model, idle, resume, once):
        if resume and not transcript(sid):
            raise FileNotFoundError(f'Pi session {sid} is missing')
        ext = lambda name: ['-e', str(Path(__file__).with_name(name))]
        flags = ext('pi_hooks.ts')  # the repo's Claude PreToolUse guards, in print mode too
        flags += ['--print'] if once else [*ext('pi_idle.ts'), '--runner-idle', str(idle)]
        flags += ['--session-id', sid, '--session-dir', str(C.notes('pi-sessions')), '--approve']
        if model:
            flags += ['--model', model]
        if C.run['lean']:
            shell = 'powershell' if plat.WINDOWS else 'bash'
            flags += ['--tools', f'read,{shell},edit,write', '--no-extensions', '--no-mcp',
                      '--no-skills', '--no-prompt-templates', '--no-themes']
        return flags

    def cmd(self, prompt, pf, sid, flags):
        return shlex.join([*pi_argv0(), *flags, '--', f'@{pf}'])

    def argv(self, prompt, pf, sid, flags):
        return [*pi_argv0(), *flags, '--', f'@{pf}']

    def fix_cmd(self, prompt):
        return agent_argv(prompt, str(uuid.uuid4()), C.run['fix_model'], MASTER_IDLE, 'master', once=True)

    def find_transcript(self, sid):
        return next((str(p) for p in C.notes('pi-sessions').glob(f'*_{sid}.jsonl')), None)

    def fork_flags(self, sid):
        return []  # ponytail: Pi sessions could be copied under a new id; a repair starts fresh there

    def entry(self, entry):
        """A Pi session record as a Claude one: role -> type, Pi's stop reasons and usage keys, and errors
        marked as API errors (transient ones resumable). None for a message that is neither user nor
        assistant. Pi retries rate limits itself, so one that reaches here is not resumed."""
        if entry.get('type') != 'message':
            return entry
        message = entry.get('message', {})
        role = message.get('role')
        if role not in ('user', 'assistant', 'toolResult'):
            return None
        entry['type'] = 'assistant' if role == 'assistant' else 'user'
        message['stop_reason'] = {'stop': 'end_turn', 'toolUse': 'tool_use',
                                  'length': 'max_tokens'}.get(message.get('stopReason'))
        if usage := message.get('usage'):
            message['usage'] = {
                'input_tokens': usage.get('input', 0),
                'cache_read_input_tokens': usage.get('cacheRead', 0),
                'cache_creation_input_tokens': usage.get('cacheWrite', 0),
            }
        if message.get('stopReason') == 'error':
            text = message.get('errorMessage') or 'Pi model request failed'
            entry['isApiErrorMessage'] = True
            permanent = re.search(
                r'\b(?:400|401|403|404|413|422|429)\b|authentication|unauthorized|'
                r'forbidden|billing|rate.?limit|invalid.?request', text, re.I)
            transient = re.search(
                r'network|fetch failed|ECONN|EAI_AGAIN|ETIMEDOUT|timeout|timed? out|'
                r'connection|\b5\d\d\b|overloaded|unavailable', text, re.I)
            entry['error'] = 'server_error' if transient and not permanent else 'invalid_request'
            message['content'] = [{'type': 'text', 'text': text}]
        return entry


BACKENDS = {'claude': Claude(), 'pi': Pi()}


def backend() -> Claude:
    """The configured backend: `[run] backend`, settled by `Config`."""
    return BACKENDS[C.run['backend']]


def agent_flags(sid: str, model: str, idle: int, resume: bool = False, once: bool = False) -> list[str]:
    """The session flags after the prompt. `resume` continues the session `sid` instead of starting it (its
    transcript keeps the id); `once` is a session with no pane, which exits after one answer."""
    return backend().flags(sid, model, idle, resume, once)


REMOTE_ENV_FLAGS = ('CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')


def remote_off_why(dialog: bool = True) -> str:
    """Why `[run] remote = 'auto'` leaves Remote Control off, or '' when it can work: Remote Control is Claude
    Code on a claude.ai login, so not pi, not an API key or token, not Bedrock, Vertex or Foundry,
    not another ANTHROPIC_BASE_URL. `dialog`: also off while Claude Code's one-time "Enable Remote Control?" has
    not been answered yes (`remote_ready` asks it at a terminal), which would hold a session in a hidden pane."""
    if pi():
        return 'backend pi (Remote Control is Claude Code\'s)'
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


def remote_dialog_seen() -> bool:
    try:
        return bool(json.loads(claude_json().read_text(encoding='utf-8')).get('remoteDialogSeen'))
    except (OSError, ValueError, AttributeError):
        return False


def remote_on() -> bool:
    """`[run] remote`, resolved: control sessions and the control server on Remote Control. 'auto' is on when
    `remote_off_why` finds nothing; true forces it (still never for pi); false keeps it off."""
    v = C.run['remote']
    if v == 'auto':
        return not remote_off_why()
    return bool(v) and not pi()


def remote_slots_on() -> bool:
    """`[run] remote_slots`: the slots on Remote Control too (never under 'auto' alone, and never pi)."""
    return C.run['remote_slots'] is True and not pi()


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
    """`[run] remote_slots`: the session shows in claude.ai/code and the Claude apps as "<task title> · <repo> s2 ·
    B646" (the title leads, the id stays for referring to it), where a person can watch it and type to it. Claude
    Code only, and only an interactive session (not Pi).
    (`[run] remote` alone puts only the control sessions there: `control_argv`.)"""
    if not remote_slots_on():
        return []
    tid = git('branch', '--show-current', cwd=cwd).stdout.strip().removeprefix('task/') if cwd else ''
    title = P.titles(C.done, C.todo, width=50).get(tid, '') if tid else ''
    return ['--remote-control', ' · '.join(x for x in (title, f"{ROOT.name} {name.replace('slot', 's')}", tid) if x)]


def agent_cmd(prompt: str, sid: str, model: str, idle: int, name: str, resume: bool = False,
              cwd: Path | None = None) -> str:
    """The agent command line for one task, for sh (tmux, and the POSIX sequential run). The prompt is
    written to `<notes>/<name>.prompt` and goes in from there (`Claude.cmd`, `Pi.cmd`)."""
    pf = C.notes(f'{name}.prompt')
    pf.write_text(prompt, encoding='utf-8')
    return backend().cmd(prompt, pf, sid, agent_flags(sid, model, idle, resume) + remote_flags(name, cwd))


def agent_argv(prompt: str, sid: str, model: str, idle: int, name: str, resume: bool = False,
               once: bool = False, cwd: Path | None = None) -> list[str]:
    """The same command as an argv, for Windows, where no POSIX shell stands between us and the agent. The
    prompt is written to `<notes>/<name>.prompt` all the same."""
    pf = C.notes(f'{name}.prompt')
    pf.write_text(prompt, encoding='utf-8')
    return backend().argv(prompt, pf, sid, agent_flags(sid, model, idle, resume, once) +
                          ([] if once else remote_flags(name, cwd)))


SLOTS = 1  # how many slots this run has; `cmd_run` sets it, for {slots} in `[run] slot_env`


def shared_env() -> list[str]:
    """`[run] slot_env` entries that are not per slot (no {n}), such as a compiler cache, {slots} filled in."""
    return [e.replace('{slots}', str(SLOTS)) for e in C.run['slot_env'] if '{n}' not in e]


def merge_env() -> dict:
    """The merge worktree's gate environment: ours and `shared_env`, so the merge builds the way the slots do."""
    return {**os.environ, **env_vars(shared_env())}


def slot_env(n: int | None) -> list[str]:
    """A slot's environment, as NAME=value: `AGENT_RUNNER=1`; the config file when it came from
    AGENT_RUNNER_CONFIG and every variable `[run] pass_env` names that is set (a tmux pane does not inherit
    the runner's environment, so a wrapper's own variables must be passed on by name); then `[run]
    slot_env` with {n} (the slot) and {slots} filled in. `n=None` is the master window's: `shared_env` in
    place of `[run] slot_env`, so it builds in the merge worktree the way the gate there does."""
    env = ['AGENT_RUNNER=1'] + ([] if n is None else [f'AGENT_RUNNER_SLOT={n}'])  # `finished_mark`
    env.append(f'CLAUDE_CODE_TMPDIR={session_tmp()}')
    if os.environ.get('AGENT_RUNNER_CONFIG') and C.file:
        env.append(f'AGENT_RUNNER_CONFIG={C.file}')
    env += [f'{k}={os.environ[k]}' for k in C.run['pass_env'] if k in os.environ]
    return env + (shared_env() if n is None else [e.format(n=n, slots=SLOTS) for e in C.run['slot_env']]) + \
        [f'{k}={v}' for k, v in no_push_env().items()] + \
        ([f'{PRESENCE_ENV}={quiet_file("slots")}'] if n is not None and remote_slots_on() and silent() is not False
         else [])


# While the file it names exists, Claude Code pulses "client present" just before each push-triggering state
# (needs input, turn done), so the server skips those pushes. It cannot stop the "session ready" push: the server
# sends that as the session registers, before the first pulse (R2, from the Claude Code 2.1.329 binary).
PRESENCE_ENV = 'CLAUDE_CLIENT_PRESENCE_FILE'


def silent() -> bool | str:
    """`[run] silent`: 'launch' (a Remote Control session is quiet only while it starts), True (quiet for good),
    False (no presence file: Claude Code pushes as it would for any session)."""
    return C.run['silent']


def quiet_file(who: str, on: bool = True) -> Path:
    """`<notes>/quiet-<who>`, the file a Remote Control session's CLAUDE_CLIENT_PRESENCE_FILE names: made (`on`) or
    removed. "slots" is kept for good (a slot's later pushes stay quiet; not its start push, see PRESENCE_ENV);
    a control session's and the control server's are there only while it starts, so its later pushes arrive."""
    f = C.notes(f'quiet-{who}')
    try:
        f.touch() if on else f.unlink(missing_ok=True)
    except OSError:
        pass
    return f


def env_vars(env) -> dict[str, str]:
    """NAME=value entries as a dict."""
    return dict(e.split('=', 1) for e in env)


def no_push_env() -> dict[str, str]:
    """With `[git] push = false`: git config, as environment, that makes every push from an agent session fail."""
    if C.push_remote:
        return {}
    count = int(os.environ.get('GIT_CONFIG_COUNT', '0'))
    env = {f'GIT_CONFIG_{part}_{i}': os.environ[f'GIT_CONFIG_{part}_{i}']
           for i in range(count) for part in ('KEY', 'VALUE')}
    env['GIT_CONFIG_COUNT'] = str(count + len(NO_PUSH_URLS))
    for i, url in enumerate(NO_PUSH_URLS, start=count):
        env[f'GIT_CONFIG_KEY_{i}'] = 'url.agent-runner-no-push:.pushInsteadOf'
        env[f'GIT_CONFIG_VALUE_{i}'] = url
    return env


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


def start(n: int, task, branch: str, model: str, idle: int, slots: int):
    tid = task[0]
    finished_mark(n).unlink(missing_ok=True)  # the last task's `done`, not this one's
    d = worktree(n, branch)
    head = git('symbolic-ref', '-q', '--short', 'HEAD', cwd=d).stdout.strip()
    if not vacate(n, d, head, branch, f'for {tid}'):
        return None
    if trim(d, f'slot {n}'):
        worktree(n, branch)  # the `links` the clean took
    co = git('checkout', '-q', '-B', f'task/{tid}', branch, cwd=d)
    if co.returncode:  # e.g. another worktree still holds task/<ID>: never start an agent on the wrong branch
        log(f'slot {n}: checkout task/{tid} failed: {co.stderr.strip()[:200]}')
        return None
    sid = str(uuid.uuid4())
    prompt = prompt_for(tid, n, slots, d, branch)
    logfile, since = slot_header(n, f'{tid} session {sid}')
    if not (pid := MUX.open(n, d, prompt, sid, model, idle, slot_env(n), logfile)):
        log(f'slot {n}: the session for {tid} did not start in {MUX.where(n)}')
        return None
    log(f'slot {n}: {tid} ({task[1]}; {", ".join(sorted(task[2])) or "no files listed"})')
    for where in edited_elsewhere(task[2]):
        log(f'slot {n}: {tid} heads into uncommitted edits outside the runner, in {where}: '
            f'if that is the same work, stop the slot; if not, commit it before {tid} lands')
    return pid, sid, since


RESUME = """The runner resumed this session: it was cut off ({why}). Whatever you had running in the \
background ended with it, and so did anything `[run] on_exit` stops. Look at `git status` and at what you \
did last, then carry on with task {tid} where you left off and finish it as the first message of this \
session says."""


def resume(n: int, tid: str, sid: str, why: str, branch: str, model: str, idle: int):
    """Continue the session `sid` of task `tid` in slot n, where it ran: its transcript names that worktree's
    paths, so no other slot will do. A slot still on task/<tid> is used as it is; one that moved on gets the
    task back from wip/<tid> (the edits the session left, saved when the slot was reset), uncommitted again.
    """
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
    logfile, since = slot_header(n, f'{tid} resume {sid} ({why})')
    if not (pid := MUX.open(n, d, RESUME.format(why=why, tid=tid), sid, model, idle, slot_env(n), logfile,
                            resume=True)):
        log(f'slot {n}: the session for {tid} did not resume in {MUX.where(n)}')
        return None
    log(f'slot {n}: {tid} resumed ({why})')
    return pid, sid, since


# --- terminals: one per slot -----------------------------------------------------

class TmuxMux:
    """tmux panes in this repo's window "agents-<repo>", tagged @runner=sN; the pane's output goes to the
    slot log."""
    name = 'tmux'

    def open(self, n: int, cwd: Path, prompt: str, sid: str, model: str, idle: int, env: list[str],
             logfile: Path, resume: bool = False) -> int | None:
        try:
            return pane(f's{n}', cwd, agent_cmd(prompt, sid, model, idle, f'slot{n}', resume, cwd), env, logfile)
        except RuntimeError as e:
            log(f'slot {n}: {e}')
            return None

    def panes(self) -> dict[str, tuple[str, int]]:
        return panes()

    def session_id(self, pid: int) -> str | None:
        return session_id(pid)

    def where(self, n: int) -> str:
        return f'pane s{n}'


class ShimMux:
    """Windows: a Windows Terminal tab per slot (`wt`), or a console window per slot (`console`).

    Neither hands back the agent's pid the way tmux does: `wt.exe` only asks the running terminal to open
    a tab and exits, and the tab gets the terminal's environment, not ours. So each slot runs through a
    shim (`run --slot-shim <job>`, `slot_shim`): it reads the argv, directory and environment from
    `<notes>/slotN.job`, starts the agent, and keeps its pid in `<notes>/slotN.live` while it runs. The
    loop, a restart's adopt and the Stop hook all read that marker. The console window gets the shim too,
    so the two behave the same. Nothing captures a console's output, so the slot log has only the header
    lines here.
    """

    def __init__(self, name: str):
        self.name = name

    def open(self, n, cwd, prompt, sid, model, idle, env, logfile, resume=False):
        job, marker = C.notes(f'slot{n}.job'), C.notes(f'slot{n}.live')
        ended = marker.with_suffix('.exit')
        marker.unlink(missing_ok=True)
        ended.unlink(missing_ok=True)
        envd = env_vars(env)
        job.write_text(json.dumps({'argv': agent_argv(prompt, sid, model, idle, f'slot{n}', resume, cwd=cwd), 'cwd': str(cwd),
                                   'env': envd, 'marker': str(marker)}), encoding='utf-8')
        shim = [*runner_cmd(), 'run', '--slot-shim', str(job)]
        if self.name == 'wt':
            sp.Popen(['wt.exe', '-w', 'agents', 'new-tab', '--title', f's{n}', '-d', str(cwd), *shim],
                     stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        else:
            plat.spawn_console(shim, cwd, {**os.environ, **envd}, hidden=HIDDEN[0])
        for _ in range(100):
            if pid := marker_pid(marker):
                return pid
            if ended.exists():  # the agent ended before the marker was seen, or never started
                log(f'slot {n}: the agent ended at once: {ended.read_text(encoding="utf-8").strip()[:300]}')
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
        return f'the "s{n}" tab' if self.name == 'wt' else f'the console window of slot {n}'


def marker_pid(marker: Path) -> int:
    try:
        return int(marker.read_text(encoding='utf-8').strip() or 0)
    except (OSError, ValueError):
        return 0


def run_session(argv: list[str], cwd: str, env: dict, marker: Path) -> int:
    """Run one agent session in this terminal, its pid in `marker` while it runs (see ShimMux). The agent
    gets AGENT_RUNNER_MARKER, which is how the Stop hook finds the pid to end on Windows."""
    proc = sp.Popen(argv, cwd=cwd, env={**os.environ, **env, 'AGENT_RUNNER_MARKER': str(marker)})
    marker.write_text(str(proc.pid), encoding='utf-8')
    try:
        while True:
            try:
                return proc.wait()
            except KeyboardInterrupt:
                continue  # Ctrl-C in the tab is for the agent (it interrupts a turn), not for the shim
    finally:
        marker.unlink(missing_ok=True)


def slot_shim(job: str) -> int:
    """`run --slot-shim <job>`: what a Windows tab or console window runs (see ShimMux).

    Always exits 0, so Windows Terminal closes the tab; and a job runs once, so a tab restarted with Enter
    does not resume a finished session behind the runner's back."""
    f = Path(job)
    spec = json.loads(f.read_text(encoding='utf-8'))
    if spec.get('started'):
        print('This slot\'s session has ended; the runner starts the next one. Close this tab.')
        return 0
    f.write_text(json.dumps({**spec, 'started': True}), encoding='utf-8')
    ended = Path(spec['marker']).with_suffix('.exit')
    try:
        code = run_session(spec['argv'], spec['cwd'], spec['env'], Path(spec['marker']))
        ended.write_text(f'exit code {code}', encoding='utf-8')
    except OSError as e:
        ended.write_text(f'could not start {spec["argv"][0]}: {e}', encoding='utf-8')
        print(f'could not start the agent: {e}')
    return 0


MUX: TmuxMux | ShimMux = TmuxMux()  # what `cmd_run` picked
MASTER_IDLE = 90     # s a master session sits at its prompt, its answer given, before the Stop hook ends it


# --- watching a session --------------------------------------------------------

TRANSCRIPTS: dict[str, str] = {}  # sid -> its transcript, once found: `stalled` asks every 10 s per slot


def transcript(sid: str) -> str | None:
    if (t := TRANSCRIPTS.get(sid)) and os.path.exists(t):
        return t
    t = backend().find_transcript(sid)
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


def background_session() -> str:
    """The detached tmux session bare `agent-runner` starts the run in: "ar-<repo>"."""
    return f"ar-{re.sub(r'[^A-Za-z0-9_-]', '-', ROOT.name)}"


def background_env() -> list[str]:
    """NAME=value for the runner in a new tmux session, which gets the tmux server's environment, not this
    shell's: the PATH the agent and git are found on, the runner's and Claude's own variables, `[run] pass_env`."""
    keep = ('PATH', 'VIRTUAL_ENV', *C.run['pass_env'])
    return [f'{k}={v}' for k, v in sorted(os.environ.items())
            if k in keep or k.startswith(('AGENT_RUNNER', 'CLAUDE_', 'ANTHROPIC_'))]


def claude_json() -> Path:
    cfg_dir = os.environ.get('CLAUDE_CONFIG_DIR')
    return Path(cfg_dir) / '.claude.json' if cfg_dir else Path.home() / '.claude.json'


def attach_target(rows: list[str], root: Path, which: str) -> tuple[str, str] | None:
    """(session, pane id) of the runner's pane (`which` "runner") or a tagged pane (s2, master) of the run for
    `root`, from `tmux list-panes -a` rows of session, pane id, @runner, @runner-repo, @runner-run."""
    for l in rows:
        sess, pane_id, name, repo, run_for = (l.split('\t') + [''] * 5)[:5]
        mine = run_for if which == 'runner' else repo if name == which else ''
        if mine and Path(mine) == root:
            return sess, pane_id
    return None
