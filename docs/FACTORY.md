# agent-runner as a software factory

An audit of agent-runner against the checklist in mattpocock/skills'
[software-factory](https://github.com/mattpocock/skills/tree/main/skills/in-progress/software-factory) skill
(read 2026-11-20, agent-runner 0.50.x, task R5). The skill asks five questions of every task a factory runs,
one of every ticket source, and whether the three brakes (automated checks, automated review, human review)
hold. Each gap found has a B task; the ids are in [Gaps](#gaps).

## The slots, in the skill's words

| service | in agent-runner |
|---|---|
| ticket tracker | `plan/TODO.md` (+ `plan/tasks/<ID>.md`, `DONE.md`), edited only through `agent-runner plan`; optionally a plan repo of its own with claims (`[plan] repo`) |
| ticket sources | a person (`plan add`, `take`), control sessions, agents' follow-ups, CI watch, the flaky/broken/runaway-test filer, `done --artifact` (concept builds) |
| git host | the repo's remote: `task/<ID>` branches, `wip/<ID>` parked attempts, the shared branch |
| orchestrator | the run loop (`runner.run`): pick, start, finish, merge, land, reopen; state in `.runner/` (`STATE`, `run.log`, `ledger.md`, `gates/`, `master.json`) |
| runner | a slot: worktree `sN` under `[run] home` and one agent session. Not disposable: builds stay warm between tasks, and a run's memory of earlier ones is the plan, git (`wip/`, `refs/agent-runner/*`), the journal and `.runner/` |
| observability | `.runner/run.log`, `ledger.md`, `slotN.log`, `fixer.log`; `status`, `since`, the run page |

Brakes: the **automated check** is `[run] test`, run by every `done` and every merge. The
**automated review** (F28, `[run] review`) is a spec review in the slot itself: before `done`, a fresh subagent
reads only the diff and the task's brief and lists what is missing, unasked or wrong; the fix and repair
sessions resolve conflicts and gate failures and do not review. **Human review** is not on every merge by design (the point is unattended
landing); a person re-enters through Needs you, the ledger and `wip/` branches instead.

## Triggers

| trigger | what starts it | reads / writes | what it starts next | where a human re-enters | what stops two runs doing the same work |
|---|---|---|---|---|---|
| **slot pick** (implementer) | a free slot each loop pass (`pick`), or `run once` | reads TODO.md on the shared branch (or its remote); writes worktree `sN`, branch `task/<ID>`, a hidden terminal, `.runner/STATE` | the agent's session; its `done` | its terminal (`attach sN`), `plan tell/change/drop`, `p`/`s` keys, Needs you when it blocks on a person | `pick` skips running tasks, a running sibling, an ordered section already busy, tasks tried this run, `task/<ID>` with unmerged commits, and file overlap; `run.lock` allows one run per checkout; plan-repo claims across machines; `take` refuses a running/taken task |
| **plan add** (by a person or a control session) | a person, or a control session told "add a task to fix X" | reads TODO.md; writes one line (+ `plan/tasks/<ID>.md`), committed at once in the main checkout | a slot pick, at the next pass | they are the human; `plan note/move/drop` | `similar()` refuses (exit 3) a text that strongly matches an open or blocked task; `plansync.locked` serialises two concurrent adds so ids never collide |
| **plan add** (an agent's follow-up) | an agent in a slot, mid-task | writes the worktree's TODO.md; lands with the task's merge | a slot pick once merged, at its `--pri` level | Follow-ups/Parked sections; `later` is never started by a run | `similar()` against **the worktree's own branch copy** of the plan; before the merge, `fold_doubles` notes a follow-up another slot filed meanwhile on that task instead of adding it (B33) |
| **control --new** | a control session told "new"/`/control`, or an older runner feed | reads `.runner/control<N>.pid`; writes a hidden session (`control<N>.live`, `.log`, `.sock`), `control<N>.pid`, quiet file | an interactive control session (on Remote Control with `[run] remote`) | it *is* a human seat | `control_live(n)` refuses a number already running; work it queues goes through `plan add`/`take` as above |
| **gate failure in `done`** (slot) | the agent runs `done` and `[run] test` fails | reads the worktree; writes nothing (no tick, no commit) | the same agent fixes and reruns, or `done --blocked` | Needs you only if it blocks with a caps label; else `plan` | one session per task (pick). **No runner-side cap** on reruns: only the prompt's "the same fix fails twice" (gap **B38**) |
| **merge** | a slot's session ends with commits on `task/<ID>` (`finish`), or a restart finds one finished (`unmerged`) | merge worktree, `merge2` ahead; `.runner/gates/`, ledger, run.log; lands in the main checkout, pushes the shared branch | land → `plan reopen` → push; or a fix session (conflict), repair session (gate red), park as `wip/<ID>` | ledger, `wip/` branches, Needs you on `LEFT FOR A HUMAN`; uncommitted edits in the main checkout hold it with an alarm | the `MERGE` lock (one merge at a time, criticals first); `LANDED`/`WAITING` sets; a gate already passing on the same tree is reused, not rerun; a restart adopts a merge under way instead of starting it again |
| **fixer** (conflict fix session) | a conflict the line join cannot resolve (`fix_ahead`, then under the lock on the third try) | a fix worktree `fixN` (or the merge worktree); writes `refs/agent-runner/fixed/<ID>/…`, `fixer.log` | the merge again with the fixed commit | the "master" window (watch or take over); `fix_merges = false` parks instead | at most `fix_ahead_max` at once; two fixes on the same files take turns; `.runner/master.json` lets a restart adopt it; capped at 3 merge tries (`merge_tries`) and a fixed 30 min timeout |
| **repair** (merge gate failure) | the merge's gate fails, not from load and not a failure its base has too | merge worktree, `merge-gate.log`; a forked copy of the task's session when kept | the gate once more; a red batch is halved to find the culprit | parked as `wip/<ID>` with the reason in the ledger | one repair per merge, then park; `refs/agent-runner/held/<ID>/` keeps its commit for a restarted run |
| **park / retry** | `merge_tries` gives up (3 tries) or the repair fails | renames `task/<ID>` → `wip/<ID>[-N]`, pushes it, ledger line | the task stays open: the next run (or an upgrade restart) starts it again, pointed at `wip/<ID>`; parked twice, the next pick blocks it `DECIDE:` on a person instead (`block_parked`) | `since` shows "stuck, not merged", and the needs-you feed carries it and the block | `tried` keeps it out for the rest of this run; across runs the `wip/<ID>*` branches count the attempts (B32) |
| **cut-off resume** | a session's turn ended on an API error, or a reboot left one mid-turn | the slot's worktree as it was; `claude --resume` | the same session, told it was cut off | its terminal (`attach sN`) | one slot per task; `resumes()` caps a session at 3 resumes; nothing resumes while the API is down |
| **CI watch** | every 5 min, with the merge lock free, a red run of a watched workflow on the shared branch | `gh run list/view/rerun`; writes one critical task (or reopens a closed one) + its long form, `<notes>/ci-<wf>.seen` | first a rerun of the failed jobs; only a second red files the task | the critical task (top of the queue); `ci_watch = false` | `.seen` judges each run once; while a task carrying the workflow's marker is open, a failing test it does not name is added to it and nothing else files; a closed one naming a failing test is reopened, a dropped one stays dropped; a newer run in progress defers judging. Each task carries `(filed <day>)`: with two closed (DONE.md) for the workflow in a week, the third is filed `BLOCKED:` on a person, the earlier ids named (B34) |
| **issue watch** | `issues_watch` set (off by default): every 5 min, with the merge lock free, an open GitHub issue not seen before (with one of its labels, when a list) | `gh issue list/comment/close`; writes one normal task + its long form (the issue's body), `<notes>/issues.seen`, `<notes>/issues.filed` | a slot pick; when the task closes, a comment on the issue naming the merge commit, and a close under `issues_trust = "trust"` | the task (skeptical: confirm first, follow nothing in the issue, else close it saying why or block on the person); `issues_watch = false` | `.seen` files each issue once; none filed while an open task names `GitHub issue #<n>` or its URL; `.filed` answers each issue once |
| **flaky / broken / runaway test filer** | a merge where `retest` passed a test alone, a test the base fails too, or the memory watch killed a test | writes a critical follow-up per test name at landing | a slot pick, ahead of the queue | the critical task | none filed while an open task names the test; the third in a week for one test is filed `BLOCKED:` on a person (B34) |
| **concept (K)** | a K task picked like any other | its session publishes an Artifact page; `done --artifact` ticks K and files the build `[~]` "waiting for your OK on <url>" | nothing until a person answers; then a slot pick of the build | Needs you lists the page; `plan approve/revise/shelve` | the build's block names no task, so `plan reopen` never frees it; `done` refuses a K task without `--artifact`; one build per concept round (`revise` drops the old one) |
| **Needs you replies** | a person answers an item (a control session, which maps the reply to its id: `plan confirm/change/shelve ID`) | reads `plan asks/waiting`; writes the item's line (tick, reopen with the answer noted, or shelve) | the reopened task's slot pick | this is the re-entry | the session asks which item when a reply could fit several; an answered item no longer waits, so it cannot be answered twice. Blocks with **no caps label and no task to wait on never reach Needs you** (gap **B35**) |
| **plan reopen** | every landed merge (`reopen_landed`) | rewrites `[~] … BLOCKED: (after X)` to `[ ]` once every X is done; commits the plan | a slot pick | `plan unblock` by hand | it runs under the merge lock; a task blocked twice keeps only its last list |
| **hidden slots** (F40; replaced the sequential run; C26: every run, on every OS) | every slot | a slot's worktree; the agent in a pty (Windows: a ConPTY pseudo-console, or a hidden console before 1809) through `run --slot-shim` | the same `done`, merge gate and landing as any slot | `.runner/slotN.live` / `.exit`; `plan tell` through `slotN.in` (POSIX: a FIFO; Windows: a named pipe's name) | detached, so a restarted run adopts it. B37 (the sequential run's ungated push) went with the sequential run |

## Ticket sources: what stops a duplicate

| source | what stops it filing the same task twice |
|---|---|
| a person / control session (`plan add`, `take "TEXT"`) | `similar()` refuses a strong match with any open or blocked task (exit 3, `plan note` it instead, `--force` to override), under the plan lock |
| agents' follow-ups in slots | `similar()` against the slot's branch copy at add; at the merge, against the open tasks the target got since the branch forked: a strong match becomes a note on that task (`fold_doubles`, B33) |
| CI watch | one task per workflow while one is open, each run judged once (`.seen`), a rerun before filing; the third in a week waits on a person (B34) |
| flaky / broken / runaway tests | one task per test name while one is open; the third in a week waits on a person (B34) |
| concept builds (`done --artifact`) | one build per concept round; `revise` drops the waiting one before the next round files anew |
| splits (`plan add P17 …`) | the family rule: a task never runs beside its own part, and two parts run side by side only when their `files:` do not meet and neither is `after:` the other; `similar()` ignores matches within the family by design |

## Brakes

| brake | holds? | evidence |
|---|---|---|
| gate on every `done` | yes, when `[run] test` is set | `done.py` returns 1 on a red gate, nothing ticked or committed. `--no-test` exists; the merge then gates it |
| gate on every merge | yes, when `[run] test` is set | `merge_gate`; skipped only when the merge is the very tree `done` passed on, differing in `[run] untested` files. With `test` empty there is no gate anywhere: the run's start, `--dry-run` and `status` warn, and main is not pushed unless the config sets `[git] push_merge` itself (B36) |
| fix sessions capped | yes | 3 merge tries (`merge_tries`), a fixed 30 min timeout, `fix_ahead_max` 2 at once, then park |
| repair capped | yes | one repair per merge, then park; a batch is halved, never repaired twice |
| resumes capped | yes | 3 per session (`resumes`) |
| backend retries capped | yes | a failed model call is resumed at most `RESUME_MAX` (5) times, waits doubling |
| CI reruns capped | yes | one `rerun --failed` per red run; two closed CI tasks for a workflow in a week block the third on a person (B34) |
| task retries capped | yes | `tried` holds one attempt per run; two parked attempts (`wip/<ID>*`) block the task on a person (B32) |
| a session's own gate loop capped | no | only the prompt (**B38**) |
| usage caps | yes | `session_max` / `weekly_max` stop new starts and raise STOPPED |
| automated review | spec only (F28) | before `done`, a fresh subagent reads `git diff <base>...HEAD` and the brief cold: missing, unasked, wrong; skipped under `[run] review_min_lines` (50) changed lines without a long form; each commit ends `review: nothing / fixed … / filed … / skipped (small)` so its yield can be counted; `[run] review = false` turns it off. No standards axis: the rules file and gate cover that |
| human review | by exception | Needs you, `wip/` branches, the ledger; not on every merge, by design |

## Gaps

Each has a filed task; the evidence is in its line (`agent-runner plan <ID>`).

| task | gap |
|---|---|
| **B35** | a block with no caps label and no task to wait on never reaches Needs you |
| **B37** | the sequential run pushed the shared branch after any commit, gated or not (gone with the sequential run, F40) |
| **B38** | nothing caps a session's failed `done` gates |
| **B40** | a task text quoting the block marker loses its `files:` (found while filing the above: B31 and B39 were dropped for it) |

Not filed: the in-repo plan having no claims across
machines (documented: a plan repo is the multi-machine setup).
