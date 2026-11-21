# R12: an iFizBox task filed in agent-runner's plan

## What R12 asked

Why the iPhone 7's Home Screen icon kept the old badge (1) on the first launch after `apt-get install` of a new
iFizBox .deb, while the page had counted 2. The repro it named,
`journal/2026-11-21-r65-badge-after-run-iphone7/notes.md`, is not in agent-runner: it is in iFizBox (task R65,
worktree `~/runs/iFizBox/s1`, branch `task/R65`).

## How it got here

R65's session (iFizBox slot 1, transcript `~/.claude/projects/-home-ryha-runs-iFizBox-s1/01ca718c-….jsonl`,
2026-11-21 20:36Z) ran:

    cd /home/ryha/repos/agent-runner && ./run plan add R "iPhone 7: on the first launch …" --files 'journal/**' --pri low

`run` finds the project from the current directory (`config.toplevel`), so the `cd` made agent-runner the
project: the task went into agent-runner's `plan/TODO.md` as R12 and was committed on agent-runner's main
(d713dba). The brief told the agent to call `/home/ryha/repos/agent-runner/run plan add` by path; it `cd`'d into
the runner's folder and ran `./run` instead. Nothing stops this: a slot's environment has `AGENT_RUNNER_SLOT`
but not which project or worktree the slot works on (`slots.slot_env`), so `plan add` cannot tell it is
writing another project's plan.

## What was done

- Re-filed in iFizBox's own plan as **iFizBox R69** (low, after R65, files `journal/**`), with the code reading
  below, so the badge question is worked where its code and phone notes are.
- Filed agent-runner **B103** so a slot cannot write another project's plan again.
- This R12 is closed with these findings; no iFizBox code was changed.

## The iFizBox question, from reading the code (not the phone)

- `web/app/settings.js` `updated()` (B158, first launch of a new version) sends `app.badge 0`, then Changes'
  count. `native/Sources/Notifications.swift` `app.badge` stores `pageCount`, then `setIcon` →
  `getNotificationSettings` → `applyIcon` → `UIApplication.applicationIconBadgeNumber` (iOS 15 branch).
- The icon showed neither the 0 nor the 2: it stayed at the daemon's 1. So the order of B158's two counts is not
  the cause; every set on that launch was lost on the iOS side, after `pageCount` was stored.
- Suspects for R69 to test on the phone: SpringBoard's record of the app right after `uicache` (the set lands
  only after SpringBoard re-reads the app, or after a delay), and badge authorization reading `notDetermined`
  after the reinstall (`setIcon` then waits on `requestAuthorization`). A log line in `applyIcon` tells whether
  it ran at all. Whether an iFizBox B is needed is R69's to answer.
