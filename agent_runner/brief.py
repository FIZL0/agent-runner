"""What an agent session is told: the slot prompt (`PROMPT`, `OTHERS`, …, `prompt_for`) and the paragraphs
for reviews, asks and pick sheets it may carry."""

from __future__ import annotations

import os
from pathlib import Path

from agent_runner import audit, pitch, plan as P, shared_tools
from agent_runner.gitops import missing_remote
from agent_runner.guide import GLOSSARY, OWN_FILES, SAFE_SHELL, SPLIT_FILES, VERIFY
from agent_runner.state import C, default_branch, git, ROOT


PROMPT = """Unattended run: nobody is here to answer in this chat, so never ask a question here — decide, write \
down why, and go on. Only for what you truly cannot decide or check, `{runner} ask` (below).

Do the one task named at the end of this brief, and nothing else; `<ID>` below stands for its id. You are in a git \
worktree on branch task/<ID>: commit this repo's work here only. Never \
touch the main checkout, and never merge, rebase or push the main branch. {publish}
{others}
Rules: {rules}. {test} """ + GLOSSARY + """
{journal}
Finish with `{runner} done <ID> "<commit message>"`. It runs the test gate, ticks the task, commits and \
pushes, and it refuses to tick when the gate fails. Run it, and any whole test suite, as a background command \
and wait for it to end: beside the other slots a gate can outlast your own command time limit, and one cut \
off there commits nothing. Run one at a time: start another only once the first has ended.

A command stopped for low memory ("the system is running low on memory ... start it again only when asked") is \
never a reason to `ask` or to block, and never a decision for the person: this is their standing go-ahead to run it \
again. Commit what is solid, run `{runner} wait-for memory`, and do what it says: either memory is free and you run \
the command again, or you stop, your slot is given up, and this session goes on by itself once memory is free.

If you are stuck (a tool hangs, the same fix fails twice, it needs a human, about 20 minutes with no \
progress), commit what is solid and run `{runner} done <ID> "<msg>" --blocked "<why + what would unblock \
it>"`, then stop. If all it waits on is another task landing (its code is not on the main branch yet), add \
`--after <ID>[,<ID>]`, and the run reopens it the moment those merge; a WHY that waits on a task takes no label. If it waits on a person, start WHY with \
what you ask of them: `CONFIRM: <what to check by hand>`, `DECIDE: <the question or choice>` or `BLOCKED: \
<the access, login or fix only a person can make>`, then one short sentence, at most about 100 characters, and the link if there is one; the rest \
goes in the ask file (under "What you ask of a person"). It lists under Needs you until they answer. `CONFIRM:` is only for a check by hand you cannot do yourself, never \
to have a finished task marked done: run `done` without `--blocked` for that. Before a `BLOCKED:` on access, check what this machine already has \
and try it: `gh auth status`, `wrangler whoami`, the service's own CLI login, `ssh -T`, and \
~/.claude/ACCESS.md if it exists; the `BLOCKED:` line then names, after what the person does, the exact command that failed and its error \
(e.g. `BLOCKED: Log in to Cloudflare again; wrangler OAuth login cannot change Workers Builds settings: Authentication error`).

When the task's deliverable is itself for a person's eyes outside the code (a video, pictures, a post, a document), add \
`--ready "<what is ready: what to do>"` (e.g. "Showcase video is ready: watch it"; `--ready-link <URL>` for where it is) \
to `done`: the task still ticks, and once it lands the person answers it under Needs you; its pictures or video go in \
the ask file named `ready-<ID>.json`. Not for a check's screenshots, nor beside a concept page or a `CONFIRM:`.

Once `done` has run (or `done --blocked`), run `{runner} finish "<one line: what you did>"` and stop: it \
records the summary and ends this session at once. If you hit a question only a person can answer and the work \
should go on afterwards with what you know now, run `{runner} ask "<the question, with what you recommend, one short sentence>"` \
(the rest in the ask file) and stop: the task is parked under Needs you with your worktree as it is, and the person's answer comes back as the \
next message of this same session. Your AskUserQuestion tool is off; `ask` is the only way to ask. To show \
the person a page (a concept's options, a report), run `{runner} publish-page <the HTML file>`: the run page \
shows it, and it prints the page's claude.ai URL.

""" + VERIFY + """ What you do hand over, write in short steps (under "What you ask of a person").

A usage limit is not being stuck: the session waits for the reset and carries on, so do not block the task.

Wait for and stop only processes you started, by the pid you kept (`$!`): `wait` on it, `kill` it. Never \
match processes by a command-line pattern (`pgrep -f`, `pkill -f`, `ps | grep`/`awk`, `killall`): a wait \
loop's pattern matches the loop itself and never ends, and every agent's command line holds this whole \
prompt, so a pattern kill can end the other sessions on this machine. Every wait gets a time limit \
(`timeout 600 <cmd>`, or a deadline in the loop): a loop waiting for a line that a dead process will never \
print runs for ever. Search where the thing can be, not the whole disk (`find /`).

""" + SAFE_SHELL + """ Delete only inside your worktree.

{followups}"""

# F103: what differs from task to task comes after PROMPT, the task's own brief last, so every slot's first turn
# starts with the same text and the model's prompt cache is reused across slots and tasks.
TASK_PROMPT = """\
Your task is {tid}: `<ID>` above is {tid}, and your branch is task/{tid}.
{earlier}{extra}"""

BRIEF_LAST = """\
The task's brief (`{runner} plan brief {tid}`) follows, so don't gather it again.

{brief}"""

FOLLOWUPS = """\
The task list is a tool, not a file to read whole: `{runner} plan` lists the tasks, `{runner} plan <ID>` \
shows one, and `{runner} plan add <KIND> "<text>" --files a,dir/** [--after ID] [--test name] [--pri LEVEL]` files a \
follow-up you find but must not do now: `--files` the files it will change (the run keeps running tasks apart \
by them; name the exact test file, not `tests/**`), `--after` the ids it must wait for; the text is never read for files or ids. Never hand-edit a checkbox. KIND is the id letter for the kind of work: {kinds}. LEVEL is where it queues: \
`critical` only when it breaks or blocks other work (it goes ahead of everything, so its text says what it \
breaks); `high` only when a person asked for high priority (after critical, ahead of the rest); `normal`, the default, after the work a person queued; `low` for a check or a small tidy-up, after \
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


APPROVE = ('When your session ends, the runner merges your branch and tests the merge. A person approves it before it '
           'is pushed (`[run] approve`), so nothing is pushed yet, and `{runner} done` pushes nothing: never run '
           '`git push` in this repository. Commits you make in other repositories (a dependency or sibling repo the '
           'task needed) are pushed as usual; never publish beyond git (releases, uploads, stores) unless the task '
           'says to.')
PR_MODE = ('When your session ends, the runner tests your branch with main merged in, pushes it and opens a pull request '
           '(`[git] pr`). A person merges that: the runner never merges and never pushes main, and neither do you, with '
           '`git` or `gh`, in this repository. Commits you make in other repositories (a dependency or sibling repo the '
           'task needed) are pushed as usual; never publish beyond git (releases, uploads, stores) unless the task says to.')
PR_PROMPT = ('Before `done`, write `{path}` for the person who reviews the pull request, as JSON: "what": what it changes; '
             '"why": why; "try": how to try it; "risk": what it might break. `done` refuses without all four, or without '
             'the `review: …` line that ends its message.')
PITCH_PROMPT = ('Before `done`, write `{path}` for the person who approves the push: they use the product, and do not '
                'review code. JSON, plain words, no code talk; `backticks` show as code. "what": what it changes for '
                'them; "why": why they would want it; "try": how to try it now (the page or command to open); "risk": '
                'what it might break; and for a change to a screen "before" and "after": words, or the name of an '
                'image you put beside that file. `done` refuses without the first four.')
NO_PUSH = ('When your session ends, the runner merges your branch and tests the merge. Pushing is off for this '
           'run: never run `git push`, here or in any other repository, and never publish anything else '
           '(releases, uploads, stores). A human reviews and pushes.')


def plan_at(cwd: Path) -> Path:
    """The plan directory a session in worktree `cwd` reads and changes."""
    return C.plan_dir if C.plan_external else cwd / os.path.relpath(C.plan_dir, C.root)


def brief_for(tid: str, cwd: Path) -> str:
    try:
        return '\n'.join(P.brief(tid, root=cwd, plan_dir=plan_at(cwd)))
    except SystemExit as e:
        # B869: a worktree started on a base older than the task (a merge ahead, a task filed on main since) has no
        # line for it in its own plan; the main checkout's plan has, so the session still gets its brief.
        if not C.plan_external and Path(cwd).resolve() != Path(C.root).resolve():
            try:
                return '\n'.join(P.brief(tid, root=cwd, plan_dir=C.plan_dir))
            except SystemExit:
                pass
        return f'({C.command} plan brief {tid} produced nothing: {e})'


def prompt_for(tid: str, n: int, slots: int, cwd: Path, branch: str, model: str = '') -> str:
    """The first turn of a task's session: `[run] prompt` (a file) if set, else PROMPT, filled in.

    Placeholders a custom template may use: {tid} {n} {runner} {branch} {others} {earlier} {rules} {test}
    {journal} {extra} {followups} {brief}. Any other `{name}` is left as it is. `[run] prompt_extra` may use them too
    (a slot's own emulator, say: "KIT_PCSX2={n} is set").

    F103: the built-in prompt is the same for every task up to TASK_PROMPT (its id, an earlier attempt,
    `prompt_extra`), then the task's paragraphs and policies, and the task's brief last, so the model's prompt
    cache is reused across slots. A custom template keeps its own order.

    F132: `model` is the session's settled model; on another provider's (the harness loop, which has no Agent
    tool) the brief leaves out the docs subagent; F406e: its spec review is `run review`, a one-shot on [models] review.
    """
    r = C.run
    loop = harness_session(model)
    journal = os.path.relpath(C.journal, C.root).replace(os.sep, '/') if C.journal else ''

    def journal_text(t: str) -> str:
        at = (f'{journal}/{t}/notes.md (if it exists, an earlier attempt wrote it: then '
              f'{journal}/{t}/<date>-<slug>/notes.md)' if C.raw['plan']['journal_layout'] == 'id'
              else f'{journal}/<date>-{t.lower()}-<slug>/')
        return (f'\nWrite the task\'s journal as you go, in {at}: what you did, '
                f'what you tried that failed, and under **Not verified** everything you could not check, with '
                f'why (or `none`). A skipped check that is written down is useful; a silent one is a bug '
                f'nobody will find.\n' if journal else '')

    def publish(t: str) -> str:
        return (NO_REMOTE if C.push_remote and missing_remote(C.root) else PR_MODE if C.pr else APPROVE if C.approve else PUBLISH if C.push_remote
                else NO_PUSH).format(runner=C.command, tid=t, remote=C.push_remote)

    wip = not git('rev-parse', '--verify', '-q', f'refs/heads/wip/{tid}').returncode
    vals = dict(
        tid=tid, n=n, runner=C.command, branch=branch,
        publish=publish(tid),
        others=OTHERS if slots > 1 else '',
        earlier=(f'An earlier attempt that did not land is on wip/{tid} (or the newest wip/{tid}-N; `git log {branch}..wip/{tid}`, '
                 f'and the ledger line in {r["notes"]}/ledger.md says why). Read it before starting over.\n'
                 if wip else ''),
        rules=f'read {r["rules"]} first' if r['rules'] else 'the README, and AGENTS.md or CLAUDE.md if there is one',
        test=(f'Before its commit, `done` runs `{r["done_test"]}`, and it must pass.' +
              (f' The test gate, `{r["test"]}`, is for the merge.' if r['test'] else '')
              if r['done_test'] else f'The test gate is `{r["test"]}`. `done` runs it, and it must pass.' if r['test'] else
              'There is no test gate, so say in the commit message how you checked the work.'),
        journal=journal_text(tid),
        extra=f'\n{r["prompt_extra"].strip()}\n' if r['prompt_extra'] else '',
        brief=brief_for(tid, cwd),
    )
    kinds, _ = P.kinds()
    vals['followups'] = FOLLOWUPS.format(runner=C.command, kinds='; '.join(f'{k} {v}' for k, v in kinds.items()))
    vals['extra'] = vals['extra'].format_map(_Keep(vals))  # `prompt_extra` may say {n}, {tid}, {runner}
    template = (ROOT / r['prompt']).read_text(encoding='utf-8') if r['prompt'] else PROMPT
    own = bool(r['prompt']) or '{brief}' in template  # a custom template, or a replaced PROMPT that places the brief
    if own:
        prompt = template.format_map(_Keep(vals))
    else:  # F103: the same text for every task first; `<ID>` stands for the id the task part names
        prompt = template.format_map(_Keep({**vals, 'tid': '<ID>', 'publish': publish('<ID>'),
                                            'journal': journal_text('<ID>'), 'earlier': '', 'extra': ''}))
    from agent_runner import glossary  # F22: name things with its terms, add new ones; nothing when it is off
    prompt = glossary.fit(prompt, 'slot', C.command, C)
    from agent_runner import voice  # F21: the person's wording, for what status and since show of this task
    prompt = voice.slot(prompt, C)
    if not own:
        prompt = f'{prompt.rstrip()}\n\n' + TASK_PROMPT.format_map(_Keep(vals))
    policies = []
    if r['include_task_id_in_commit']:
        policies.append(f'Include task ID `{tid}` at the start of the commit subject.')
    else:
        policies.append(f'Do not include task ID `{tid}` in the commit subject; task tracking is separate.')
    if not P.concept(tid):  # F200a: a policy, so a project's own prompt template carries it too
        policies.append(f'{OWN_FILES} {SPLIT_FILES}')
    if pitch.on(C):  # F98
        policies.append(PITCH_PROMPT.format(path=C.notes('pitches', f'{tid}.json')))
    if C.pr:  # F419
        policies.append(PR_PROMPT.format(path=C.notes('pitches', f'{tid}.json')))
    if P.concept(tid):
        prompt = f'{prompt.rstrip()}\n\n' + CONCEPT_PROMPT.format(runner=C.command, tid=tid)
    elif audit.is_audit(tid, P.lines(plan_at(cwd) / 'TODO.md')):  # F417
        prompt = f'{prompt.rstrip()}\n\n' + audit.prompt(tid, branch, cwd)
    elif research_task(tid):  # F36
        prompt = f'{prompt.rstrip()}\n\n' + RESEARCH_PROMPT.format(runner=C.command, tid=tid,
                                                                   findings=findings_where())
    prompt = f'{prompt.rstrip()}\n\n' + ASKS_PROMPT.format(path=C.notes('asks', f'{tid}.json'), shots=C.notes('asks', tid),
                                                        env=C.notes('asks', f'{tid}.env'))  # F156, F175
    if questionnaires_on() and not P.concept(tid):  # F18
        prompt = f'{prompt.rstrip()}\n\n' + SHEET_PROMPT.format(
            runner=C.command, tid=tid, path=C.notes('sheets', f'{tid}.json'))
    if review_on() and not P.concept(tid):  # a concept task changes no product code: nothing to review
        prompt = f'{prompt.rstrip()}\n\n' + review_prompt(tid, cwd, harness=loop)
    if 'docs' in subagents() and not loop:  # F101; F132: the harness loop has no subagents
        prompt = f'{prompt.rstrip()}\n\n' + DOCS_PROMPT.format(runner=C.command, tid=tid)
    prompt = f'{prompt.rstrip()}\n\n{READS_PROMPT}'  # F451
    if agent_tool() and not loop:
        prompt = f'{prompt} {SEARCH_PROMPT}'
    if big := P.too_big(tid, C, plan_at(cwd) / 'TODO.md'):  # F177
        prompt = f'{prompt.rstrip()}\n\n' + SPLIT_PROMPT.format(runner=C.command, tid=tid, why=big)
    if tools := shared_tools.brief(C.command, tid):  # F168
        prompt = f'{prompt.rstrip()}\n\n{tools}'
    prompt = f'{prompt.rstrip()}\n\nProject policies:\n' + '\n'.join(f'- {policy}' for policy in policies)
    if not own:  # F103: the task's own text last
        prompt = f'{prompt}\n\n' + BRIEF_LAST.format_map(_Keep(vals))
    return prompt


BUDGET_STOP = ('Stop at a clean point: {tid} has used its budget ({why}). If your `{runner} done` is already '
               'running its test gate, let it finish and do nothing else. Otherwise do not run `done`: commit what '
               'is solid on task/{tid}, write in your journal what is done and what is left, then end your turn. '
               'The run parks your branch as wip/{tid}, and the task\'s next attempt starts from there.')


SPLIT_PROMPT = """\
Split {tid} first: it is too big for one session ({why}). Before any other work, choose its first part (one outcome \
that passes the gate and can be checked alone) and file each other part with `{runner} plan add {tid} "<what, why, \
how to check>" --files …` (they become {tid}a, {tid}b, … and start once {tid} has landed; `--after` another part it \
needs, never {tid}). """ + SPLIT_FILES + """ Nothing the task asks for may be lost between them. Then `{runner} plan edit {tid} "<the first \
part's whole text>" --files <its files>`, and do only that part. Skip what an earlier attempt already did or filed."""


# F177: said once to a session past `[run] context_warn`, at a turn's end (`watch.full_message`, harness.mjs)
CONTEXT_FULL = ('From the runner, not a person: this session\'s context is {peak}k tokens, past [run] context_warn '
                '({warn}k). If your `{runner} done` is already running its test gate, let it finish and do nothing '
                'else. Otherwise: commit what is solid on task/{tid}, file the rest as a part with `{runner} plan add '
                '{tid} "<what is left, why, how to check>" --files …`, make {tid} say what you did with `{runner} '
                'plan edit {tid} "<text>" --files …`, then `{runner} done` and `{runner} finish`. This is said once, '
                'and nothing stops you if you go on.')


CONCEPT_PROMPT = """\
{tid} is a concept task: do not build it. Research the repo (the code, the plan, how similar things are done \
here) and publish one page with `{runner} publish-page <the HTML file>` that lays out the options, usually two or three: for each, \
what it looks like or does (a sketch, a mock-up or an example where that says it best), the files it touches, \
and its trade-off; then your recommendation and why. A person picks one from that page, often on a phone, so \
make it short, concrete and readable at a glance. Put no answer buttons on the page: the person picks in \
Concepts or Needs you on the run page, or in the chat. Change no product code; commit only notes you wrote (the \
journal). Finish with `{runner} done {tid} "<msg>"`: it takes the page's URL that publish-page recorded, and its \
copy at .runner/concepts/{tid}.html, which the run page shows inline (a page published some other way: add \
`done {tid} "<msg>" --artifact <the page's URL> --page <the HTML file you published>`). With no Claude Code here there is no URL: \
publish-page records the run page's copy, and `done` takes that. It is refused without a published page, and it files the build task, blocked until the person approves an option."""


RESEARCH_PROMPT = """\
{tid} is a research task: find out, measure or check, and change no product. Write your findings where the \
run merges them ({findings}), queue each change they call for with `{runner} plan add`, and change no code: \
a research diff that touches any other file is not merged, and the task blocks on a person instead. One \
exception: code the person's own words asked for (the task's request when a person queued it, or their change, \
answer or message to you). Make only that code, and put a line `asked for: "<their exact words, three or more>"` \
in the commit message you pass to `done`, above its last line: the merge finds those words in what they said and \
does not ask them again. If its note says a person answered `Queue them as their own task` (or `follow-up`), file \
the earlier attempt's code (on wip/{tid}) as its own task with `{runner} plan add` and commit only the findings; \
if it says `Ship them` (or `merge anyway`, or a plain yes), they accepted that code: bring it over from wip/{tid} \
with the findings."""


def research_task(tid: str) -> bool:
    """F36: `tid` is research by the run's own kinds (`[plan] kinds`, else plan.KINDS)."""
    return P.research(tid, C.raw['plan'].get('kinds') or P.KINDS)


def findings_globs() -> list[str]:
    """F36: the files a research task may change, the one list the brief names and the merge checks: the plan
    directory (in the repo), the journal (in the repo), `[run] findings` and the audits' (F417)."""
    out = []
    if not C.plan_external:
        d = os.path.relpath(C.plan_dir, C.root).replace(os.sep, '/')
        out += ['TODO.md', 'DONE.md'] if d == '.' else [f'{d}/**']
    if C.journal and C.journal.is_relative_to(C.root):
        out.append(os.path.relpath(C.journal, C.root).replace(os.sep, '/') + '/**')
    return out + [f'{audit.folder()}/**'] + list(C.run['findings'] or [])


def findings_where() -> str:
    """Where a research task's findings go (F36), for its brief."""
    return ', '.join(f'`{g}`' for g in findings_globs())


class _Keep(dict):
    def __missing__(self, k: str) -> str:
        return '{' + k + '}'


# F156: what an agent asks of a person, in short steps: <notes>/asks/<ID>.json, read by need_detail (F162)
ASKS_PROMPT = """\
What you ask of a person (a CONFIRM, DECIDE or BLOCKED, or `ask`) is read in Needs you, often on a phone. The line is \
one short sentence, at most about 100 characters. It starts with what the person does, in words a person who never saw \
the task understands, and the reason comes second; it names no task id without that task's title. \
A wait on a task or a release is `--after <ID>`, and a wait a check can read is `--until <CHECK>` (`version:X.Y.Z`, \
`login:PROVIDER`, `tool:NAME`, `check:NAME`, or `date:YYYY-MM-DD` when all it waits for is a day, and it reopens by \
itself then): never `BLOCKED:`, as no person is needed. `done --blocked` refuses a \
CONFIRM or BLOCKED line over 200 characters with no ask file, or one that waits on an open task or release with no \
`--after`. When there is more to say, write it first to the ask file {path}, as \
JSON: {{"summary": <what is wanted, one sentence>, "where": <the device or place>, "steps": [<what to do>, …], \
"expect": [<what they should see>, …], "shots": [{{"file": <a picture's or video's path>, "caption": <what it shows>}}]}}; shots takes pictures and .mp4 \
or .webm videos, under {shots}/, 50 MB each, and anything to watch or look at is attached there or given as a link, \
never as an address to type or a hand-written /concept/ page (`done --blocked` refuses a /concept/<ID> of a task with \
no concept filed); leave out \
what you do not need. One action per step, in words the person sees on screen, no file names or code (a failed command and its error, \
when too long for the line, go in the commit message). For a check or choice about looks, take small screenshots, put under {shots}/, with no secrets or \
tokens in them. The file is optional; write a new one for each ask.

A `DECIDE:` is one question: two choices crossed in one bracket are two (ask the next once this one is answered). It may be read days later by someone who has not seen the chat: name the project, the thing and the problem in plain words, never "this", "it", "like this" or "What should I do?". Short answers become buttons: end the question with them in a bracket, as in `DECIDE: Should tasks added after an automatic release is queued go in the next release, instead of holding it up? [Yes (recommended) / No]`, before any link (about a page, always its link), or as "options": [{{"name": "Full", "rec": true}}, {{"name": "Small"}}] in the ask file. With `ask` use the ask file: a bracket there gives no buttons. Give 2 to 12 different names, each under 80 characters and no ` / ` in one, at most one recommended. Each says what happens and is clear without the chat: never a bare task id (say what it is, the id in brackets at most).

When you block with `BLOCKED:` because of steps only a person can take (a login, a certificate or signing key, \
a secret, a click in a third-party dashboard), write the steps, links, commands and inputs they have to do in that \
file: a step is words or {{"text", "link", "cmd", "on"}}, and "inputs" lists what they give back (a secret is only \
named there; the person's answer carries its value). Here a step may hold a link or a command. Write only steps you cannot do yourself, checked \
and not guessed, and put no secret in the file. Never tell the person to run a script. When they answer, the \
reopening note gives you their values, and a secret is in {env} as NAME='value'."""


REVIEW_PROMPT = """\
Spec review, before `done` (after mattpocock/skills code-review, MIT; its Spec axis only): commit your work, \
then give a fresh subagent ({who}; with none, a fresh one-shot session of your agent CLI) only the \
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


ONCE_REVIEW = """\
Spec review, before `done` (after mattpocock/skills code-review, MIT; its Spec axis only): commit your work, then \
run `{runner} review {tid} --base {base}`, with a command time limit of 1000 seconds (or in the background, waiting \
for it to end). It gives a fresh one-shot only the diff and the task's brief and prints its findings: (a) what the \
task asked for that is missing or partial, (b) what the diff does that was not asked, (c) what looks implemented but \
wrong. When it says the one-shot did not run, review your own work as a fresh reader would: read only `git diff \
{base}...HEAD` and `{runner} plan brief {tid}`, and list the same. """ + REVIEW_PROMPT[REVIEW_PROMPT.index('Fix (a)'):]


DOCS_PROMPT = """\
Hand CHANGELOG, docs, README, journal and plan-text edits (a `plan add` or `plan note` text) to the `docs` \
subagent (the Agent tool, subagent_type "docs"): tell it the file or command, what to say and why, and the \
facts it needs. Then check its result (`git diff`, `{runner} plan {tid}`) and fix what it got wrong yourself."""

# F451: what a session reads stays in its context and is paid for again every turn
READS_PROMPT = """\
Read only the ranges you need: find the place first (`grep -n`, or the file's outline in the brief), then read that \
range. Do not read a big file whole, or read again a range you already have and that has not changed. Read all the \
task needs."""

SEARCH_PROMPT = """\
Hand a broad search over several files to a read-only search subagent (the Agent tool, `Explore`) that returns \
file:line and a short conclusion; look up a known place yourself."""

SUBAGENTS = {
    'review': ('A fresh spec reviewer for the review before done: give it only the diff and the task brief, '
               'never the conversation, and it lists what is missing, what was not asked and what looks wrong.',
               'You review a diff against the task brief you are handed, nothing else: you have none of the '
               'conversation that wrote it. Read the diff and the brief (open a changed file in the repo only to '
               'check a finding), then answer as the message asks, each finding quoting the task\'s words. Change '
               'no file.'),
    'docs': ('Writes documentation and plan text: CHANGELOG, docs, README, journal edits and the text of a '
             '`plan add` or `plan note`. Tell it the file or command, what to say and why.',
             'You make the documentation or plan-text change you are asked for, and only that: in the repo\'s own '
             'style and with the terms of its GLOSSARY.md, if it has one. Change no code and commit nothing. '
             'Answer with what you changed: each file or command, and a line on what it says now.'),
}


def subagents() -> dict:
    """F101: the task session's Claude Code subagents (`--agents`), each on its `[models]` role: `review` when
    the spec review is on, `docs` unless `[models] docs = false`. F406e: none on another provider's model: that
    review is `run review`, and those docs are the task's own."""
    try:
        models = C.raw.get('models') or {}
    except (AttributeError, KeyError, TypeError):  # no config loaded
        return {}
    on = {'review': review_on(), 'docs': True}
    return {role: {'description': desc, 'prompt': prompt, 'model': models[role]}
            for role, (desc, prompt) in SUBAGENTS.items() if on[role] and models.get(role) and not harness_session(models[role])}


def agent_tool() -> bool:
    """F451: a Claude Code task session has the Agent tool: every one that is not lean, else as `slots.lean` gives it."""
    try:
        return not C.run['lean'] or review_on() or bool(subagents())
    except (AttributeError, KeyError, TypeError):  # no config loaded
        return False


def review_on() -> bool:
    """F28: `[run] review` (default on): the slot prompt asks for a spec review before done."""
    try:
        return C.run.get('review', True) is not False
    except AttributeError:  # no config loaded
        return False


def harness_session(model: str) -> bool:
    """F132: a session on `model` runs in the harness loop (another provider's than claude): no Agent tool."""
    if not model:
        return False
    try:
        from agent_runner.config import harness_model
        return harness_model(model, C.providers)
    except AttributeError:  # no config loaded
        return False


def review_prompt(tid: str, cwd: Path, harness: bool = False) -> str:
    """REVIEW_PROMPT filled in: the branch the diff is taken against, the skip threshold, and whether this task
    has a long form (then it is reviewed whatever its size). F406e: with `harness` (a harness loop session, which
    has no subagents), or a [models] review of another provider, it is a one-shot: ONCE_REVIEW."""
    try:
        base = default_branch()
    except SystemExit:
        base = 'main'
    try:
        plan_dir = C.plan_dir if C.plan_external else cwd / os.path.relpath(C.plan_dir, C.root)
        has_long = P.long_form(plan_dir, tid).exists()
    except (OSError, ValueError):
        has_long = False
    if harness or harness_session((C.raw.get('models') or {}).get('review') or ''):
        return ONCE_REVIEW.format(
            base=base, runner=C.command, tid=tid, min_lines=int(C.run.get('review_min_lines', 50)),
            long='this task has one, so review it whatever its size' if has_long else 'this task has none')
    return REVIEW_PROMPT.format(
        who='the Agent tool, subagent_type "review"' if 'review' in subagents() else 'the Agent tool',
        base=base, runner=C.command, tid=tid, min_lines=int(C.run.get('review_min_lines', 50)),
        long='this task has one, so review it whatever its size' if has_long else 'this task has none')


# --- F18: pick sheets for a DECIDE with more than one question (agent_runner/sheet.py) ---------------------------------------
#
# An agent that blocks with `DECIDE:` on a choice writes it as questions with answers to <notes>/sheets/<ID>.json,
# has the runner publish its page with `agent-runner sheet <ID> --publish` (F411) and blocks with
# `DECIDE: <summary> <the sheet's url>`. Needs you, the feed and the control brief show one line, '<summary>.
# Pick on the sheet or reply go', and the link. The sheet's Send gives a reply line (`<ID> picks: a=b …`) that
# the session the person talks to passes to `sheet <ID> --picks`; 'go' is `sheet <ID> --go`. Both reopen the
# task (`plan confirm`) with each answer spelled out in its note. `[run] questionnaires = false` turns it off.

SHEET_PROMPT = """\
When you block with `DECIDE:` on a choice that takes more than one question (a pick-list, settings), or whose answers each need a why (a sheet is the one `DECIDE:` that holds several), write the choice \
as a pick sheet, not as a numbered list: no option numbers anywhere. Write {path} as JSON: "title" (a short \
name), "summary" (one line that says what is ready), "intro" \
(one or two sentences), and "groups": [{{"heading": <a kind of change>, "questions": [{{"id": <short key>, \
"q": <a plain question>, "answers": [<2-3 short answers>], "recommended": <index of your pick>, "keep": \
<index of the answer that changes nothing; leave it out when every answer changes something>, "why": <one or two lines>}}]}}]; `backticks` show as \
code. Check it with `{runner} sheet {tid}` and publish it with `{runner} sheet {tid} --publish`: it prints the sheet's URL \
(its Send writes the picks there; with no URL, the run page has the sheet: leave the link out). Give it up to 6 minutes. Then block with `--blocked "DECIDE: <the summary> <the sheet's url>"`. Their picks (or 'go' for your recommendations) reopen {tid} with each \
answer in its note."""


def questionnaires_on() -> bool:
    """F18: `[run] questionnaires` (default on): a DECIDE with more than one question is asked as a pick sheet."""
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


def concept_at(cwd: Path | None) -> bool:
    """C48: is the worktree `cwd` on a concept task's branch (`task/<ID>`): the one session that gets the Artifact tool."""
    if cwd is None:
        return False
    try:
        head = (git('rev-parse', '--abbrev-ref', 'HEAD', cwd=cwd).stdout or '').strip()
    except Exception:
        return False
    return head.startswith('task/') and P.concept(head[5:])
