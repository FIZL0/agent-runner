"""F166: what the run app's Settings view says of each setting: its name, its description (what it does, then what
changes when it is moved), its group, its home (the place a change is saved) and the parent it appears with.

Every key in `config.DEFAULTS` has a line here; `tests/test_settings.py` checks it. The notes beside DEFAULTS stay the
reference (`agent-runner settings`); these are the words for the person who decides.
"""
from __future__ import annotations

DEVICE, EVERYONE = 'device', 'everyone'  # a home: saved in runner.local.toml at once, or in runner.toml, committed at once

# (group, heading, where it is drawn, what the heading says of its home): 'page' on the page itself, 'advanced' behind
# Advanced, 'file' behind Project file (F448b: edited there too)
GROUPS: tuple[tuple[str, str, str, str], ...] = (
    ('speed', 'Speed and limits', 'page', DEVICE),
    ('landing', 'Landing work', 'page', EVERYONE),
    ('models', 'Models', 'page', EVERYONE),
    ('chats', 'Chats', 'page', DEVICE),
    ('machine', 'Disk and memory', 'advanced', DEVICE),
    ('look', 'This machine', 'advanced', DEVICE),
    ('merge', 'Merging and tests', 'advanced', EVERYONE),
    ('work', 'Tasks and sessions', 'advanced', EVERYONE),
    ('roles', 'More models', 'advanced', EVERYONE),
    ('commands', 'Commands', 'file', EVERYONE),
    ('files', 'Files and folders', 'file', EVERYONE),
    ('patterns', 'Patterns', 'file', EVERYONE),
    ('rules', 'Rules and the plan', 'file', EVERYONE),
)
_WHERE = {g: where for g, _, where, _ in GROUPS}
_HOME = {g: home for g, _, _, home in GROUPS}

# '<table>.<key>': (group, name, description); in the order the page draws them
WORDS: dict[str, tuple[str, str, str]] = {
    # on the page
    'run.slots': ('speed', 'Tasks at once', 'How many tasks are worked on together. More finishes sooner and uses your limit faster.'),
    'run.weekly_max': ('speed', 'Weekly limit', 'New tasks wait once your 7-day Claude usage passes this. Running tasks finish.'),
    'run.session_max': ('speed', '5-hour limit', 'New tasks wait once your 5-hour Claude usage passes this. Running tasks finish.'),
    'git.master_branch': ('landing', 'Working branch', 'The branch finished work is applied to; tasks start from it. Empty: found by itself.'),
    'run.approve': ('landing', 'Ask me before publishing', 'Finished work waits in Needs you until you approve it. Off: it is pushed once its tests pass.'),
    'run.approve_wait': ('landing', 'Wait before asking', 'Minutes with no new related change before you are asked. Longer groups more work into one question.'),
    'run.approve_batch': ('landing', 'Ask at once at', 'This many related changes are put to you at once, without the wait. Lower asks sooner.'),
    'run.approve_diff_lines': ('merge', 'Diff lines shown', 'How many lines of each change\'s diff its Review page shows before it is cut. 0: no diff.'),
    'run.review': ('landing', 'Review each task', 'A second agent checks the work against what you asked. Off: faster, but nothing catches what was missed.'),
    'run.releases': ('landing', 'Manage releases', 'Releases are shown, and you can queue one. Off: nothing about releases shows, and none is queued by itself.'),
    'run.auto_release': ('landing', 'Release by itself', 'A release is queued every so many tasks, when the run goes idle, or both. Both off: you ask for each one.'),
    'git.land_edited': ('landing', 'My unsaved edits are in the way', 'Wait: finished work waits for you. Set aside: your edits move to a branch so it can land.'),
    'run.ci_watch': ('landing', 'Fix failed GitHub checks', 'A check that fails on GitHub is filed as an urgent bug. Off: nobody looks.'),
    'run.issues_watch': ('landing', 'Take GitHub issues', 'Each new open issue becomes a task. Off: issues stay on GitHub.'),
    'run.issues_trust': ('landing', 'Trust what an issue says', 'Check first: the agent confirms it in the code. Do as written: it is done as asked and the issue closed.'),
    'models.provider': ('models', 'Provider', "Where your models run. Opus, sonnet and haiku become its matching models. A model set as provider:model keeps its own."),
    'models.control': ('models', 'Chats', 'The model your chats run on. A stronger one answers better and uses more of your limit.'),
    'models.review': ('models', 'Reviews', 'The model that reviews each task. A cheaper one finds less.'),
    'run.remote': ('chats', 'Steer from the Claude apps', 'Your chats show in the Claude apps on your phone. Auto: on when it can work.'),
    'run.remote_slots': ('chats', 'Slots in the Claude apps', 'When I open one: a slot is listed once you open it. Always: every slot has its own entry.'),
    'run.silent': ('chats', 'No phone alerts', 'Chats stop sending alerts to your phone after their first one. Off: Claude alerts you as usual.'),
    'run.control': ('chats', 'Reopen chats', 'A run brings back chats a shutdown cut off and lets the Claude apps start chats. Off: neither.'),
    'run.control_idle': ('chats', 'Close quiet chats after', 'A chat with nothing said in it this long is closed. Its words are kept.'),
    'run.control_ask': ('chats', 'Move an open question after', 'A chat quiet this long on a question is closed and the question goes to Needs you. Off: it stays open.'),
    'ui.chat_quiet': ('chats', 'Gray out a chat after', 'A chat that needs no reply moves to the bottom of Chats after this long. Off: it keeps its place.'),
    'run.grill': ('chats', 'Questions before a task', 'When I ask: a chat asks you rounds of questions only then. Also big asks: for big vague ones too. Off: never.'),
    'run.questionnaires': ('chats', 'Ask choices on a page', 'A choice is put to you as a page with answers to pick. Off: as a list in text.'),
    'run.voice_learn': ('chats', 'Learn how I word things', 'A chat that had to say something again offers a wording rule to keep. Off: rules are added only when you ask.'),
    'run.needs_order': ('chats', 'Order of Needs you', 'What you see first in Needs you: the oldest, the newest, or the order of the plan.'),
    # advanced
    'run.slot_max_gb': ('machine', 'Biggest worktree', 'A worktree larger than this loses its oldest build output before its next task. 0: never.'),
    'run.min_free_gb': ('machine', 'Minimum free disk', 'Below this, free worktrees are cleaned and new tasks wait. 0: never.'),
    'run.proc_max_gb': ('machine', 'Biggest process', 'A process of the run using more memory than this is ended. Auto: a quarter of the memory. 0: never.'),
    'run.min_free_mem_gb': ('machine', 'Minimum free memory', "Below this, the run's biggest process is ended. 0: never."),
    'run.web': ('look', 'Run page', 'The run serves this page on your network. Off: no page, only the terminal.'),
    'run.web_port': ('look', 'Run page port', 'The port this page is on. With Runner Home, setting one keeps it open beside Home.'),
    'run.web_open': ('look', 'Run page opens on', 'Everywhere: your other devices open this page too. Here: only this computer, by its localhost link. Applies from the next run.'),
    'run.web_https': ('look', 'Run page over https', 'An https address for this page on your tailnet, by Tailscale Serve on the next port. Talk needs https for the mic.'),
    'ui.trusted_networks': ('look', 'Networks with no key', 'Open this page without its key from: a CIDR, tailnet, a host name, or all (careful: no key anywhere). Empty: the key is needed.'),
    'ui.theme': ('look', 'Terminal colors', 'The colors of the terminal page and of a session on this page. Light suits a bright terminal.'),
    'run.auto_upgrade': ('look', 'Update by itself', 'A newer agent-runner is installed, and the run restarts on new code, between merges. Off: only when you press upgrade or restart.'),
    'run.install_skill': ('look', 'Guide for your own sessions', 'Keeps the agent-runner guide where sessions you start find it. Off: they do not know the run.'),
    'run.agent': ('look', 'Claude Code program', 'The program that runs a session: one found on this machine, or another path for a wrapper around Claude Code.'),
    'run.engine': ('look', 'How a slot runs', 'Terminal: a session you can attach to. Stream: no terminal and no Claude apps.'),
    'run.batch_max': ('merge', 'Merge together at most', 'Finished tasks tested as one group, at most this many. 1: one at a time. 0: no limit.'),
    'run.max_unmerged': ('merge', 'Slow down past', 'With more finished tasks than this waiting to merge, slots are left free. 0: never.'),
    'run.full_every_hours': ('merge', 'Whole test every', 'Hours after which the whole test runs again, when a shorter one is used. 0: never.'),
    'run.fix_merges': ('merge', 'Fix merge conflicts', 'A session resolves a conflict. Off: it waits for you.'),
    'run.fix_ahead_max': ('merge', 'Conflicts fixed at once', 'How many are fixed beside other merges. 0: one at a time, while merges wait.'),
    'run.repair_merges': ('merge', 'Repair failed merges', 'A merge that fails its test gets one session to repair it. Off: it goes back at once.'),
    'run.command_timeout': ('merge', 'Longest command', 'Seconds a test or command may take before it counts as failed. Too low fails slow tests.'),
    'git.no_push': ('merge', 'Never push', 'Nothing is pushed, and sessions are refused git push everywhere. Applies from the next run.'),
    'git.pr': ('merge', 'Pull requests', 'Each finished task is a pull request you merge on GitHub; the run merges nothing. Applies from the next run.'),
    'git.pr_max': ('merge', 'Open pull requests', 'No new task starts while this many pull requests are open. 0: no limit.'),
    'git.push_merge': ('merge', 'Push each merge', 'The shared branch is pushed after each merge that passed. Off: you push.'),
    'run.review_min_lines': ('work', 'Smallest change to review', 'A change with fewer lines than this skips the review. Lower reviews more.'),
    'run.split_files': ('work', 'Split busy files', 'When slots stand free because 3 tasks wait for one file, a task to split that file is queued. Off: they wait.'),
    'run.auto_audit': ('work', 'Audit by itself', 'When the run is idle and so many tasks have landed, one looks for what is stale, unused or wasted. Off: none.'),
    'models.audit': ('work', 'Audit model', 'The model that audits what changed, also in an audit you add. A cheaper one finds less.'),
    'run.audit_tokens': ('work', 'Token cap per audit', 'An audit that uses more tokens than this stops and keeps what it found. 0: no cap.'),
    'run.task_tokens': ('work', 'Token cap per task', 'A task that uses more tokens than this stops and is parked. 0: no cap.'),
    'run.task_usd': ('work', 'Dollar cap per task', 'A task that costs more than this at list price stops and is parked. 0: no cap.'),
    'run.context_warn': ('work', 'Warn about a full session', 'A session larger than this many thousand tokens is named in the log and told once to finish. Nothing stops. 0: never.'),
    'run.task_size': ('work', 'Split tasks bigger than', 'Counts code files, numbered outcomes and text. A bigger task is split into parts. 0: never.'),
    'run.lean': ('work', 'Lean sessions', 'Tasks get only the tools they need, without your plugins and settings. Off: they load everything and use more.'),
    'run.include_task_id_in_commit': ('work', 'Task id in commits', "Each commit's title starts with its task's id. Off: it does not."),
    'run.rules_pointer': ('work', 'Guide line in the rules file', 'A run adds one line to the rules file that points at its guide. Off: the file is left alone.'),
    'plan.need_files': ('work', 'Tasks must name files', 'A new task without files or a test is refused. Off: it is taken, but may clash with others.'),
    'plan.context_kb': ('work', 'Warn about long rules', 'Kilobytes of rules every session loads before the run warns you. 0: never.'),
    'plan.lessons': ('work', 'Lessons', "What agents learned about some files, shown to the next task on them. Off: none kept or shown."),
    'models.kinds': ('roles', 'Model for each kind', 'The model a task runs on, by the letter of its id. It wins over Other tasks.'),
    'models.sizes': ('roles', 'Model for each size', 'The model for a task marked simple or complex, like { simple = "sonnet" }. It wins over its kind. Empty: sizes are ignored.'),
    'models.code': ('roles', 'Other tasks', 'The model for a task whose kind has none. Every kind has one, so this rarely changes anything.'),
    'models.fix': ('roles', 'Conflict fixes', 'The model that resolves conflicts and repairs merges. A cheaper one fails more often.'),
    'models.docs': ('roles', 'Docs helper', 'The model that writes docs and changelog lines for a task. Off: the task writes them itself.'),
    'models.feed': ('roles', 'Run page copy', 'The model that publishes the run page copy on claude.ai. It is short work, so a cheap one does it.'),
    'models.fallback': ('roles', 'When a limit is reached', 'Other models a task goes on with at a limit, in order. Empty: it waits for the reset.'),
    'models.local': ('roles', 'Allow local models', 'Lets a role name a model that runs on your own network. Off: such a name is refused.'),
    'models.tiers': ('roles', 'Opus, sonnet and haiku elsewhere', "The model each name means on another provider, like { copilot = { opus = \"claude-opus-5.5\" } }. Empty: the built-in ones."),
    # the project file, read only here
    'run.test': ('commands', 'Test command', 'Every task and merge must pass it. Empty: nothing is tested.'),
    'run.done_test': ('commands', 'Test before a commit', 'What a task must pass before its commit, in place of the test command. A merge still runs that. Empty: the test command.'),
    'run.test_since': ('commands', 'Quick test', 'Tests only what changed, at a merge. Empty: the whole test every time.'),
    'run.retest': ('commands', 'Test again', 'Runs only the tests that failed, to tell a real failure from load. Empty: a failure is taken as real.'),
    'run.build': ('commands', 'Build check', 'A quick build a conflict fix must pass before it is committed. Empty: only the whole test checks it.'),
    'run.docs_check': ('commands', 'Docs check', 'Runs in place of the test when only docs changed. Empty: nothing runs.'),
    'run.before_start': ('commands', 'Before a task', 'Must succeed before a task starts. The slot waits for it.'),
    'run.on_exit': ('commands', 'After a session', "Runs in the slot's folder when its session ends. Empty: nothing runs."),
    'run.slot_clean': ('commands', 'Clean a worktree', 'Runs in place of the built-in cleaning when disk is short. Empty: the built-in one runs.'),
    'run.command': ('commands', 'Runner command', 'What sessions type to reach the runner. Empty: this runner.'),
    'run.tools': ('commands', 'Shared tools', 'Things only one task can use at a time, like a test phone: how to check each, its web page and buttons. Empty: none.'),
    'run.checks': ('commands', 'Until checks', 'Commands that say whether what a blocked task waits on has come. Empty: none.'),
    'run.join': ('commands', 'Join a file', 'Commands that join a conflict in a kind of file by themselves. Empty: a fix session does it.'),
    'plan.brief_extra': ('commands', 'Added to a brief', "A command whose output ends each task's brief. Empty: nothing is added."),
    'plan.outline': ('commands', 'File outline', "A command that lists a file's parts, shown in the brief. Empty: none is shown."),
    'run.home': ('files', "Runner's folder", "Where this project's worktrees and plan copy are kept. Moving it starts new worktrees there."),
    'run.notes': ('files', 'Log folder', "Where the run's logs are kept. Git ignores it."),
    'run.links': ('files', 'Linked files', 'Ignored files every worktree shares, such as big data. A worktree without its link misses those files.'),
    'run.copies': ('files', 'Copied files', 'Ignored files each new worktree gets its own copy of. A change in one worktree stays there.'),
    'run.slot_env': ('files', 'Slot variables', 'Extra environment variables each slot gets. Empty: only the slot number.'),
    'run.pass_env': ('files', 'Passed variables', "Names of the runner's own variables that slots also get. One not named here does not reach a slot."),
    'run.shared_files': ('files', 'Shared files', 'Files nearly every task changes. Two tasks may name one and still run together.'),
    'run.joinable': ('files', 'Files joined by line', 'Files with one record a line, where a conflict keeps both sides. Other files need a fix session.'),
    'git.push': ('files', 'Push to', 'Where finished work is pushed. Off: nothing is pushed.'),
    'plan.dir': ('files', 'Plan folder', 'Where the task list is kept. Outside the project, every checkout shares it.'),
    'plan.repo': ('files', 'Plan repository', 'A git repository of its own for the task list. Empty: it is in this one.'),
    'plan.journal': ('files', 'Journal folder', 'Notes kept per task and shown in its brief. Empty: none.'),
    'plan.journal_layout': ('files', 'Journal layout', 'How journal folders are named: by date, or by task id.'),
    'run.untested': ('patterns', 'Files tests cannot see', 'A merge that differs only in these is not tested again. Too wide lets untested changes land.'),
    'run.docs_files': ('patterns', 'Docs files', 'A change to only these skips the test. Too wide lets code skip it.'),
    'run.findings': ('patterns', 'Research files', 'The files a research task may change. A change to any other file is not merged.'),
    'run.failures': ('patterns', 'Failed test names', "Finds the failing tests' names in the test's output. Empty: a failure is not looked into."),
    'run.flaky': ('patterns', 'Flaky test names', 'Finds tests that passed only on a second try, to file them. Empty: none are filed.'),
    'run.suspect': ('patterns', 'Suspect block lines', 'Flags a block line that matches it in the log. Empty: none is flagged.'),
    'run.not_attempt': ('patterns', 'Not an attempt', "A first commit that matches does not count as the task's one try. Empty: every session counts."),
    'run.rules': ('rules', 'Rules file', "The project's rules every task is pointed at. Empty: none."),
    'run.prompt': ('rules', 'Task prompt', 'A file that replaces the built-in prompt. Empty: the built-in one.'),
    'run.prompt_extra': ('rules', 'Added to the prompt', 'A paragraph every task gets. Empty: nothing is added.'),
    'run.voice': ('rules', 'Wording file', 'Your rules for how sessions word things. Empty: the one in your home folder.'),
    'plan.glossary': ('rules', 'Glossary', "The project's words, named in every brief. Off: none."),
    'plan.lookup': ('rules', 'Files to look things up in', 'More files the plan tool searches for a heading. Empty: only its own files.'),
    'plan.kinds': ('rules', 'Kinds of task', 'What each id letter means. Empty: the built-in list.'),
    'models.providers': ('rules', 'Model providers', 'Other services a model can come from. A key is never kept here, only its variable name.'),
}

# not its group's home
_HOMES: dict[str, str] = {'git.land_edited': DEVICE, 'run.questionnaires': EVERYONE, 'run.grill': EVERYONE, 'run.web_open': DEVICE}
# shown only while its parent is on
_PARENTS: dict[str, str] = {
    'run.approve_wait': 'run.approve', 'run.approve_batch': 'run.approve', 'run.approve_diff_lines': 'run.approve', 'run.issues_trust': 'run.issues_watch',
    'git.pr_max': 'git.pr',
    'run.review_min_lines': 'run.review', 'run.web_port': 'run.web', 'run.web_https': 'run.web', 'run.web_open': 'run.web',
    'run.fix_ahead_max': 'run.fix_merges', 'models.review': 'run.review', 'run.auto_release': 'run.releases',
}
# a choice in words: value -> what its control says
_CHOICES: dict[str, dict[str, str]] = {
    'git.land_edited': {'wait': 'Wait', 'wip': 'Set aside'},
    'run.issues_trust': {'skeptical': 'Check first', 'trust': 'Do as written'},
    'run.remote': {'auto': 'Auto', 'true': 'On', 'false': 'Off'},
    'run.remote_slots': {'open': 'When I open one', 'always': 'Always'},
    'run.grill': {'ask': 'When I ask', 'big': 'Also big asks', 'off': 'Off'},
    'run.voice_learn': {'ask': 'Offer', 'off': 'Off'},
    'run.needs_order': {'oldest': 'Oldest first', 'newest': 'Newest first', 'plan': "The plan's"},
    'run.engine': {'terminal': 'Terminal', 'stream': 'Stream'},
    'run.ci_watch': {'auto': 'On', 'false': 'Off'},
    'run.issues_watch': {'true': 'On', 'false': 'Off'},
    'run.control_idle': {'1h': '1 hour', '3h': '3 hours', '6h': '6 hours', '12h': '12 hours', 'false': 'Never'},
    'run.control_ask': {'1h': '1 hour', '2h': '2 hours', '6h': '6 hours', '12h': '12 hours', 'false': 'Off'},
    'ui.chat_quiet': {'1h': '1 hour', '3h': '3 hours', '6h': '6 hours', '12h': '12 hours', '1d': '1 day', 'false': 'Off'},
    'models.provider': {'claude': 'Claude Code', 'copilot': 'GitHub Copilot', 'codex': 'Codex', 'gemini': 'Gemini', 'ollama': 'Ollama'},
    'models.control': {'opus': 'opus', 'sonnet': 'sonnet', 'haiku': 'haiku'},
    'models.review': {'opus': 'opus', 'sonnet': 'sonnet', 'haiku': 'haiku'},
}
# F174: a table value set by two controls on its row: each one's label, and a count's choices. F422: with 'on', the switch
# turns the count on at its 'every'
_PARTS: dict[str, dict] = {
    'run.auto_release': {'every': {'label': 'Every', 'counts': [5, 10, 20], 'unit': 'tasks'}, 'idle': {'label': 'When idle'}},
    'run.auto_audit': {'on': {'label': 'On', 'every': 50}, 'every': {'label': 'Every', 'counts': [25, 50, 100], 'unit': 'tasks'}},
}
_UNITS: dict[str, str] = {
    'run.weekly_max': '%', 'run.session_max': '%', 'run.approve_wait': 'min', 'run.slot_max_gb': 'GB',
    'run.min_free_gb': 'GB', 'run.proc_max_gb': 'GB', 'run.min_free_mem_gb': 'GB', 'run.full_every_hours': 'h',
    'run.command_timeout': 's', 'run.task_usd': '$', 'run.context_warn': 'k tokens', 'plan.context_kb': 'KB',
}

# F448a: a sentence on what a risky change of a 'file' group setting does
_WARNS: dict[str, str] = {
    'run.test': 'Every task and merge uses it at once: one that always fails lands nothing, one that always passes lands anything.',
    'run.done_test': 'Every running task has to pass it from now on: one that always fails lets no task finish.',
    'run.test_since': 'A command that tests too little lets broken work land until the next whole test.',
    'run.retest': 'A command that always passes makes every failed test count as load, so broken work lands.',
    'run.build': 'A command that always fails leaves every conflict for you.',
    'run.docs_check': 'A command that always fails holds back every docs change.',
    'run.before_start': 'While it fails, no task starts.',
    'run.on_exit': 'It runs in the worktree after every session, and what it deletes there is gone.',
    'run.slot_clean': 'It runs in worktrees when disk is short, and what it deletes there is gone.',
    'run.command': 'Every session reaches the runner by it: a wrong one lets no task finish.',
    'run.tools': 'A check that always fails keeps the tasks that need the tool waiting.',
    'run.checks': 'A blocked task that waits on a check no longer here goes on waiting.',
    'run.join': 'A command that joins wrongly loses lines, and nobody looks.',
    'plan.brief_extra': 'It runs each time a brief is made: a slow one holds every start.',
    'plan.outline': 'It runs for each long file in a brief: a slow one holds every start.',
    'run.home': 'The next run makes new worktrees there, and the old folder stays on the disk until you delete it.',
    'run.notes': 'A folder without the old logs loses the open questions, approvals and history.',
    'run.links': 'Too wide a pattern shares files between worktrees that each needs its own of.',
    'run.copies': 'A copy that is in a worktree already is never renewed.',
    'run.slot_env': 'A variable that tests need and that goes away here fails them in every slot.',
    'run.pass_env': 'A variable that tests need and that goes away here fails them in every slot.',
    'run.shared_files': 'Tasks that change a file named here run together, and their merges may conflict.',
    'run.joinable': 'Both sides of a conflict are kept and nobody looks, which breaks code and prose.',
    'git.push': 'Off, finished work stays on this machine.',
    'plan.dir': 'Chats use the task list there at once, and the run from its next start.',
    'plan.repo': 'Chats use the task list there at once, and the run from its next start.',
    'plan.journal': 'Notes in the old folder are no longer shown in briefs.',
    'plan.journal_layout': 'Notes named the other way are no longer found.',
    'run.untested': 'A pattern that matches code lets broken work land.',
    'run.docs_files': 'A pattern that matches code lets broken work land.',
    'run.findings': 'A research task may change and land every file that matches.',
    'run.failures': 'A pattern that misses names takes a test that failed from load as a real failure.',
    'run.flaky': 'A pattern that matches too much files an urgent task for each name it finds.',
    'run.not_attempt': 'A pattern that matches too much starts the same task again and again.',
    'run.rules': 'Sessions that start from now on follow that file, and no longer the one before.',
    'run.prompt': 'It replaces all that sessions are told: what it leaves out, they do not know.',
    'run.prompt_extra': 'Every task that starts from now on gets it.',
    'plan.kinds': 'A letter that goes away takes no new tasks.',
    'models.providers': 'No model of a provider that goes away can be picked.',
}


def _of(table: str, key: str) -> tuple[str, str, str]:
    return WORDS.get(f'{table}.{key}', ('work', key, ''))


def group(table: str, key: str) -> str:
    return _of(table, key)[0]


def name(table: str, key: str) -> str:
    return _of(table, key)[1]


def desc(table: str, key: str) -> str:
    return _of(table, key)[2]


def home(table: str, key: str) -> str:
    """Where a change is saved: DEVICE or EVERYONE."""
    return _HOMES.get(f'{table}.{key}') or _HOME[group(table, key)]


def parent(table: str, key: str) -> str:
    """The setting it appears with, as '<table>.<key>' ('' for none)."""
    return _PARENTS.get(f'{table}.{key}', '')


def words(table: str, key: str) -> dict[str, str]:
    """A pick's values (as JSON reads them, a string bare) and what the control says for each; {} when typed."""
    return _CHOICES.get(f'{table}.{key}', {})


def parts(table: str, key: str) -> dict:
    """The controls that set a table value together (`_PARTS`); {} when one control sets it."""
    return _PARTS.get(f'{table}.{key}', {})


def unit(table: str, key: str) -> str:
    return _UNITS.get(f'{table}.{key}', '')


def warn(table: str, key: str) -> str:
    """What a risky change of it does, in a sentence ('' when it risks nothing)."""
    return _WARNS.get(f'{table}.{key}', '')


def order(table: str, key: str) -> int:
    """Its place on the page."""
    return list(WORDS).index(f'{table}.{key}') if f'{table}.{key}' in WORDS else len(WORDS)
