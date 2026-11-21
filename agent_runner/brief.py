"""What an agent session is told: the slot prompt (`PROMPT`, `OTHERS`, …, `prompt_for`) and the paragraphs
for reviews, wizards and pick sheets it may carry."""

from __future__ import annotations

import os
from pathlib import Path

from agent_runner import plan as P
from agent_runner.gitops import missing_remote
from agent_runner.guide import GLOSSARY, SAFE_SHELL, VERIFY
from agent_runner.state import C, default_branch, git, ROOT


PROMPT = """Unattended run: nobody will answer questions, so never ask one — decide, write down why, and go on.

Do task {tid} and nothing else. You are in a git worktree on branch task/{tid}: commit this repo's work here only. Never \
touch the main checkout, and never merge, rebase or push the main branch. {publish}
{others}{earlier}
Rules: {rules}. {test} """ + GLOSSARY + """
{journal}
Finish with `{runner} done {tid} "<commit message>"`. It runs the test gate, ticks the task, commits and \
pushes, and it refuses to tick when the gate fails. Run it, and any whole test suite, as a background command \
and wait for it to end: beside the other slots a gate can outlast your own command time limit, and one cut \
off there commits nothing. Run one at a time: start another only once the first has ended.

If you are stuck (a tool hangs, the same fix fails twice, it needs a human, about 20 minutes with no \
progress), commit what is solid and run `{runner} done {tid} "<msg>" --blocked "<why + what would unblock \
it>"`, then stop. If all it waits on is another task landing (its code is not on the main branch yet), add \
`--after <ID>[,<ID>]`, and the run reopens it the moment those merge. If it waits on a person, start WHY with \
what you ask of them: `CONFIRM: <what to check by hand>`, `DECIDE: <the question or choice>` or `BLOCKED: \
<the access, login or fix only a person can make>`, then one short line, and the link if there is one; it \
lists under Needs you until they answer. Before a `BLOCKED:` on access, check what this machine already has \
and try it: `gh auth status`, `wrangler whoami`, the service's own CLI login, `ssh -T`, and \
~/.claude/ACCESS.md if it exists; the `BLOCKED:` line then names the exact command that failed and its error \
(e.g. `wrangler OAuth login cannot change Workers Builds settings: Authentication error`).

""" + VERIFY + """

A usage limit is not being stuck: the session waits for the reset and carries on, so do not block the task.

Wait for and stop only processes you started, by the pid you kept (`$!`): `wait` on it, `kill` it. Never \
match processes by a command-line pattern (`pgrep -f`, `pkill -f`, `ps | grep`/`awk`, `killall`): a wait \
loop's pattern matches the loop itself and never ends, and every agent's command line holds this whole \
prompt, so a pattern kill can end the other sessions on this machine. Every wait gets a time limit \
(`timeout 600 <cmd>`, or a deadline in the loop): a loop waiting for a line that a dead process will never \
print runs for ever. Search where the thing can be, not the whole disk (`find /`).

""" + SAFE_SHELL + """ Delete only inside your worktree.

{followups}
{extra}
The task's brief (`{runner} plan brief {tid}`) follows, so don't gather it again.

{brief}"""

FOLLOWUPS = """\
The task list is a tool, not a file to read whole: `{runner} plan` lists the tasks, `{runner} plan <ID>` \
shows one, and `{runner} plan add <KIND> "<text>" --files a,dir/** [--after ID] [--test name] [--pri LEVEL]` files a \
follow-up you find but must not do now: `--files` the files it will change (the run keeps running tasks apart \
by them; name the exact test file, not `tests/**`), `--after` the ids it must wait for; the text is never read for files or ids. Never hand-edit a checkbox. KIND is the id letter for the kind of work: {kinds}. LEVEL is where it queues: \
`critical` only when it breaks or blocks other work (it goes ahead of everything, so its text says what it \
breaks); `normal`, the default, after the work a person queued; `low` for a check or a small tidy-up, after \
normal; `later` for big future work, parked for a person to schedule and never started by a run. To split \
your own task, give its id as KIND (`plan add P17 …` files P17a, P17b…), which keeps its place in the queue. `plan add` \
refuses (exit 3, nothing filed) when an open task looks like the same work: `plan note` that task instead, or add again \
with `--force` if it really is different work. A test that \
fails under load and passes alone is a bug in the test: if one gets in your way, make it robust (what it \
races, not a longer timeout), or file it as critical.
Reference material you write for later sessions (module lists, how-tos, findings) goes in the files \
`{runner} plan "<section>"` searches, under its own heading, not in the rules file every session loads.
"""

OTHERS = ('Other agents are working on other tasks at the same time, in other worktrees. Keep your changes '
          'local: add functions and new files, and don\'t move, rename or reformat code you did not come '
          'for, so the merges stay clean.\n')

PUBLISH = ('When your session ends, the runner merges your branch, tests the merge and publishes it. `{runner} '
           'done` pushes task/{tid} for you, which is the one copy of your work that is not on this disk. Commits '
           'you make in other repositories (a dependency or sibling repo the task needed) are pushed as usual; '
           'never publish beyond git (releases, uploads, stores) unless the task says to.')
NO_REMOTE = ('When your session ends, the runner merges your branch and tests the merge. This repository has no '
             'remote `{remote}` (`[git] push`), so nothing is pushed: your commits and the merge stay on this disk. '
             'Commits you make in other repositories (a dependency or sibling repo the task needed) are pushed as '
             'usual; never publish beyond git (releases, uploads, stores) unless the task says to.')


def no_remote_line(remote: str) -> str:
    """The run's one log line when `[git] push` names a remote this repository does not have (B70)."""
    return (f'[git] push = {remote}: no such remote here, merges stay local; '
            f'git remote add {remote} <url> to publish')


NO_PUSH = ('When your session ends, the runner merges your branch and tests the merge. Pushing is off for this '
           'run: never run `git push`, here or in any other repository, and never publish anything else '
           '(releases, uploads, stores). A human reviews and pushes.')

# With `[git] push = false`, every agent session gets these as git config: any push to a URL of these kinds
# goes to a remote helper that does not exist, so it fails whatever command or repository it comes from.
NO_PUSH_URLS = ('https://', 'http://', 'ssh://', 'git://', 'git@', 'file://')


def brief_for(tid: str, cwd: Path) -> str:
    try:
        plan_dir = C.plan_dir if C.plan_external else cwd / os.path.relpath(C.plan_dir, C.root)
        return '\n'.join(P.brief(tid, root=cwd, plan_dir=plan_dir))
    except SystemExit as e:
        return f'({C.command} plan brief {tid} produced nothing: {e})'


def prompt_for(tid: str, n: int, slots: int, cwd: Path, branch: str) -> str:
    """The first turn of a task's session: `[run] prompt` (a file) if set, else PROMPT, filled in.

    Placeholders a custom template may use: {tid} {n} {runner} {branch} {others} {earlier} {rules} {test}
    {journal} {extra} {followups} {brief}. Any other `{name}` is left as it is. `[run] prompt_extra` may use them too
    (a slot's own emulator, say: "KIT_PCSX2={n} is set").
    """
    r = C.run
    journal = os.path.relpath(C.journal, C.root).replace(os.sep, '/') if C.journal else ''
    journal_at = (f'{journal}/{tid}/notes.md (if it exists, an earlier attempt wrote it: then '
                  f'{journal}/{tid}/<date>-<slug>/notes.md)' if C.raw['plan']['journal_layout'] == 'id'
                  else f'{journal}/<date>-{tid.lower()}-<slug>/')
    wip = not git('rev-parse', '--verify', '-q', f'refs/heads/wip/{tid}').returncode
    vals = dict(
        tid=tid, n=n, runner=C.command, branch=branch,
        publish=(NO_REMOTE if C.push_remote and missing_remote(C.root) else PUBLISH if C.push_remote
                 else NO_PUSH).format(runner=C.command, tid=tid, remote=C.push_remote),
        others=OTHERS if slots > 1 else '',
        earlier=(f'An earlier attempt that could not be merged is on wip/{tid} (`git log {branch}..wip/{tid}`, '
                 f'and the ledger line in {r["notes"]}/ledger.md says why). Read it before starting over.\n'
                 if wip else ''),
        rules=f'read {r["rules"]} first' if r['rules'] else 'the README, and AGENTS.md or CLAUDE.md if there is one',
        test=(f'The test gate is `{r["test"]}`. `done` runs it, and it must pass.' if r['test'] else
              'There is no test gate, so say in the commit message how you checked the work.'),
        journal=(f'\nWrite the task\'s journal as you go, in {journal_at}: what you did, '
                 f'what you tried that failed, and under **Not verified** everything you could not check, with '
                 f'why (or `none`). A skipped check that is written down is useful; a silent one is a bug '
                 f'nobody will find.\n' if journal else ''),
        extra=f'\n{r["prompt_extra"].strip()}\n' if r['prompt_extra'] else '',
        brief=brief_for(tid, cwd),
    )
    kinds, _ = P.kinds()
    vals['followups'] = FOLLOWUPS.format(runner=C.command, kinds='; '.join(f'{k} {v}' for k, v in kinds.items()))
    vals['extra'] = vals['extra'].format_map(_Keep(vals))  # `prompt_extra` may say {n}, {tid}, {runner}
    template = (ROOT / r['prompt']).read_text(encoding='utf-8') if r['prompt'] else PROMPT
    prompt = template.format_map(_Keep(vals))
    policies = []
    if r['include_task_id_in_commit']:
        policies.append(f'Include task ID `{tid}` at the start of the commit subject.')
    else:
        policies.append(f'Do not include task ID `{tid}` in the commit subject; task tracking is separate.')
    if r['comment_policy'] == 'minimal':
        policies.append('Only add comments when necessary to explain non-obvious intent or constraints.')
    if P.concept(tid):
        prompt = f'{prompt.rstrip()}\n\n' + CONCEPT_PROMPT.format(runner=C.command, tid=tid)
    elif wizards_on():
        prompt = f'{prompt.rstrip()}\n\n' + WIZARD_PROMPT.format(
            runner=C.command, tid=tid, template=WIZARD_TEMPLATE, path=C.notes('wizards', f'{tid}.sh'))
    if questionnaires_on() and not P.concept(tid):  # F18
        prompt = f'{prompt.rstrip()}\n\n' + SHEET_PROMPT.format(
            runner=C.command, tid=tid, path=C.notes('sheets', f'{tid}.json'))
    if review_on() and not P.concept(tid):  # a concept task changes no product code: nothing to review
        prompt = f'{prompt.rstrip()}\n\n' + review_prompt(tid, cwd)
    return f'{prompt.rstrip()}\n\nProject policies:\n' + '\n'.join(f'- {policy}' for policy in policies)


CONCEPT_PROMPT = """\
{tid} is a concept task: do not build it. Research the repo (the code, the plan, how similar things are done \
here) and publish one page with the Artifact tool that lays out the options, usually two or three: for each, \
what it looks like or does (a sketch, a mock-up or an example where that says it best), the files it touches, \
and its trade-off; then your recommendation and why. A person picks one from that page, often on a phone, so \
make it short, concrete and readable at a glance. Change no product code; commit only notes you wrote (the \
journal). Finish with `{runner} done {tid} "<msg>" --artifact <the page's URL>`: it is refused without one, and \
it files the build task, blocked until the person approves an option."""


class _Keep(dict):
    def __missing__(self, k: str) -> str:
        return '{' + k + '}'


# --- F17: wizards for BLOCKED items a person must do by hand --------------------------------------------------
#
# A slot agent that blocks with `BLOCKED:` on steps only a person can take (a login, a cert, a secret, a
# dashboard click) also writes a bash wizard to `<notes>/wizards/<ID>.sh`, from `wizard_template.sh` (vendored
# from mattpocock/skills, MIT). Needs you then shows `run: agent-runner wizard <ID>` under the item, and that
# command checks it with `bash -n`, runs it in the main checkout, and on exit 0 confirms the item
# (`plan confirm`). `[run] wizards = false` turns it off: no brief paragraph, no run line.

WIZARD_TEMPLATE = Path(__file__).with_name('wizard_template.sh')

WIZARD_PROMPT = """\
When you block with `BLOCKED:` because of steps only a person can take (a login, a certificate or signing key, \
a secret, a click in a third-party dashboard), also write a wizard that walks them through those steps: copy \
{template} to {path} and replace its example with one `stage` per step, in order (`open_url` before asking \
for what that page shows, `ask_secret` for anything secret, `write_env` / `set_secret` where each value \
belongs, `confirm` before anything irreversible); leave the library above its STAGES marker as it is. Check \
it with `bash -n {path}`; do not run it. Say only what you know of each page or command, not guesses. Write \
one only for steps you cannot do yourself, never for a CONFIRM or a DECIDE, and never put a secret in it. \
Needs you shows the person `{runner} wizard {tid}`, and finishing the wizard confirms the item."""


REVIEW_PROMPT = """\
Spec review, before `done` (after mattpocock/skills code-review, MIT; its Spec axis only): commit your work, \
then give a fresh subagent (the Agent tool; with none, a fresh one-shot session of your agent CLI) only the \
output of `git diff {base}...HEAD` and of `{runner} plan brief {tid}`, nothing of this conversation, and ask it \
for, in under 300 words, each finding quoting the task's words: (a) what the task asked for that is missing or \
partial, (b) what the diff does that was not asked, (c) what looks implemented but wrong. Fix (a) and (c) on \
this branch before `done`, never file them: filing would land known-broken work. Revert (b) from this branch; \
if the extra is worth keeping, file it as a follow-up (`{runner} plan add <KIND> "<what the review found>" \
--files … --pri normal`), and file the same way anything broken outside this task's files or already broken \
before it. Skip the review when the diff is under {min_lines} changed lines (`git diff --shortstat \
{base}...HEAD`, insertions plus deletions) and the task has no long-form brief (plan/tasks/{tid}.md); {long}. \
The commit message passed to `done` ends with exactly one line: `review: nothing`, `review: fixed <what>`, \
`review: filed <IDs>` (with what was fixed too, if any: `review: fixed <what>; filed <IDs>`) or `review: \
skipped (small)`."""


def review_on() -> bool:
    """F28: `[run] review` (default on): the slot prompt asks for a spec review before done."""
    try:
        return C.run.get('review', True) is not False
    except AttributeError:  # no config loaded
        return False


def review_prompt(tid: str, cwd: Path) -> str:
    """REVIEW_PROMPT filled in: the branch the diff is taken against, the skip threshold, and whether this task
    has a long form (then it is reviewed whatever its size)."""
    try:
        base = default_branch()
    except SystemExit:
        base = 'main'
    try:
        plan_dir = C.plan_dir if C.plan_external else cwd / os.path.relpath(C.plan_dir, C.root)
        has_long = P.long_form(plan_dir, tid).exists()
    except (OSError, ValueError):
        has_long = False
    return REVIEW_PROMPT.format(
        base=base, runner=C.command, tid=tid, min_lines=int(C.run.get('review_min_lines', 50)),
        long='this task has one, so review it whatever its size' if has_long else 'this task has none')


def wizards_on() -> bool:
    try:
        return C.run.get('wizards', True) is not False
    except AttributeError:  # no config loaded
        return False


def wizard_file(tid: str) -> Path | None:
    """`<notes>/wizards/<tid>.sh` when wizards are on and one is there, else None."""
    if not wizards_on():
        return None
    try:
        f = C.notes('wizards', f'{tid}.sh')
    except (OSError, SystemExit):
        return None
    return f if f.is_file() else None


def wizard_cmd(tid: str) -> str:
    """The one command Needs you gives for `tid`'s wizard."""
    return f'{C.command} wizard {tid}'


# --- F18: pick sheets for a DECIDE with options (agent_runner/sheet.py) ---------------------------------------
#
# An agent that blocks with `DECIDE:` on a choice writes it as questions with answers to <notes>/sheets/<ID>.json,
# renders the page with `agent-runner sheet <ID> --html FILE`, publishes it (the Artifact tool) and blocks with
# `DECIDE: <summary> <the sheet's url>`. Needs you, the feed and the control brief show one line, '<summary>.
# Pick on the sheet or reply go', and the link. The sheet's Send gives a reply line (`<ID> picks: a=b …`) that
# the session the person talks to passes to `sheet <ID> --picks`; 'go' is `sheet <ID> --go`. Both reopen the
# task (`plan confirm`) with each answer spelled out in its note. `[run] questionnaires = false` turns it off.

SHEET_PROMPT = """\
When you block with `DECIDE:` on a choice (options, a pick-list, settings to change or keep), write the choice \
as a pick sheet, not as a numbered list: no option numbers anywhere. Write {path} as JSON: "title" (a short \
name), "summary" (one line that says what is ready, e.g. "12 config cleanups ready, 10 optional"), "intro" \
(one or two sentences), and "groups": [{{"heading": <a kind of change>, "questions": [{{"id": <short key>, \
"q": <a plain question>, "answers": [<2-3 short answers>], "recommended": <index of your pick>, "keep": \
<index of the answer that changes nothing; leave it out when every answer changes something>, "why": <one or two lines>}}]}}]; `backticks` show as \
code. Check and render it with `{runner} sheet {tid} --html <a file in your scratchpad>`, publish that file \
with the Artifact tool with capabilities {{"db": {{}}}} (its Send writes the picks there), and block with `--blocked "DECIDE: <the summary> <the sheet's url>"`. Needs you shows \
the person that one line and the link; their picks (or 'go' for your recommendations) reopen {tid} with each \
answer in its note."""


def questionnaires_on() -> bool:
    """F18: `[run] questionnaires` (default on): a DECIDE with options is asked as a pick sheet."""
    try:
        return C.run.get('questionnaires', True) is not False
    except (AttributeError, NameError):  # no config loaded
        return False


def has_sheet(tid: str) -> bool:
    """Has `tid` a pick sheet (<notes>/sheets/<tid>.json), with questionnaires on."""
    if not questionnaires_on():
        return False
    try:
        return C.notes('sheets', f'{tid}.json').is_file()
    except (OSError, SystemExit, AttributeError, NameError):
        return False
