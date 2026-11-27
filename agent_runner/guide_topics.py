"""The `guide <topic>` pages, split from guide.py (C59). Import TOPICS through agent_runner.guide."""
from __future__ import annotations

from agent_runner.guide_text import *  # noqa: F401,F403

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
concept's id. File each page once: publishing it again to the same file keeps its link. Put no answer buttons
on the page (they do not work in the Claude app): the person picks in Concepts or Needs you on the run page, or
in the chat. While the concept is
shown here, a question or a change in their reply, even after "yes", "good" or "very good" ("yes its good, does it
still handle X? Y should have Z too"), is not a pick: answer it, update the same page (publish it again to the
same file, then `open`), and build nothing. Once a filed concept's page is published again, run `{cmd} plan
concept-updated <its id> "<what changed, a few words>"` (with `--file <the page>` when you have the page as a
file, so the run's copy is refreshed): the same link hides the change from the run, which then
shows the concept as Updated. Queue the build only on a plain go with no change asked ("build it",
"queue it", "go with B"): `{cmd} plan approve <the concept's id> "<the option they chose>"`, not a fresh `plan
add`; a no or another direction: `{cmd} plan revise <its id> "<what to change>"`.
Queue a concept (`{cmd} plan add K "..."`) only when they say queue it, later, or add a task. Queued one by
mistake and they say "do it here", "here", "now" or "here and now"? `{cmd} plan drop ID "shown inline"` and
write the page here, with no question, even when a slot already took it: the drop stops that slot's session and
deletes its branch, so nothing builds the dropped concept.
Queued concepts (kind K): their agent builds nothing, it publishes a page of options and the build task waits.
`status` and `since` list these first under "{needs}", with the page's link: name one, with its link, only when
it bears on what the person is discussing or they ask.
""" + CONTROL_SHELL + """
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
An item `ready-F290`: what a landed task made for them to look at or use (a video, a post); the task is done.
Looks good: `{cmd} plan confirm ready-F290`; change it: `{cmd} plan change ready-F290 "<their words>"` (files a
follow-up); not now: `{cmd} plan shelve ready-F290`.
A DECIDE whose question ends in a bracket, `[Full (recommended) / Small]`, or whose ask file has `options`, shows
them as answer buttons (F181c): a name they reply is `{cmd} plan confirm ID "<the name>"`.
A DECIDE with several questions (F18, `[run] questionnaires`) has a pick sheet: its line reads "<what is ready>. Pick
on the sheet or reply go" with the sheet's link; give the link (call the Artifact tool's `open` on it). The
sheet's Send writes their picks to the sheet's artifact db (F54): when they say they sent it ("sent",
"done", "picked"), and whenever you show that item again, read it with the ArtifactData tool (`get`, the
sheet's url, collection `picks`, doc_id the ID); if the document is there, run `{cmd} sheet R7 --picks
"<its picks field>"`. An older sheet, or one whose write failed, gives a line like `R7 picks: backend=a
batch=b` to paste instead: run `{cmd} sheet R7 --picks "<that line>"`. "go" (or "recommended") is `{cmd}
sheet R7 --go`. A sheet with no link opens on the run page (Open on its Needs you item). Each of these reopens the task with every answer spelled out in its note, so the sheet
command is the whole answer (`plan confirm` is for items without a sheet).
An item can be settled in another session, on the run page or in the TUI while you wait (F160). Re-read it (`{cmd}
plan ID`) right before you ask the person to do something for it, and again on each follow-up about it. If it is
settled (dropped, done, answered, changed), say so at once, ask nothing more for it, and stop every watch and undo
any reservation you made for it. A message starting "From the runner, not the person:" is the runner telling a
chat about that item that it was settled: it is not the person's reply; re-read the item and do the same. A
`DECIDE:` line you were waiting on that still stands ends your answer again, or it is never filed. This
goes only for the item the chat is about; leave the others alone as your brief says.
""" + DECIDED + """ That holds for
an item of another chat too.
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
