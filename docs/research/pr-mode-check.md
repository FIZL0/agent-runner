# T26: PR mode end to end

Checked on 2026-11-25 from agent-runner on branch task/T26, with `[git] pr = true` and `[plan] repo` set. The
check covers the start of PR mode (the [git] pr setting), not a whole run of it.

## Verdict

Not finished. The trial did not start, because no GitHub login on this machine can protect main of a private
repo. PR mode is refused at start, and the refusal names the cause.

## What was checked

1. **Scratch repos.** FIZL0/pr-mode-scratch and FIZL0/pr-mode-scratch-plan were made with `gh` as FIZL0 (admin),
   so creating a private repo works.
   - A ruleset requiring a pull request on it: HTTP 403, "Upgrade to GitHub Pro or make this repository public
     to enable this feature."
   - `GET rules/branches/main`: the same 403.
   - Both scratch repos were deleted after the check.

2. **Other login, RyanAHayden.**
   - Reading rulesets and branch protection of its private clay-plan: the same 403.
   - Reading rulesets of its public iFizBox: `[]`, allowed.
   - No repo was made under this login.
   - The plan field was not readable with these token scopes, so the plan is inferred from the 403.

3. **Live start.** `run setup` and `run run once` each exited 1 with:
   "agent-runner: PR mode ([git] pr = true) is refused: GitHub did not say how main is protected (gh: Upgrade to
   GitHub Pro or make this repository public to enable this feature. (HTTP 403))".
   - The run home stayed empty.
   - Nothing was written to the plan repo.

4. **Public repo not used.** The task says private, and publishing is the person's choice. The protection check
   was not stubbed to go on, because the result would not be PR mode.

## Not checked

- A task merged on GitHub.
- A change request.
- Red CI.
- A conflict.
- One closed.
- `pr_max`.
- The display of PR state, against real GitHub.

## To go on

- A paid plan on FIZL0, or the person allowing a public scratch repo.
- Then: a ruleset on main with no bypass.
- Then: a second account for the change request. GitHub does not let an author request changes on their own
  pull request. RyanAHayden could be invited, with `GH_TOKEN=$(gh auth token -u RyanAHayden)` per command so the
  active account stays.
- Then: ask which repo to turn PR mode on for.
- A consequence: PR mode cannot be on for a private repo of an account on the free plan.
