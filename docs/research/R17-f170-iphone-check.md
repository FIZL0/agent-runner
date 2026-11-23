# R17: F170's chat controls on the iPhone 15 (not yet checked)

No product code changed; this is research only. **The check could not be done yet, because F170 is not on the page the phone can reach.**

## What was found

- The rig works: the iPhone 15 Pro (iOS 27.0.1) is attached and listed by `ios list`; the tools are `~/repos/iFizBox/tools/ui-15.sh` and `docs/iphone15.md` there (WebDriverAgent, take its lock first).
- Runner Home (port 8770, the Tailscale https link from `agent-runner home status`) serves the installed run, **0.62.0**. Its page has no F170: none of `feedFoot`, `ar-box` or the Force send / Stop buttons are in it (8 matches in this branch's `agent_runner/web_page.html`, 0 in the served page). Judging it there would judge the old chat window.
- Putting the new page in front of the phone needs either a release (V5 is open) with `agent-runner upgrade`, which restarts the person's running run, or a second run of this branch beside it. Neither is for an unattended task to do: the first restarts every session, the second needs its own ttyd sessions, tokens and ports on a machine with a live run.

## What to check once F170 is served (the task's list)

Open a chat with a real session at `/p/agent-runner/` in Safari on the phone (390 pt wide, Tailscale link), with Claude working:

1. The hidden bottom lines stay hidden while the agent redraws (a working spinner, a long reply): no line flashes at the frame's edge.
2. Scroll up in the session: chips, message box and top bar go with the finger and come back on scrolling down, with no jump.
3. Tap the box: the keyboard opens and closes with the box, chips and frame gliding to their place, no gap, no pan of the page.
4. Box lines (`ar-box` font) join with no gaps in Safari, in light and dark (`/wda/device/appearance`, and put it back).

Record each as pass or fail with a screenshot (`ui-15.sh ME shot NAME`) in `docs/research/R17-samples/`, and queue a B task for each fail. Rules to confirm or correct in `docs/STYLE.md`: "Its bottom lines are past the edge", "The session", "Keyboard".
