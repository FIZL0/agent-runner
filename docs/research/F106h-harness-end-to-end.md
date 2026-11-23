# F106h: end-to-end check of the stream engine, the harness loop and Copilot

Run on 2026-11-23 from agent-runner on branch task/F106h, in a scratch project with no remote, with `run once`
and Claude Code 2.1.330.

## Verdict

Not finished. The Copilot half could not be run because there is no Copilot login, so `[run] engine` stays
"terminal", and REFERENCE.md and SETUP.md are unchanged.

Still to do once `run login copilot` is done:

- the same D task on copilot (fence, ask with answer, finish);
- flip the default engine;
- update the test that asserts "terminal" (tests/test_runner.py, test_stream_engine_f106b);
- update the docs.

## What was checked

1. **Stream engine (`engine = "stream"`), Claude, D2 (docs/stream.md).** Started 10:36:10, exited 10:36:30 after
   6 calls with `run finish` ("docs only, gate skipped"). Merged and ticked.
   - The stream's init event had `apiKeySource` "none" and model claude-sonnet-5-5. The D task ran on that
     model; the `[models] code` setting was opus.
   - The rate_limit_event was seven_day, utilization 0.25, isUsingOverage false.
   - The result was success, 6 turns, total_cost_usd 0.197, 818 output tokens.
   - The outer shell had no ANTHROPIC_API_KEY set.
   - `claude -p /usage` before and after both showed "You are currently using your subscription" and "Current
     week (all models): 26% used". One small task is under the 1% display step and other sessions ran at the
     same time, so this does not show a change. The evidence of plan usage is `apiKeySource` none and the
     seven_day limit event.

2. **Harness loop on Codex.** This is a substitute for Copilot: Pi's auth.json has a codex OAuth login, and
   Codex is not what the task named.
   - codex:gpt-6-luna, D1: `git push origin main` through bash was denied by the fence ("the git fence: no
     `git push` here. `run done` pushes your task branch; the runner pushes the merge."). The agent then wrote,
     committed, ran done and finish. Merged and ticked. It did not call ask, although the task said to; it
     chose "Hello" itself.
   - codex:gpt-6-luna, D3 (the task says only the person knows the code word, so the first call must be ask):
     in two runs, its one call was the finish tool, with a summary saying it could not be done. No file was
     written and nothing was blocked. The run logged "D3: no commits — nothing to merge" and left D3 open. The
     brief's opening says never to ask a question here; that is a plausible cause, not established.
   - codex:gpt-5.6-terra, D3: called ask. The run logged "asks the person: Which code word?… parked as
     asked/D3" and D3 was listed under Needs you. `plan confirm D3 heliotrope` was run. The next run logged "D3
     resumed with the person's answer"; the same transcript file kept its history. The agent wrote heliotrope,
     ran done and finish. Merged and ticked. Git push was not tried on this model.
   - So ask, the fence and finish each worked on the harness loop, across two models, though not all in one
     task.
   - Transcripts are Claude-shaped in `.runner/harness-sessions`; usage carries a cost per call.

3. **Copilot.** Pi's `~/.pi/agent/auth.json` has only openai-codex and anthropic. `run login` lists
   `copilot ✗ no login: …/run login copilot`.
   - D4 was pointed at copilot with `[models] code = "copilot:gpt-5"`. `run once` logged "D4: not started:
     copilot has no login; … login copilot is under Needs you" and held D4 with that reason, so the F106e hold
     works.
   - `run login copilot --enterprise ""`, run with no person present (stdin /dev/null, timeout 20-40 s), ended
     on the timeout (exit 124). The device code waits for a person to approve it on github.com.
   - The copilot.lua login in `~/.config/github-copilot` and the Copilot CLI's own login were not copied over.

## Not checked

- Copilot itself.
- A tell into either session.
- A gate that is not docs-only.
- Pushing.
- Fallback.
