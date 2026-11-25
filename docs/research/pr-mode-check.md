# T26: PR mode end to end

Checked on 2026-11-25 from agent-runner on branch task/T26. The run of this branch's code went from 10:31 to 11:08,
with `[git] pr = true` and `[plan] repo` set.

## Verdict

PR mode works end to end on a real GitHub repo. Three bugs are filed: B820, B821 and B823. Only B820 touches
work. An answer given with `plan unblock` can be lost, so the session blocks again on the same question. That
is recoverable, and `plan confirm` works.

## Earlier blocker

A private repo of a free GitHub account cannot have a ruleset or branch protection on main. GitHub answers HTTP
403, so PR mode is refused at start. This held for both logins used (FIZL0 and RyanAHayden). The person then
chose a public scratch repo, and the run below used it. Task D10 (open) is to say so in REFERENCE.md.

## Setup

- Public FIZL0/pr-mode-scratch, with a ruleset on main: pull request required, no bypass (`current_user_can_bypass`
  "never").
- Private FIZL0/pr-mode-scratch-plan, as the `[plan] repo`.
- `pr_max` 4, 2 slots, haiku sessions.
- A GitHub Actions check that fails when a `notes/*.txt` file does not end with "end". The local gate does not
  check that.
- Five small tasks, F1 to F5. T26's session played the people with the two logins: FIZL0 (also the run's own login)
  merged, closed and answered; RyanAHayden reviewed. No real person looked at the pull requests.
- Both scratch repos were deleted after the run.

## Seen working

- The start was accepted. Each finished task pushed its branch and opened a PR (#1 to #4, #6, #7, #8).
- `pr_max` 4: F1 waited while four PRs were open. Status said "4 pull requests are open: no new task starts until
  you merge or close one". It started once one was closed.
- `status` and `needs` list each open PR with its link and its pull request state: waits for review, changes asked,
  conflicts with the main branch, CI red.
- Merges: #6 squash, #2 merge commit, #3 rebase, #4 and #8 squash. Each was ticked at the run's next look or two. Local main
  fast-forwarded, and the task branches were deleted on the remote. The activity list showed no force push.
- Red CI (#3): the feedback round resumed by itself, one session. The task text conflicted with the check, so the
  session blocked with a DECIDE and did not weaken the check. After the answer (`plan confirm`) it pushed the fix,
  the check went green, and it merged.
- Conflict (#2): a person's PR #5 changed the same line. The session merged main in, kept both sides, ran the
  gate and pushed. The PR became mergeable.
- Change request (#4): a review by RyanAHayden, made while they had only read access, was ignored. The key is kept
  as seen, so it stays ignored once they have write access. After write access, a line comment and a change request
  resumed the session. The session did the first asked change ("FIVE" is done) and declined the second with a
  reason. It replied on the thread, with the hidden mark, and as a PR comment. GitHub refuses the merge while the
  change request stands. The reviewer approved, and then #4 merged.
- Closed (#1): Needs you showed it in under a minute, with who closed it and their reason. After an answer the
  task resumed and opened a new PR (#7, then #8).
- GitHub had a minor outage from about 10:44 to 11:03 (502s, GraphQL errors). The run retried each minute and
  recovered. #8 was made even though gh's create said 502. The run found it by its branch, so it did not open a
  second one. The merged tick of #4 landed during the outage.

## Filed bugs

- **B820** (answer lost): an answer given with `plan unblock` is lost in a PR round. The log says "It is open
  again; no answer was noted". F3's session blocked again on the same question. F5's #7 was opened identical to the
  closed #1. `plan confirm` works.
- **B821**: `run plan` with no arguments, under `[plan] repo`, ends in an IndexError traceback.
- **B823** (low): the log says "its round on pull request #0 is over". A reopened PR keeps its old time in Needs you.

## Rough, not filed

- During an outage the same log line repeats each minute. gh's message holds a changing request id.
- F5's PR body still said "six" after its file held "SIX". The session did not rewrite its PR body in the round.
  F4's did.
- After F5's later answer, #8's title keeps the task's first words. The task's line is not edited.

## Not checked

- Classic branch protection.
- A private code repo. It needs a paid plan (D10).
- The `[run] approve` refusal.
- A direct push to main being refused after the ruleset (the run's start only read that it cannot be bypassed).
- The run page and the terminal UI: `web` was off, so only `status` and `needs` were looked at.
- The spec review line: `review` was off.
- Three failed tries.
- Split tasks' shared PR.

## To turn it on

A repo needs:

- a GitHub remote;
- `[plan] repo` set, with the plan in its own git repo;
- a ruleset on main with no bypass;
- to be public, unless the account has a paid plan.

The person must pick the repo.

No runner.toml in `~/repos` sets `[plan] repo` yet. GitHub lists no rules on main for agent-runner, openmx, opentennis,
partyboard and iFizBox; classic protection was not looked at, nor were the other repos. Clay is private and the logins
here have write access at most, so its owner would have to set the ruleset.
