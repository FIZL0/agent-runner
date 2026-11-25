"""C45: the run page's web.py, the slash commands the composer menu offers.

Part of `web`: `web` runs this file in its own namespace (see its PARTS), so these names are `web`'s, and a test that sets
`web.X` reaches the code here. Not imported on its own."""

# B119: the agent CLI's own slash commands the run app's composer menu offers after the session's skills
BUILTIN_COMMANDS = (  # F170: Claude Code's own, as its 2.1.330 lists them (it keeps them in no file the page can read)
    ('clear', 'Start the conversation over'),
    ('compact', 'Summarise the conversation so far to free context'),
    ('context', 'Show how full the context is'),
    ('cost', 'Show what this session has used'),
    ('model', 'Pick the model'),
    ('memory', 'Edit the memory files'),
    ('help', 'List the commands'),
    ('add-dir', 'Add a working directory'),
    ('advisor', 'Let Claude consult a stronger model at key moments'),
    ('agents', 'Manage the agents'),
    ('artifacts', 'Browse published and shared artifacts'),
    ('autocompact', 'Set how full the context gets before it is summarised'),
    ('background', 'Send the session to the background'),
    ('batch', 'Plan a large change; background agents each open a PR'),
    ('branch', 'Branch the conversation at this point'),
    ('btw', 'Ask a side question without interrupting'),
    ('bug', 'Report a bug'),
    ('cd', 'Move the session to another directory'),
    ('color', "Set the prompt's colour"),
    ('config', 'Open the settings'),
    ('copy', 'Copy the last reply'),
    ('debug', 'Turn on debug logging and look into a problem'),
    ('diff', 'Show the uncommitted changes'),
    ('doctor', "Check Claude Code's setup"),
    ('effort', "Set the model's effort"),
    ('exit', 'Close the session'),
    ('export', 'Export the conversation'),
    ('fast', 'Turn fast mode on or off'),
    ('feedback', 'Send feedback'),
    ('focus', 'Show only the prompt, the summary and the reply'),
    ('fork', 'Copy the conversation into a background session'),
    ('goal', 'Set a goal to check before stopping'),
    ('hooks', 'Show the hooks'),
    ('ide', 'Manage the editor connection'),
    ('init', 'Write a CLAUDE.md for the project'),
    ('insights', 'Report on your sessions'),
    ('keybindings', 'Open the keyboard shortcuts file'),
    ('login', 'Sign in'),
    ('logout', 'Sign out'),
    ('loop', 'Repeat a prompt or command'),
    ('mcp', 'Manage the MCP servers'),
    ('output-style', 'Pick an output style'),
    ('permissions', 'Manage the tool permissions'),
    ('plan', 'Turn on plan mode, or show the plan'),
    ('plugin', 'Manage plugins'),
    ('privacy-settings', 'Show the privacy settings'),
    ('recap', 'Say in one line what this session did'),
    ('release-notes', 'Show the release notes'),
    ('reload-plugins', 'Load changed plugins'),
    ('reload-skills', 'Load changed skills'),
    ('remote-control', 'Control the session from claude.ai/code'),
    ('rename', 'Rename the conversation'),
    ('resume', 'Resume an earlier session'),
    ('rewind', 'Go back to an earlier point'),
    ('sandbox', 'Set up the sandbox'),
    ('security-review', 'Review the changes for security'),
    ('skills', 'List the skills'),
    ('status', 'Show the version, account and servers'),
    ('statusline', 'Set up the status line'),
    ('subtask', 'Send an agent off with the whole context'),
    ('tasks', 'Show the background work'),
    ('theme', 'Pick the theme'),
    ('upgrade', 'Change the plan'),
    ('usage', 'Show the usage'),
    ('workflows', 'Show the workflows'),
)


def skill_description(text: str) -> str:
    """The `description:` line of a SKILL.md or command file's front matter, '' for none."""
    m = re.match(r'---\s*\n(.*?)\n---', text, re.S)
    d = re.search(r'^description:\s*(.+)$', m.group(1), re.M) if m else None
    return d.group(1).strip().strip('"\'') if d else ''


def skill_files(base: Path) -> list[tuple[str, Path]]:
    """[(slash command name, its file)] under a `.claude` folder: skills/<name>/SKILL.md and commands/<name>.md."""
    out = [(f.parent.name, f) for f in sorted(base.glob('skills/*/SKILL.md'))]
    return out + [(f.stem, f) for f in sorted(base.glob('commands/*.md'))]


def slash_commands(session: str = '') -> list[dict]:
    """B119: the slash commands a session takes, for the run app's composer menu: [{'name', 'desc'}]. The control
    session's own skills first (/run /since /follow /control /pause /stop /slots, as guide.control_skills writes
    them), then the agent CLI's built-ins (/clear /compact …), then the project's and the person's own skills and
    commands (`.claude/skills`, `.claude/commands`), each name once. F170: then the skills `session`'s own transcript lists,
    plugin and bundled ones too. F406g: none on the harness loop, which takes no slash commands."""
    try:
        from agent_runner import control_harness
        if control_harness.harness_session(U.session_sid(session)) if session else control_harness.new_chat_model():
            return []
    except Exception:  # noqa: BLE001 - settings that cannot be read are said elsewhere
        pass
    from agent_runner.control import CONTROL_SKILL, control_cmd
    from agent_runner.guide import control_skills
    seen: dict[str, str] = {}
    try:
        cmd = control_cmd()
    except Exception:  # noqa: BLE001 - the runner's path only fills the skills' bodies, not their names or lines
        cmd = 'agent-runner'
    own = control_skills(cmd, CONTROL_SKILL)
    order = ['run', 'since', 'follow', CONTROL_SKILL, 'pause', 'stop', 'slots']
    for name in sorted(own, key=lambda n: (order.index(n) if n in order else len(order), n)):
        seen[name] = re.sub(r'\s*\(the person typed /\S+?(, or [^)]*)?\)\.?$', '', skill_description(own[name]))
    for name, desc in BUILTIN_COMMANDS:
        seen.setdefault(name, desc)
    for base in (Path(S.ROOT) / '.claude', Path.home() / '.claude'):
        for name, f in skill_files(base):
            if name not in seen:
                try:
                    seen[name] = skill_description(f.read_text(encoding='utf-8', errors='replace'))[:120]
                except OSError:
                    continue
    for name, desc in (session_now.session_skills(session) if session else {}).items():
        seen.setdefault(name, desc)
    return [{'name': n, 'desc': d} for n, d in seen.items()]

