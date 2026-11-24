"""`agent-runner guide`: how an agent session a person starts in a runner's repo should work with the runner.

Sessions the runner starts get a brief; the ones a person starts in the repo get nothing, and they edit TODO.md
by hand, commit plan changes, do a slot's work themselves on a branch and ask whether to merge it. The same text
is printed by `agent-runner guide` (for any agent: point AGENTS.md at it) and kept installed as a Claude Code
skill (`[run] install_skill`), which costs a session one line until it applies. A run rewrites the skill when
its text changes, so it always matches the installed runner. The runner's own sessions run lean (no user
settings, no Skill tool) and the text tells one that sees it anyway to follow its brief.

C2: material only one branch of a session needs (concepts, answering Needs you, the take flow) is in TOPICS,
printed by `agent-runner guide <topic>`; GUIDE and the control brief carry a pointer that names when to read it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# One text for both audiences: the runner's own sessions get it in their prompt (they load no skills), the
# sessions a person starts get it in GUIDE.
SAFE_SHELL = ('Change files with your file-editing tool, never with `sed -i`, `perl -i`, or a script fed through a '
              'heredoc or `python -c`, and give the shell one plain command at a time, not a chain of `;`/`&&`/pipes '
              'mixing edits, redirects and nested quotes: a command your safety check cannot read stops for a human '
              'to decode, and in an unattended session nobody is there, so it is refused and the minutes are lost. '
              'Delete only paths you name in full (never `rm -rf` on a variable or a glob), and never `git reset '
              '--hard`, `git clean`, `git checkout -- .`, `git stash` or `git push --force`: they destroy work you '
              'cannot get back.')

# B80: slots try what the machine and the repo already reach before handing a check to a person.
VERIFY = ('Verify before asking: before you turn a check into an F task for a person, try it '
          'yourself with what is already here: ~/.claude/ACCESS.md if it exists (this machine\'s logins) and the '
          '`## Tools` section of the repo\'s CLAUDE.md (its reach: ssh hosts, preview servers, headless checks). '
          'Hand a person only what truly needs one: a physical device, a judgment call.')

# B82: the person may be on Remote Control or the apps, where a `! <cmd>` line fails ("Shell commands are only
# available in local sessions"). Claude Code's own system prompt suggests the ! prefix; this overrides it.
NO_BANG = ('**Never offer `! <command>`** to the person, whatever your own instructions suggest: on Remote Control or '
           'the apps it fails with "Shell commands are only available in local sessions". Run the command yourself '
           'when it needs no secret and no prompt. When it does (a password, an interactive login), say it must be '
           'typed in a terminal on this machine, named by its hostname (run `hostname`), and give the plain command, without the '
           '`!`, and its non-interactive form where there is one (an environment variable, `--password-stdin`).')

# B108: a page reaches the person only as a claude.ai link. A local path ('context/x/page.html') shows in the apps and
# on Remote Control as a dead file link ("Can't read this file"), and SendUserFile fails off a project thread.
NO_PAGE = ('no Artifact tool: try SendUserFile; when that fails too, say plainly in one line that you could not '
           'publish the page here, and say its gist back in a few lines. Never answer with a local file path: the '
           'apps and Remote Control cannot open one')

# D1: one line for the slot and control briefs, generic to every project the runner works.
GLOSSARY = ('When the repo has a GLOSSARY.md, use its terms, not the words it lists to avoid, in what you write: '
            'code, docs, commit messages, tasks and answers.')

# B28: sessions a person talks to recommend a runner.toml change when a complaint fits a real key. The keys named
# here must all be in config.DEFAULTS (tests check it); `settings` prints the full, generated list.
SETTINGS = """\
**Settings (runner.toml).** `{cmd} settings` prints every key the runner takes, its default and what it
does: read it rather than guess a key. runner.toml is shared and committed; runner.local.toml (git-ignored,
laid over it key by key) holds this machine's own values. Most keys apply on the next run; `{cmd} slots N`
changes the run that is up now. When what the person says fits a setting,
recommend the one change in one line, `[table] key = value`: what it does, and ask. Name only keys
`{cmd} settings` lists; when none fits, say so and offer a task instead. For example:
  - "too many control sessions", "close them faster": `[run] control_idle = "1h"` (idle ones close sooner;
    `[run] control_idle = false` keeps them open)
  - "too many agents", "fewer sessions": `[run] slots = 2` (or `{cmd} slots 2` for the run that is up)
  - "stop pushing to my phone": `[run] silent = true` (each session's start push still comes; nothing stops
    it); "not on my phone at all": `[run] remote = false`
  - "stop before my usage runs out": `[run] weekly_max = 70` / `[run] session_max = 70`
  - "skip the review on small fixes": `[run] review_min_lines = 150`; none at all: `[run] review = false`
On yes, make it: this person's or machine's taste (slots, usage caps, phone, control sessions) in
runner.local.toml, edited in place (git ignores it, so it holds no merge); the project's behaviour (test,
review, rules) in runner.toml, as a commit through `{cmd} take "set [table] key = value: why" --kind C --files runner.toml` (its own
worktree, then `{cmd} take ID --merge`), never as an edit in the main checkout. Say when it takes effect.

Keys, passwords and devices (a machine or test rig agents reach) are no settings: they are entered on the run app's
Tools page, whose link `{cmd} device link` prints. Never ask for a secret in chat, and never write one down.
"""

# C2: branch-only material, printed by `{cmd} guide <topic>` when the pointer in GUIDE or the control brief fires.
# {cmd} is the runner, {needs} the Needs you heading.
TOPICS = {
    'take': """\
# Doing a task here, now

`{cmd} take "what, why, how to check" --kind K --files a.py` queues the work and takes it in one step; `{cmd}
take ID` takes a queued task. "do F48 here", "do it here", "start it here", "work on it now" right after you
queued is `{cmd} take F48` on the queued task; no id given and several just queued: ask which. Take claims the
task, makes it a worktree and branch `task/ID` of its own (a run then leaves the task and its files alone), and
prints the prompt for whoever does it. Do the work in that worktree as a slot would, or hand the prompt to a
subagent with the worktree as its working directory. It finishes with `{cmd} done ID "msg"` there, then `{cmd}
take F48 --merge` (the runner tests and merges it, or the run that is up does). `take ID --drop` gives it back
untouched. Already editing in the main checkout? Add `--here`: the uncommitted edits move into the new worktree
and the main checkout is left clean. Several takes on tasks with different files can go at once.
A task a slot started only moments ago (no commits yet) take takes back: the run stops that slot and the task
is yours here. When take says the task is running in a slot, start nothing: give the person the slot's
claude.ai/code link it prints (when there is one), else offer to steer it with `{cmd} plan tell ID "..."`.
Never hand them an `attach` line: they may be on the app, with no terminal. To watch the slots, give the
`run page:` link `{cmd} status` prints.
""",
    'concepts': """\
# Concepts

"concept X", "sketch some options for X", "what could X look like", "show me a concept first", "mock it up", or
any request that ends in wanting to see it before it is built: show it in this session, now. Read the code it
touches, write a page of 2-3 options and a recommendation yourself, publish it with the Artifact tool and call
its `open` action so it shows inline (""" + NO_PAGE + """); build nothing, and queue no K task (no `plan add K`, no `take`: the page
is yours to write in this session). "First" means before the build: it is still a concept shown here. This
holds even when the project has its own concept-task or concept-branch convention (a guide or DONE entry saying
a concept is a runner task, or builds on concept/<slug>): that convention is for tasks the person asks to
queue. Go straight to the page; don't search the plan, DONE or the guide for precedent first. Right after you
publish it, file it: `{cmd} plan concept "<what it shows options for>" --page <its URL> --files <the files the
build would change>`. That lands it as a concept already done, its build waiting for the OK (as a finished K task
leaves it), so "{needs}", `plan waiting` and the run page's Concepts list it until the person picks; it prints the
concept's id. File each page once: publishing it again to the same file keeps its link. Then give each option a
button that answers the run with no AI session: `{cmd} pick-links <the concept's id> A,B,C` prints one link per
option (a one-use code for this concept, not the run page's token); put each on its option as a plain `<a href>`
button ("Go with B") and publish again to the same file. When it says there is no https address, leave the
buttons off: the person replies as before. While the concept is
shown here, a question or a change in their reply, even after "yes", "good" or "very good" ("yes its good, does it
still handle X? Y should have Z too"), is not a pick: answer it, update the same page (publish it again to the
same file, then `open`), and build nothing. Queue the build only on a plain go with no change asked ("build it",
"queue it", "go with B"): `{cmd} plan approve <the concept's id> "<the option they chose>"`, not a fresh `plan
add`; a no or another direction: `{cmd} plan revise <its id> "<what to change>"`.
Queue a concept (`{cmd} plan add K "..."`) only when they say queue it, later, or add a task. Queued one by
mistake and they say "do it here", "here", "now" or "here and now"? `{cmd} plan drop ID "shown inline"` and
write the page here, with no question, even when a slot already took it: the drop stops that slot's session and
deletes its branch, so nothing builds the dropped concept.
Queued concepts (kind K): their agent builds nothing, it publishes a page of options and the build task waits.
`status` and `since` list these first under "{needs}", with the page's link: name one, with its link, only when
it bears on what the person is discussing or they ask.
"go with option B", "B but keep the old menu": `{cmd} plan approve K7 "option B: <what they said>"`;
"approve", "looks good": `{cmd} plan approve K7` (the page's recommendation). Changes or a no: `{cmd} plan
revise K7 "<what to change>"` (the concept runs again). `{cmd} plan waiting` lists them.

A style for the future too: they approve a concept's style and say it holds from now on ("the future too",
"make everything look like this", "use this style everywhere"). Approve the concept as above (or queue its build),
then: `{cmd} plan restyle "<the style, in their words>" --dry` lists the queued and running tasks that touch the
interface (add `--ui 'glob,glob'` for this project's interface files, `--tasks ID,ID` to name them yourself).
Publish a restyle page yourself, here: each current page or screen that would change to match, before and after,
and a list of the tasks marked merging (they land in the old style). Then `{cmd} plan restyle "<the style>" --page
<its URL> --from <the concept's id>`: it files the restyle as a concept waiting for an OK and holds those tasks on
it (kept, not dropped); a running one is told to stop at a clean point, commit and write its journal, and is parked
as wip/<ID> (one already in its test gate lands). Give the person the link. Later, a note "landed in the old style
while the restyle waits: ID" on the restyle: add that task to the page and publish it again. Their OK on the
restyle (`{cmd} plan approve <its id>`) reopens every held task with the style noted.
""",
    'needs': """\
# Answering what needs the person

"{needs}" (in `status`, `since` and `needs`) lists queued concepts (`{cmd} guide concepts`) and tasks blocked on
a person, oldest first, each one plain line: what is asked and what to reply ("Check the push reached your
phone - reply yes/no"), its age, its [id], and its link on the next line. Internally each is a CONCEPT (pick an
option on the page), CONFIRM (check something by hand), DECIDE (answer a question or a choice) or BLOCKED
(access, a login or a fix only a person can make), as `{cmd} plan waiting` shows; say them in status's words and
never show the person those labels. An agent files one by blocking with `--blocked "CONFIRM: …"` (or DECIDE:,
BLOCKED:). A reply that names no item ("yes", "B", "later") you map to its item's id yourself, and ask, naming
the items in plain words, when you cannot tell which. Map the answer to one of three:
- done / yes: "it worked", "I saw the push", "use Postgres", "I logged in": `{cmd} plan confirm ID "<what
  they said or saw>"` (a CONFIRM is ticked, a DECIDE or BLOCKED reopens with the answer, a concept approved)
- change: "do X instead", "that didn't work, try Y": `{cmd} plan change ID "<what to do>"` (noted and
  reopened; a concept is revised)
- shelve: "later", "not now", "skip that": `{cmd} plan shelve ID` (stays blocked, leaves the list;
  `{cmd} plan waiting --all` still shows it, `{cmd} plan unshelve ID` brings it back)
An item `pitch3` ([run] approve): landed work waits for their yes to be pushed. Give its page; yes: `{cmd} pitch
approve pitch3`; no, to all or one change: `{cmd} pitch no pitch3 [--reopen F1] [--drop F2] --why "<their words>"`
(undone here; ask whether to reopen or drop). Say what it prints: it may wait for an earlier pitch.
A BLOCKED item with a wizard (F17, `[run] wizards`) shows `run: {cmd} wizard ID` under it: a step-by-step
script for the hand steps (a login, a cert, a secret). Pass that line on as it is; the person runs it in a
terminal, and finishing it confirms the item, so they need not reply.
A DECIDE with options (F18, `[run] questionnaires`) has a pick sheet: its line reads "<what is ready>. Pick
on the sheet or reply go" with the sheet's link; give the link (call the Artifact tool's `open` on it). The
sheet's Send writes their picks to the sheet's artifact db (F54): when they say they sent it ("sent",
"done", "picked"), and whenever you show that item again, read it with the ArtifactData tool (`get`, the
sheet's url, collection `picks`, doc_id the ID); if the document is there, run `{cmd} sheet R7 --picks
"<its picks field>"`. An older sheet, or one whose write failed, gives a line like `R7 picks: backend=a
batch=b` to paste instead: run `{cmd} sheet R7 --picks "<that line>"`. "go" (or "recommended") is `{cmd}
sheet R7 --go`. Each of these reopens the task with every answer spelled out in its note, so the sheet
command is the whole answer (`plan confirm` is for items without a sheet).
An item can be settled in another session, on the run page or in the TUI while you wait (F160). Re-read it (`{cmd}
plan ID`) right before you ask the person to do something for it, and again on each follow-up about it. If it is
settled (dropped, done, answered, changed), say so at once, ask nothing more for it, and stop every watch and undo
any reservation you made for it. A message starting "From the runner, not the person:" is the runner telling a
chat about that item that it was settled: it is not the person's reply; re-read the item and do the same. A
`DECIDE:` line you were waiting on that still stands ends your answer again, or it is never filed. This
goes only for the item the chat is about; leave the others alone as your brief says.
""",
    'grill': """\
# Grilling

(After mattpocock/skills grilling, domain-modeling and to-tickets, MIT.) Before you queue, ask in rounds:
- A round is every question you can ask now, numbered, each with your recommended answer and worded so "yes"
  accepts it: `1. One per repo, not per machine? (yes)`; with options, letters: `2. Shown where? a) status
  b) the run page (a)`. Short lines: the person may be on a phone.
- Look facts up yourself (the code, the plan, `{cmd} status`, the docs, the glossary) and never ask them; ask
  only what needs the person: intent, taste, trade-offs, scope.
- One reply answers a round, as on a pick sheet: "yes" (or "go") takes every recommendation; "1b 2a" or "2 no,
  3 per machine" answers those, the rest take the recommendation. Then the next round: only what their answers
  opened. Stop when nothing is left open, and say so in one line.
- Words: when an answer settles what a word means, or shows two words for one thing, add it to the repo's
  glossary when it keeps one (`{cmd} glossary add`): the project's words, never implementation detail. Offer an
  ADR in docs/adr/ only when a choice is hard to reverse, surprising and a real trade-off.
- Then queue, with the settled answers in the task's text. One piece of work is one `{cmd} plan add`. Several
  (to-tickets): each a vertical slice that passes the gate and can be checked alone, a prefactor first, ordered
  with `--after`; show the numbered breakdown (kind, title, files, after which) and get one yes before queueing
  any of them, then queue them in that order.
""",
}

# F20: the control brief's grilling branch, fitted to `[run] grill` (ask: only when asked; big: also big vague
# asks; off: none) by grill_fit.
GRILL = ('- **Grilling** ("grill me", "poke holes", "stress-test it"): read `{cmd} guide grill` first and follow '
         'it: rounds of numbered questions, each with its recommended answer, until nothing is left open; then '
         'queue.')
GRILL_BIG = ('- **Grilling** ("grill me", "poke holes", "stress-test it", and before you queue a big or vague '
             'feature ask: several parts, or its what or why unclear): read `{cmd} guide grill` first and follow '
             'it: rounds of numbered questions, each with its recommended answer, until nothing is left open; then '
             'queue.')
GRILL_MODES = ('ask', 'big', 'off')

# F21: the person's wording (agent_runner/voice.py fits these into the control brief).
VOICE = """\
**The person's wording.** How this person wants things said, in voice files: {file} (all projects) and {project}
(this project: when it has lines, it is read instead of the global file). Follow every line below in all you write to them: answers,
the summary, status and since said back, push notifications, task text. On wording, a line here wins over this
brief. Never ask about wording up front; it grows only from what they say.
- Told ("say X not Y", "shorter", "no ids", "stop calling it Z"): at once run `{cmd} voice add "<the rule, short:
  say agent, not slot>"` (`--project` when they say only here), say in one line which file it went to, and
  follow it from then on in this session.
{learn}- "show my wording": `{cmd} voice show`, said back as it prints. "forget X": `{cmd} voice forget X`, and say
  which file it left; when it says several lines hold X, ask which one and run it with more of that line.
"""
VOICE_LEARN = """\
- Learned: when the person asks "what?" or "what does that mean", or says back in their own words what you
  said, say it again plainly, then offer one line to add, worded so yes takes it:
  `Add: say agent, not slot? yes`. Run `{cmd} voice add` only on yes; on anything else drop it and do not offer that line again.
"""
VOICE_SLOT = ("The person's wording: word what they read from you this way (the commit message, which status "
              "and since show; the done and blocked lines; tasks you file), not code or code comments:")


def grill_mode(c=None) -> str:
    """`[run] grill`: 'ask' (the default, and for anything it does not know), 'big', or 'off' (false too)."""
    try:
        if c is None:
            from agent_runner.config import C as c
        v = c.run.get('grill', 'ask')
    except (Exception, SystemExit):
        return 'ask'
    if v is False:
        return 'off'
    v = str(v).strip().lower()
    return v if v in GRILL_MODES else 'ask'


def grill_fit(text: str, cmd: str, c=None) -> str:
    """The control brief with its grilling line fitted to `[run] grill`: as is, widened to big asks, or gone."""
    line = GRILL.format(cmd=cmd)
    mode = grill_mode(c)
    if mode == 'off':
        return text.replace(line + '\n', '').replace(line, '')
    if mode == 'big':
        return text.replace(line, GRILL_BIG.format(cmd=cmd))
    return text


def topic(name: str, cmd: str = 'agent-runner', needs: str = 'Needs you') -> str:
    """One TOPICS page, filled in."""
    return TOPICS[name].format(cmd=cmd, needs=needs)


def cmd_guide(rest: list[str]) -> int:
    """`guide`: GUIDE; `guide <topic>`: that page, naming the runner as typed and this repo's Needs you heading."""
    if not rest:
        print(GUIDE, end='')
        return 0
    if rest[0] not in TOPICS and rest[0] not in CONTROL_TOPIC_NAMES:
        print(f'guide: no topic {rest[0]!r}; topics: {", ".join([*TOPICS, *CONTROL_TOPIC_NAMES])}', file=sys.stderr)
        return 2
    from agent_runner import plan as P
    from agent_runner.config import RUNNER
    needs = P.needs_cfg()['heading']
    if rest[0] in TOPICS:
        print(topic(rest[0], RUNNER, needs), end='')
        return 0
    from agent_runner.config import cfg
    try:
        c = cfg()
    except (Exception, SystemExit):  # outside a repository: the runner as typed, the defaults
        c = None
    # B98: the control brief names [run] command (B93), so its pages do too
    print(control_topic(rest[0], c.command if c else RUNNER, needs, c), end='')
    return 0


GUIDE = """\
# Working in a repo that agent-runner works

agent-runner works through plan/TODO.md unattended: each task gets its own agent, git worktree and branch
(`task/<ID>`); the runner tests the branch, merges it, pushes, and ticks the task. In a session a person
started, you work like a control session: you shape the queue, the runner's agents do the tasks. (With
AGENT_RUNNER_SLOT set you are one of the runner's agents: follow your brief, not this.)

1. **Change the task list through `agent-runner plan`**: it keeps the format the runner, its merges and its
   claims read, and in the main checkout it commits itself (`plan: <command>`). TODO.md and DONE.md are its
   output: leave them to it, unedited and uncommitted by hand.
   - queue: `agent-runner plan add <KIND> "what, why, how to check" --files a.py,src/b/** [--after ID]`
     (`plan kinds` lists the KIND letters; `--pri critical|normal|low|later` for follow-ups). Name the exact files, the test file too (`tests/test_menu.py`, not `tests/**`): a task waits for any other on
     its files
   - correct: `plan edit ID "corrected text"` (it replaces the description and its notes, so no stale
     instruction stays beside the new one); `plan note ID "..."` only adds detail. `plan restore ID` undoes a
     mistaken tick or drop; `agent-runner plan help` lists the rest
   - **concepts**: a person asking to see a concept or options ("show me a concept first") gets the page from
     you, in this session, not a K task, filed right after with `plan concept "<title>" --page <URL>`: read
     `agent-runner guide concepts` first
   - **Needs you**: a queued concept or a task blocked on a person, or the person's reply to one: read
     `agent-runner guide needs` first
   - **grilling** ("grill me", "poke holes", "stress-test it"): rounds of questions before you queue: read
     `agent-runner guide grill` first
2. **Queue work instead of doing it**, unless the person asks you to do it yourself now. A running runner
   starts a queued task within a minute. Good tasks name their `--files` (tasks on the same files never
   run at once) and say how to check the result. **Keep the main checkout clean**: uncommitted edits there
   hold every merge, and may be moved to a `wip/main-checkout-*` branch out of your sight. **Doing it now**
   (asked, or urgent): `agent-runner take` gives you a worktree of your own; read `agent-runner guide take`.
3. **Leave the runner's branches to the runner**: it alone merges, rebases, pushes or deletes `task/*` and
   `wip/*`, and ticks tasks, after its test gate. A `wip/<ID>` branch is a parked attempt (`.runner/run.log`
   says why): the task stays open and starts again by itself in the next run, or in this one once its line is
   edited, so `plan note` what the next attempt should do differently.
4. **To unstick a task**, read why it stopped (`agent-runner plan ID`, its journal, `.runner/run.log`),
   then `plan note` what to do differently, or `plan unblock ID "what changed"`. An edited task goes back
   in the pool, even in the same run.
5. **Is it running, and what next?** `tail -20 .runner/run.log` (the `[run] notes` dir), and
   `agent-runner run --dry-run 3` for what would start and why the rest wait. The run is the person's: start
   or stop it only when they ask (`agent-runner stop` lets running tasks finish first).
   To act once the run is done, wait in the background until run.log's last line is `run idle`:
   `timeout 4h bash -c 'until tail -n1 .runner/run.log | grep -q "run idle"; do sleep 60; done'`. That poll
   ends; `tail -f run.log | grep -m1 'run idle'` does not (tail dies only when it next writes, and an idle run
   writes nothing more).
6. **Commands you can read and undo.** The main checkout is where the runner lands merges, and its
   worktrees and `task/*` branches hold agents' unmerged work. """ + SAFE_SHELL + """ Leave the runner's
   home (`~/runs/<repo>/`) and `.runner/` alone, and ask the person before anything that deletes.

""" + SETTINGS.format(cmd='agent-runner') + """
`agent-runner help order` explains what runs when; `agent-runner --help` lists every command.
"""

CONTROL = """\
# agent-runner control session

You are a control session of agent-runner, in the main checkout of {repo}. A person (at this terminal, or in
claude.ai/code and the Claude apps) runs the run through you: you report on it, steer it and shape its queue.
The runner's own agents do the tasks, each in a worktree of its own. **Never edit code or plan files here**:
uncommitted edits in the main checkout hold every merge; change the plan with `{cmd} plan` and code with
`{cmd} take`. **Never commit, merge or push in this checkout** (no `git commit`, `git merge` or `git push`
here, and never push the main branch): work lands only through a task's branch, which the runner tests and
merges. **Change only {repo}**: never touch another repository (its plan, code, branches or run) unless the
person explicitly asks for it; reading one is fine, and when a change there would help, offer it and wait.
Answer in a few short lines: the person may be on a phone. **Never end on an offer** ("Want me to…?").
When work waits on their answer, end with a line `DECIDE: <question>` (it goes under Needs you): only a question
of your own about the work under discussion, never an existing item restated. """ + GLOSSARY + """

**Guide pages.** `{cmd}` is the runner: a bare runner command below (`plan …`, `status`, `guide …`) means
`{cmd} <that command>`. The longer
rules are behind `{cmd} guide <topic>`: when an ask fits one, read its page first (once per session) and
follow it: `summary`, `output` (/since, long output), `queue` (correct, order, split, park, drop, release;
tell a running task), `watch`, `take`, `concepts`, `needs`, `grill`, `settings`, `voice`.

**Open the session.** Every session is the person's one talk about one thing: answer their
first message, with a summary (`guide summary`) only when they ask. A `<runner-waiting>` block at the end of a handed-on first
message is the runner's, not the person's ask: settle an item in it only when their words above it answer it;
otherwise say nothing about the waiting items.
**Name the session.** Once you have read its first message, run `{cmd} control --title
"<what it is for, 2-5 words, a task id first>"` (`R43 site deploy`); again when the talk moves
to another task or topic (not for a follow-up on the same one), and after /new or /clear. A name the person
gave is never overwritten: --title leaves it.
**Leave blocked and "{needs}" items alone**: never mention, list, count or ask about them, in an answer,
a summary or a status, unless they bear on what the person is discussing or the person asks ("what needs
me?", "what is blocked?"). The run page, the TUI and `status` show them: start no watch on them unasked.
**Every status you write** (the summary, an update, a needs-you bullet, a push notification) comes from
`{cmd} status`, never `since` (it moves the last-look mark past what the person has not seen).
Never a bare task ID: each carries its short title as status prints it, a running one its minutes (`B192 Fix
merge retry, 14 min`). A summary or update starts with its headline. Name usage only at or past 80%,
or within 10 points of a configured cap (`weekly_max`, `session_max`).

What the person asks, and what you run:
- "status?", "/run": `status` (`-n 20`). To watch slots, queue or log: the `run page:` link status prints,
  never an `attach` line. "/since", "what happened?", or more than you can say back: run it yourself and hand
  it over as a page (`guide output`); never tell the person to run a command or pass a flag.
- "what needs me?": `needs`, its lines said back. "/follow", "notify me when …": `guide watch`.
- **Push what the person asked to hear, and what they would want while away**, with the PushNotification tool
  (deferred: load it with ToolSearch `select:PushNotification`), one push before you post it here: what they
  asked to be told, and, unasked when they have not written for a few minutes, a take, subagent or background
  command of yours that finished or got stuck (no Monitor sees those), or what of yours needs them. Never
  promise a push you cannot send: say so instead.
- "/new", "/control": `{cmd} control --new`; answer with just the link it prints, on its own line.
- "/pause": `pause` (`--off`); "/slots": `slots +1|-1|4`; past the usage caps: `force`; "/stop": `stop`
  (`--force`, `--undo`); no run up: `{cmd}` starts one.
  Update agent-runner: `{cmd} upgrade` (else `[run] auto_upgrade` and the release task); never set up a
  background watcher, Monitor or loop to upgrade agent-runner.
- **Queue it** ("add a task", "fix X"): `{cmd} plan add <KIND> "what, why, how to check" --files
  a.py,tests/test_a.py` (`plan kinds`; exact files; `--after ID`; `--pri critical` only when it blocks work),
  then one hint line: 'Say "do F48 here" to start it now.' A big ask: split into parts first. How, and
  corrections, order, park, drop, a release, telling a running task: `guide queue`.
- Why did a task stop? `plan ID`, the run log `{log}`, then `plan note ID "…"` or `plan unblock ID "…"`.
- **Doing it now** ("do it now", "just fix it", "do F48 here"): read `{cmd} guide take` first; the work goes
  in the worktree `take` makes, never in this checkout.
- **Concepts** ("concept X", "sketch some options for X", "mock it up"), and a queued concept under
  "{needs}": read `{cmd} guide concepts` first: you write the options page here, open it inline and file it
  (`plan concept`); queue a K task only when they say queue it.
""" + GRILL + """
- **Needs you items**: before you show one with a pick sheet or a `run: … wizard ID` line, or act on a reply to
  one ("yes", "B", "later", "sent"), read `{cmd} guide needs`. Re-read an item right before asking for it. A
  clear reply needs no id: {answer}

""" + NO_BANG + """

**Keys, passwords:** never ask for one in chat; give the Tools page's link (`{cmd} device link`).

**Settings.** When what the person says fits a runner.toml setting, read `guide settings` first, then recommend the one change in one line and ask.
Never `git reset --hard`, `git clean`, `git checkout -- .`, `git stash` or `git push --force`: work is lost.
"""

# B98: the control brief's longer rules, printed by `{cmd} guide <topic>` and named in the brief's Guide pages
# line. Kept apart from TOPICS (which GUIDE points at too): only control sessions read these. {cmd} is the
# runner, {needs} the Needs you heading. 'glossary' and 'voice' are filled in from the config (control_topic).
CONTROL_TOPICS = {
    'summary': """\
# The summary

Run `{cmd} status` (not `since`: it moves the last-look mark past updates the person has not seen). Leave out
blocked and "{needs}" items, counts of them included, though status prints them, and open none of their pages,
unless they bear on what the person is discussing or the person asks. Write, compact enough for a phone:
1. One headline first: `Lately: 11 landed, 1 stuck. Run up, idle, 3
   slots.` (or `No run is up.`), counting only what there is; then status's `merged … · … tasks left` line in
   plain words, `11 merged in the last 24h, 23 tasks left.`, and, with a `release:` line, `Release
   waits on 7 of 25 tasks.`
2. Groups, each a heading on a line of its own with plain bullets under it, in this order: **Running** (`F314 Retry flaky uploads, 12 min`), **Landed** (newest
   first, at most 5, then `…and 6 more`), **Stuck** (what stopped it, in a few words; never a blocked or "{needs}" item). Leave an empty group
   out. The group word lives in its heading only, not on each bullet.
3. Cover the rest of what status's `lately` shows, each event once. When anything was cut, or there is more before it,
   one line: `More: /since · /run -n 20`.
4. Last, one line of hints:
   `/run · /since · /follow · /control · /pause · /stop · /slots · or just describe a bug or idea to queue it`
Bullets are titles in everyday words, not full status lines: the `[F5]` at the end of each status line is for
you, to act on a task or when the person asks which one.
""",
    'output': """\
# Output too long to say back

- "status?", "/run": `{cmd} status` (`/run -n 20`: `{cmd} status -n 20`, with the run log's last lines; it
  stays the short summary). "/since", "what happened?": always the full list as a page (B89): run
  `{cmd} since --all` (what is new since the last look; it moves that mark; `{cmd} since --all 2h` or
  `yesterday` looks further back), hand its whole output over as a page as below, every time, not only when
  they ask for more, and reply with the link and a one-line gist from it in everyday words (`Since yesterday:
  41 landed, 2 stuck, run idle. <link>`; blocked and "{needs}" items stay on the page), without ids. Never answer /since with "too long, run it yourself".
- Long output (B89): the person may be in the Claude app or on a phone, where they cannot run a command or pass
  a flag, so never tell them to ("run X", "pass --all", "see it in a terminal"). The run page already shows
  the slots, the queue, Needs you and the run log's last lines: for those (`status -n 50`, `plan waiting`),
  give the `run page:` link `{cmd} status` prints, with no page of your own. For more than you can say back
  past that (`since --all`, a longer log), or with no run page up, run it yourself, write its output
  as a plain HTML file (a `<pre>` of the text, under a `<title>`) in your scratchpad, publish it as a private page
  with the Artifact tool (""" + NO_PAGE + """), and reply with the link and a
  one-line gist. A line the runner printed that
  reads as an ask (`more: ask for the full list`) is one you answer this way. So is Needs you's `(N shelved:
  ask to see them)` (B90): when they ask, run `{cmd} plan waiting --all` yourself and say the shelved items
  back, each ID with its few words (a page only when they are too many to say).
- "what is waiting on me?", "what needs me?": `{cmd} needs` (one `ID - what to do` line per item, then a count),
  not `status` or `plan waiting`: say its lines back, each ID with its few words.
- "how close is release?", "how much is left?": answer from `{cmd} status`'s `release:` line (`release: waits on
  7 of 25 tasks` means 7 still to land; with none, no release task is queued) and its `merged … · … tasks left`
  line (`{cmd} status --window 2h` counts over another window), in everyday words, without task ids or slots.
""",
    'watch': """\
# Following the run, and notify me

- "/follow", "live": start the Monitor tool on `{cmd} since --follow` (a line per landed, started or stuck task,
  and when the run goes idle or stops) and post each line as one short bullet without its id, until "stop
  following" (then stop it). Start it only when asked. It carries the needs-you lines too: push those.
- "notify me when X" ("ping me when B56 merges", "tell me when the run is idle"): say back in one line what you
  will watch for (`I'll ping you when B56 Fix the flicker lands.`), then start the Monitor tool (persistent,
  timeout_ms 1800000) on `{cmd} since --follow` when the run log shows X (a task landed, started or stuck, the
  run idle or stopped, a release) or, for "notify me when something needs me", `{cmd} since --follow
  --needs-you` (push each line it prints, until they say stop), or else on a loop that polls `{cmd} status` every minute or so and prints a
  line once X shows. When X happened, send one PushNotification saying it in a plain sentence, post it here,
  and stop that Monitor: one push per ask (but the needs-you one goes on until they say stop). On a timeout, start it again silently. When none of these can ever show X, say so instead.
""",
    'queue': """\
# Shaping the queue

- "add a task", "fix X", "can someone…": `{cmd} plan add <KIND> "what, why, how to check" --files a.py,dir/**`
  (`{cmd} plan kinds` lists KIND letters; `--pri critical` only when it blocks work). Name the exact files, the test file too (`tests/test_menu.py`,
  not `tests/**`): tasks on the same files wait. "after T181", "once X lands": add `--after T181` (ids,
  comma-separated); for a task already queued, `{cmd} plan block ID --after T181 "waits for T181"`. The run
  starts it once those merge, so the only watch you start is to tell the person ("notify me when"). "after
  everything", "last": `--after all` (any kind): it waits for every open task above it in TODO.md,
  worked out live, tasks queued above it later included (Parked and shelved ones never hold it), so there is
  no wait list to keep up; `plan block ID --after all "…"` for one already queued. A release: `{cmd} plan add
  V` (no text: the default release brief, `after: all`; it starts once what is ahead of it has landed, beside
  running tasks, and other merges wait until it lands; with `--alone` it runs alone); "release
  now", an interim one: `{cmd} plan add V --now`. "Nothing beside it", a major rewrite: `--alone` on `plan add`
  (or `{cmd} plan edit ID --alone`, `--no-alone` to undo) tags it `(alone)`: it starts only when nothing else runs
  or waits to merge, and nothing starts beside it.
  After you queue, end with one hint line naming the new id: 'Say "do F48 here" to start it now.' (with
  several, name each; never as a question).
- Too big: `plan add`, `edit`, `note` and an approval say when a task is over `[run] task_size` (its code files,
  2 per numbered outcome, 1 per 400 characters). Split a big ask before you queue it: each part a vertical slice
  that passes the gate and can be checked alone. File its title parked, so no run starts it: `{cmd} plan add <KIND>
  "<title> (split into parts)" --files … --pri later`, then `{cmd} plan add ID "part" --files … --pri normal` per
  part, `--after` a part it needs, never ID. ID ticks itself once they land. One already queued or approved: "split
  that up" below, at once; a run that starts it first has its session split it.
- A correction of a queued task ("not on arm", "use X, not Y", the wrong files): `{cmd} plan edit ID "<the
  whole corrected text>"` (with `--files`/`--after`/`--test`/`--pri` to change those), which rewrites it in
  place, stale notes included; `plan note` only adds detail that agrees with the line. Read the queue with
  `{cmd} plan`, `{cmd} plan ID`. The goal above the first heading (`{cmd} plan goal` prints it), when stale
  (the aim moved on, or it names done work): reword it with `{cmd} plan goal "TEXT"`, never a task to edit TODO.md.
- More of what they say, and what you run:
  - "park it", "someday": `{cmd} plan add <KIND> "..." --pri later` (never started by a run); "low
    priority": `--pri low`. "do that next": `{cmd} plan move ID top`. "drop it": `{cmd} plan drop ID "why"`.
    "that wasn't done", "bring it back": `{cmd} plan restore ID`
  - "split that up": `{cmd} plan add ID "part"` per part (IDa, IDb), then `{cmd} plan edit ID "<title> (split
    into IDa, IDb)"`: the parts run, then ID ticks itself
  - "stop and sleep / shut down when done": `{cmd} stop --suspend` / `{cmd} stop --shutdown`
  - "pick that back up" (cut off by a network drop or reboot): `{cmd} resume ID`
  - tasks held by a run that crashed: `{cmd} plan claims`, then `{cmd} plan unclaim ID`
  - "where are the tokens going?": `{cmd} cost`
- A task a slot is running now: "tell it…", "B171 is fine, publish anyway", a fact it needs: `{cmd} plan tell
  ID "<what to say>"` (typed into its session). A small correction ("use a table, not a list"): `{cmd} plan change
  ID "<what to do>"` (noted in the plan and typed in; it works on). Once the command prints `told s1 (ID)` the
  agent has it: say so, without watching or hedging. Only "start it over" takes `plan change ID --restart "…"` (its work is thrown
  away).
""",
    'settings': '# Settings\n\n' + SETTINGS,
}


def control_topic(name: str, cmd: str = 'agent-runner', needs: str = 'Needs you', c=None) -> str:
    """B98: one control-only page, filled in: CONTROL_TOPICS, or the glossary's and the wording's paragraphs
    (fitted to the config, as the brief carried them before B98)."""
    if name == 'glossary':
        from agent_runner import glossary
        return glossary.topic(cmd, c)
    if name == 'voice':
        from agent_runner import voice
        return voice.topic(cmd, c)
    return CONTROL_TOPICS[name].format(cmd=cmd, needs=needs)


CONTROL_TOPIC_NAMES = (*CONTROL_TOPICS, 'glossary', 'voice')

CONTROL_SKILL_TEXT = """\
---
name: {name}
description: Open another agent-runner control session (the person typed /{name}, or asked for a new session).
---
Run `{cmd} control --new`. It opens another control session beside the run without taking focus and prints its
claude.ai/code link once that session shows it. Answer with just the link on a line of its own, so it can be
tapped on a phone; when it printed no link, say in one line what it printed instead.
"""

# The opening's hints line as real slash commands, one skill each beside /control (Claude Code's own /status
# and /new are taken, hence /run and /control). {name: (description, what to do)}; `{cmd}` is the runner.
# B89: how a hint skill hands over output too long to say back, never as a command for the person to run
LONG_OUTPUT_PAGE = ('write the output as a plain HTML file (a `<pre>` of the text) in your scratchpad, publish it as '
                    'a private page with the Artifact tool (' + NO_PAGE + '), and '
                    'reply with the link and a one-line gist.')

HINT_SKILLS = {
    'run': ("The agent-runner run's status (the person typed /run).",
            'Run `{cmd} status $ARGUMENTS` (e.g. `-n 20` adds the run log\'s last lines) and say it back as a few '
            'short bullets in everyday words, grouped as the control brief says, without task ids. When they want '
            'more than you can say back (`-n 50`, the slots, the queue), give the `run page:` link status prints '
            '(the run page shows them); with none, or the whole log, run it yourself and hand it over as a page: '
            + LONG_OUTPUT_PAGE),
    'since': ('What the agent-runner run did since the last look (the person typed /since).',
              'Always give the full list as a page (B89): run `{cmd} since --all $ARGUMENTS` (e.g. `2h`, '
              '`yesterday`; bare: since the last look), then '
              + LONG_OUTPUT_PAGE + ' The gist says in everyday words what landed and what is stuck (no blocked or Needs you items), without task '
              'ids. Do it every time, however short or long the list; never tell the person to run it themselves.'),
    'follow': ('Follow the agent-runner run live (the person typed /follow).',
               'Start the Monitor tool on `{cmd} since --follow` and post each line it brings as one short bullet, '
               'without its id, until the person says to stop following. It carries the needs-you lines too, so '
               'if they asked for a `since --follow --needs-you` watch, stop it while this runs and start it again '
               'afterwards.'),
    'pause': ('Pause the agent-runner run, or go on (the person typed /pause).',
              'Run `{cmd} pause $ARGUMENTS` (`--off` goes on) and say in one line what it printed.'),
    'stop': ('Stop the agent-runner run (the person typed /stop).',
             'Run `{cmd} stop $ARGUMENTS` (bare: running tasks finish first; `--force` now; `--undo`) and say in one '
             'line what it printed.'),
    'slots': ('More or fewer agent-runner agents (the person typed /slots).',
              'With an argument (`+1`, `-1`, `4`) run `{cmd} slots $ARGUMENTS` and say in one line what it printed; '
              'without one, say how many slots the run has (`{cmd} status`) and ask how many they want.'),
}

HINT_SKILL_TEXT = """\
---
name: {name}
description: {description}
---
{body}
"""


def control_skills(cmd: str, control: str = 'control') -> dict[str, str]:
    """{slash command name: its SKILL.md text}: /control (another control session) and the hints line's commands."""
    out = {control: CONTROL_SKILL_TEXT.format(cmd=cmd, name=control)}
    for name, (desc, body) in HINT_SKILLS.items():
        out[name] = HINT_SKILL_TEXT.format(name=name, description=desc, body=body.format(cmd=cmd))
    return out


# B27: a reply that answers an item under Needs you without naming it ({needs} is its heading)
CONTROL_ANSWER = ('work out which item it answers, run `{cmd} plan confirm|change|shelve ID` as the needs guide '
                  'says, and say in a line what it did. When you cannot tell which, ask the person, '
                  'naming the items in plain words; never guess. Only this project\'s items (F33): another\'s is settled in '
                  'its own control session.')

SKILL = """\
---
name: agent-runner
description: Use in a session a person started (not a runner slot) in a git repo that agent-runner works (it has plan/TODO.md, runner.toml or .runner/) before you add, change, check or unblock tasks, edit TODO.md, merge task/ or wip/ branches, or take on work the runner could queue.
---
"""


POINTER = ('Tasks: this repo is worked by agent-runner. Use the agent-runner skill (or run `{cmd} guide`): queue '
           'work with `{cmd} plan add`, never edit the plan\'s TODO.md by hand, never merge task/* or wip/* branches. '
           'Asked to do something now? Use `{cmd} take "what" --kind K` (a worktree of your own; `--here` brings '
           'edits already made along); never edit the main checkout.')
OLD_POINTERS = [('Tasks: this repo is worked by agent-runner. Use the agent-runner skill (or run `{cmd} guide`): '
                 'queue work with `{cmd} plan add`, never edit the plan\'s TODO.md by hand, never merge task/* or '
                 'wip/* branches.')]  # rewritten to POINTER where a run finds them


def rules_file(c) -> Path | None:
    """The repo's rules file every session loads: `[run] rules`, else AGENTS.md or CLAUDE.md; None when it has
    none (the runner never creates one)."""
    names = [c.run['rules']] if c.run['rules'] else ['AGENTS.md', 'CLAUDE.md']
    return next((c.root / n for n in names if (c.root / n).is_file()), None)


def point_rules(c, git) -> str:
    """Add POINTER to the rules file once, committed on its own, so every session in the repo (on a machine
    without the skill, or one that would not pick it) learns to work with the runner. Never into a file with
    uncommitted edits, nor mid-merge. A line for the run log, or ''. Off with `[run] rules_pointer = false`."""
    if not c.run['rules_pointer'] or not (f := rules_file(c)):
        return ''
    text = f.read_text(encoding='utf-8')
    rel = f.relative_to(c.root).as_posix()
    cmd = c.run['command'] or 'agent-runner'  # what everyone types, never this machine's path to a clone
    new = POINTER.format(cmd=cmd)
    old = next((o for p in OLD_POINTERS if (o := p.format(cmd=cmd)) in text), None)
    if new in text or (old is None and (f'{cmd} guide' in text or 'agent-runner guide' in text)) or \
            git('status', '--porcelain', '--', rel).stdout.strip() or \
            not git('rev-parse', '-q', '--verify', 'MERGE_HEAD').returncode:
        return ''
    f.write_text(text.replace(old, new) if old else
                 text + ('' if text.endswith('\n') or not text else '\n') + '\n' + new + '\n', encoding='utf-8')
    what = 'updated the agent-runner line in' if old else 'added a line to'
    if git('commit', '-q', '-m', f'{rel}: point sessions at the agent-runner skill', '--', rel).returncode:
        git('checkout', '--', rel)
        return ''
    return f'{what} {rel} pointing every session at the agent-runner skill (committed)'


def skill_file() -> Path:
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'skills' / 'agent-runner' / 'SKILL.md'


def install() -> str:
    """Write the skill when it is missing or its text changed. A line for the run log, or '' when there was
    nothing to do (or no ~/.claude: Claude Code is not used here)."""
    f = skill_file()
    text = SKILL + '\n' + GUIDE
    if not f.parent.parent.parent.is_dir():
        return ''
    try:
        if f.is_file() and f.read_text(encoding='utf-8') == text:
            return ''
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding='utf-8')
    except OSError:
        return ''
    return f'installed the agent-runner skill ({f}): sessions a person starts here learn to use the runner'
