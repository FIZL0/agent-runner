# TODO — open tasks, in order

### Next

- [ ] **R2** Slots on Remote Control (remote_slots = true) still push to the phone, even with .runner/quiet-slots (CLAUDE_CLIENT_PRESENCE_FILE) and agentPushNotifEnabled/inputNeededNotifEnabled false. Find out which push it is (session started/connected, or needs input / finished) and whether any setting or env stops it, from the Claude Code binary and docs (see R1's notes: presence pulses only go out once the session is registered, and the server decides on the push). If something works: wire it in for slots and say how it was checked. If nothing can work: remove the quiet machinery for slots (the quiet-slots presence file and the slot notification settings), so remote_slots just means on, with pushes. Say so in the README/CHANGELOG under remote_slots, and keep remote_slots off by default. Leave the quiet launch for control sessions and the server alone unless the same finding proves it useless too, and then say so in the notes. Check: tests pass after the change; anything that needs a phone to confirm goes in a CONFIRM: block. | files: agent_runner/runner.py, tests/test_runner.py, README.md, CHANGELOG.md
### Follow-ups
