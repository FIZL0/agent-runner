# Changelog

Semantic versioning; what counts as breaking is in [docs/SETUP.md](docs/SETUP.md#versions).

## Unreleased

- Added: while a run is up, it reads the until checks blocked tasks wait on every 2 min, each check once a round, and reopens a task once all of its checks pass, committed as a merge's reopening; a check that cannot run for 30 min, or has not passed for 3 days, is one Needs you item that says which check, its last words and how to free the task (F427c).
- Added: the run knows a concept's New and Updated: never opened is New, changed after its details popup was opened is Updated with a few words on what changed; one record every device shares. `plan concept-updated K "<what changed>" [--file PAGE]` tells the run a page republished at the same link changed, and the run app's `concept_opened` action (or `plan concept-opened K VERSION`), sent when a concept's details popup opens, clears both; the guide's concepts topic tells chats to run the first (F197a).
- Changed: on the run page, the Run card's More… sheet lists every run control shown now (slot +1 and -1, pause or go on, stop or take the stop back, Start the run while no run is up joined it), each row with its icon on the left and its key in `agent-runner ui` on the right (B763b).
- Removed: the pick-links command and the concept branch of /pick; an old concept link answers with a short page saying to pick in Concepts and changes nothing; a pick sheet's Send still answers (C40b).
- Added: a chat whose answer ends on several questions has each filed under Needs you as an item of its own, a question with no options too, in one commit; a retry files none twice, and the chat closes only once all are filed (F192b1b).
## 0.84.0 (2026-11-28)

- Changed: a new chat started from Home's message box goes the way one from + does, one row reading Starting the chat… until its name comes, now checked by a test (F196f).
- Changed: on the run page, a new chat's row in the sidebar stays one row from the send to the first reply: the same place and key, so the list does not redraw or jump while the chat starts (F196d).
- Changed: of several questions a chat ends on, an answer that names its question ("My answer to your question “…”: …") closes only that one, and an item answered under Needs you only its own; any other message closes all (F192b1c).

## 0.83.0 (2026-11-28)

- Changed: a new chat shows its first message's words in its row and header from the tap until it has its own title, never its bare number or New chat between (F196e).
- Changed: an open run page or Runner Home moves to a new version by itself once nothing would be lost or interrupted, back to the same view, chat and scroll place; otherwise the Refresh popup stays until then (F207).
- Added: a waiting change's Review page is written when it starts waiting, and linked from its pull request body and its done write-up (F515).
- Added: a change that waits on its task branch, or as a pull request in PR mode, has a Review page: `run review ID --page` writes it (diff, why, questions, how to answer) and `run review ID --ask "…"` asks about the change (F444d).
- Added: `[run] usage_limits = false` switches the usage caps off: the runner never reads account usage, never holds or falls back a task on `session_max` / `weekly_max`, and status hides them (F488).
- Changed: a diff whose only change to `pyproject.toml`, `package.json` or `Cargo.toml` is its description line counts as docs only, so `done` and the merge skip the gate for it (F494).
- Added: a model name can pin a Claude login, `claude@work:opus`, anywhere a model is named ([models] roles, kinds, sizes, fallback, `--model`); a session on it starts on that login, and when that login is capped it goes on with claude's next free login (F504).

## 0.82.0 (2026-11-28)

- Changed: `done.py` is split by area (`done_docs.py`, `done_refusals.py`, `done_writeup.py`), and its test is `tests/test_done_docs.py`; no behaviour change (C62).

- Added: session_max / weekly_max read each Claude login's own usage (from its own config folder's login), so a new task passes over every login past its caps, not only the default one (F514).
- Added: `status` names the Claude login each slot's session runs on, only when there is more than one login (F505).
- Added: on the run page, drag a chat's row into Quiet and back out, or a bulk select of chats all at once; the run keeps where they are, and a finger drags after a short hold (F507).
- Added: usage caps are kept per Claude login: a capped login goes on with the next free login, then `[models] fallback` (a local model normally last); session_max / weekly_max hold only the login they read; all capped and no local model waits for the earliest reset (F503).
- Added: `run login codex|copilot|gemini --as NAME` adds another login, kept in Pi's auth.json as `<id>@NAME` beside the default; `run login` lists them, and a harness session runs on that login when its model is `<provider>@NAME:<model>` or it is given `AGENT_RUNNER_LOGIN_AS=NAME` (F506).
- Fixed: on the run page, a chat message shows sent (no longer faded) as soon as the run takes it, not only once the chat's transcript has it (B878).

## 0.81.0 (2026-11-28)

- Changed: the settings area (types, checks, toml edits) moved from config.py to config_settings.py, no behaviour change (C61).
- Changed: a merge is not tested again when the shared branch moved during its gate only by the runner's own gated merges on other files; a hand commit, a shared file or a `runner.toml` change still tests it again (F493).
- Added: `run login claude --as NAME` adds another Claude login in its own CLAUDE_CONFIG_DIR, kept per machine; the first (Claude Code's own) stays the default login, and `run login` lists them. Each must be a separate real account (F502).
- Changed: lazyrunner's key bar lists every key of the mode; Concepts' panel is framed like Work, Tools and Settings; moving the highlight onto a chat shows that chat on the right (F484b)
- Changed: on the run page, a chat's question card shows whole when the question comes; a scroll up shrinks it to its small Decide pill, which stays at the bottom and grows back into the card on a tap or after 2 s still with no touch (F511).

## 0.80.0 (2026-11-28)

- Changed: the run page shows a person's own act (drop, cancel, rename…) at once, before the run answers, through one shared change in the page's act path; a refused act goes back; with no events stream the act's snapshot is fetched at once (F508)
- Added: `[run] issues_trust` takes `"contributors"` (trust OWNER, MEMBER, COLLABORATOR and CONTRIBUTOR authors), `"members"` (OWNER, MEMBER, COLLABORATOR) or a list of GitHub logins; the rest are filed skeptical, and each issue's close or comment follows its own trust (F510).
- Fixed: a page a chat published (publish-page from a chat) shows in the run page's Concepts for a week; it has no task, so it was left out (B875).
- Added: `[run] slot_memory` (default true) turns Claude Code memories off for slot sessions; the audit offers moving them into lessons (C49)
- Fixed: on the run page's Plan, a row dragged (mouse or finger) shows in its new place at once and glides only the last bit from where it was let go; before, the drag's shifts stayed on through the redraw and the rows jumped (B877).
- Added: a chat's history on the run page (Copilot and Claude Code alike) shows a thin grey scrollbar you can drag (F474).
- Added: a queue row in the snapshot carries the task's size (`size: simple`) beside its other fields (F485).
- Added: slot worktrees are built faster: the missing ones are prepared at once when a run starts, a slot past the count is kept as a spare worktree (with room on the disk) and reused by the next new slot instead of being built again, and each slow step of building one is logged with its time (F500).
## 0.79.0 (2026-11-27)

- Fixed: a release card in the Plan queue has Wait for… too: tick the tasks it waits for, in the place of the tasks above it (B870).
- Fixed: Home's Needs you lists a chat's DECIDE question at once, with its option buttons, an answer box and Chat, and counts it; before, it showed only once the run filed it, hours later, and never for a renamed chat (B832).
- Changed: a Plan row's hold, to the top, remove and Undo show as saving while sent, with no toast on success; a refusal puts the row back with a toast (F478).
- Added: a task's size, `plan add/edit --size simple|complex` (`size: simple` on its line); `[models] sizes` (empty, off, by default; e.g. `{ simple = "sonnet" }`) runs a size on its own model, over its kind's and under its own `--model`; a simple task that fails or blocks on it retries once on its kind's model; on the Settings page as Model for each size (F470).
- Added: with lessons on, `run done` asks for a lesson (or none) only after a failed gate in the task or a person's change to it in the plan, once per trigger, checks first; a merge repair's session may file one. It never holds up done (F414).
- Fixed: a release no longer waits on a task that waits for that release (directly or down its chain), so neither is stuck; the task runs after the release lands (B868).
## 0.78.0 (2026-11-26)

- Added: a pitch's Ask… on Needs you, beside Approve and Not this…: per change Ask about it (its answer shows under it, and on the Review page) and Ask for a better way (undone and its task reopened with what you want instead) (F444c).
- Fixed: a release ready to start but for the merge under way now starts before the merges waiting behind it; they go on as before when the release is held for anything else or cannot start (run paused, usage caps, no free slot) (B849b).
- Added: lessons, what a project's agents learned, one line per lesson in plan/LESSONS.md with the files it applies to; a brief shows those whose files meet the task's (most specific first, at most 8); `plan lesson add/list/drop`; a lesson whose files are all gone drops itself. `[plan] lessons`, off by default, on in this repo (F413).
- Changed: the run page's Status, Plan and History are one page, Work: the run bar and usage on top, then Now (what the agents work on and what merges), Up next (the queue, without what Now shows), Landed and Releases, with Parked and the Run log folded at the bottom; one search; old Status and History links open Work (F476).
- Added: the run page's UI settings (Settings → Look and layout): a theme (ryha, light, terminal, omarchy, from theme.py) or Standard, the Lazyrunner layout (from 760px: the sidebar as numbered panels Status, Sessions, Plans, Tools, Settings on the left, the view on the right, keys 1-5, j/k, Enter/l, h, i, Esc, a/d/p, c, ?) and a key bar; only a layout and keys over the page's own panels (F473).
- Changed: Hold on a running task (`plan hold`) stops its slot as Cancel does and holds it in its place; Cancel (the page's and `plan cancel`) now holds the task too instead of parking it, so no run restarts it until Unhold. Still refused while it merges, waits to merge, is taken by hand, or is claimed by another machine's run, which it names (F480).
## 0.77.0 (2026-11-26)

- Changed: `agent_runner/guide.py` is split by area into `guide_text.py`, `guide_topics.py` and `guide_control.py` (still imported through `guide`), and its control test is `tests/test_guide_control.py`; no behaviour change (C59).

- Added: when the usage caps hold new tasks, `status` says so first (which cap, its %, when it lifts) and the run page's Run card shows the same line; `force ID` lets just that task start past the caps (F468)
- Changed: a task whose gone run's claim is taken over starts from the task/<ID> branch that run pushed, not from a fresh fork (F467).
- Added: Settings has an "Ask about my settings" button at the top: it opens a new chat with a first message ready to edit (what settings fit how I use this project?); nothing is sent before Send, and the chat recommends each change in one line and makes only those you say yes to (F449).
- Changed: dropping a task as not wanted no longer starts the tasks that waited on it as if it had landed: each is held under Needs you with one question, still wanted? (Keep / Drop); `plan drop ID --duplicate-of X` or `--overtaken-by X` (or a reason that says so) has them wait on X instead while it is open, else go on. Tasks waiting on all before them and releases go on as before (B772).
- Added: Settings asks `[run] auto_audit` as a question (On / Off) while neither the project nor the device sets it; either answer is saved by the usual Save and the question goes (C55b).
- Changed: Settings, the Project file group (commands, files and folders, patterns, rules) is edited on the page like the rest, saved through the Settings bar; a list or table is a text box as wide as the row; a risky key says what a change does, and one that cannot change now shows why. Every open row keeps "Ask a chat to change it" beside More… (F448b).
- Fixed: auto release by count (`[run] auto_release` every) is queued at the landing that reaches the count, so merges back to back no longer hold it off (B849a).
## 0.76.0 (2026-11-26)

- Fixed: a concept card's framed options page no longer reloads, or loses its scroll place, when the Home view redraws (B860).
- Changed: Settings has two tabs, Project (runner.toml) and This device (runner.local.toml); every row edits the file of the tab in view, a row this device overrides shows its value on Project, Changed counts per tab, and the Settings bar names both files (F462)
- Changed: `home install` sets up Runner Home's Tailscale Serve https address without asking (or says why it stays http only), then asks once in a terminal whether devices on the tailnet may open Home without the key, default No (F461).
- Fixed: a chat closed for being idle stays in Chats, grayed under Quiet, until chat_quiet passes, and a message to it reopens it; before, it vanished from the list. A chat closed from the TUI or the run page still goes at once (B859).
- Added: a task taken by hand has Cancel on its queue row in the run page and the terminal UI (it keeps the work and parks the task), and no Priority or Do it here while taken (F455b).
- Fixed: `home install` on a machine whose run page had a Tailscale Serve https address keeps it: the page leaving its port hands its Serve rule over to Runner Home instead of turning it off, so the printed https link works and `home status` lists it; a rule a person made is never touched (B847).
- Changed: on the run page, a chat that a Needs you answer started goes straight to Quiet in Chats with a 'new' label until opened once; it moves to the top only when it asks you something (F465).
- Changed: in Settings, Main branch is now Working branch, in Landing work instead of the read-only Project file: a pick of the local branches that says, before Save, what Save does and that it applies once the run restarts, and why a pick cannot be saved (F447a).

## 0.75.0 (2026-11-26)


## 0.74.0 (2026-11-26)


- Added: with `[run] approve`, a pitch's page is now its Review page. Each change shows its diff (`[run] approve_diff_lines`) and the questions you asked with their answers. `agent-runner pitch ask pitch1 F1 "…"` asks about a change, and `pitch better pitch1 F1 --why "…"` asks for a better way: the change is undone and its task reopened (F444).
- Added: a bug task whose files meet those of a task waiting for the person's check (CONFIRM under Needs you, not shelved) waits until that check is done; critical and high tasks pass, and the dry run says which check it waits for (F415).
- Fixed: on the run page, a new chat you start reads Starting the chat… until its first reply (at most 2 minutes), not Loading… or ended while its session comes up (F196).
- Fixed: on a computer the words of a chat's live screen can be copied: a drag selects them and copies them at once, as Shift+drag did, Ctrl+C or Cmd+C copies a selection without interrupting, and a right click opens the browser's menu with Copy; before, Claude Code's full screen took the mouse, so a drag selected nothing and Ctrl+C interrupted (B845).
- Changed: on the run page, a Plan queue row of a task no slot runs but which is under way no longer says only 'Being worked on'; it says 'Taken by the chat <its name>' (pressing the words opens that chat), 'Taken by a chat that has ended', 'Taken by hand' (taken from a terminal or unknown), 'Merging' or 'Waits to resume'; `take` now records the control session that ran it, in the git folder of its take worktree (B846).
- Fixed: a run whose `web_port` is taken without Runner Home serves its page on every interface on the next free port (every second one, 8772, 8774, …, skipping Tailscale Serve's and recorded rules' ports), its run log saying which port it is on, instead of 127.0.0.1 only; the page-only process and a run that takes that page over keep the port (`web.fell`) (B844).
- Fixed: on the run page, a long question's card keeps its scroll place when the chat's chips change (it went back to the top), and the question marked by Chat about this stays small with the phone keyboard up; a Needs you row of All projects cuts a long question at 3 lines (B840a).
- Fixed: tests/test_no_claude.py no longer fails under load: its commit that moves main in the main checkout is tried again while the run's own `git status` there holds the index lock, where it failed at once and left a.txt edited, which held the merge (T33).
- Changed: the run app's Talk code, agent_runner/page/170-talk.js, is split by area into 170-talk.js and 171-talk-clips/kept/mic/send/speak/words.js, with no change in behaviour (C54).
- Fixed: the test of a task that goes on with the next provider at a usage cap (its fallback chain, in tests/test_runner.py) no longer fails when it runs across 15:00 local time: its fake cap said "resets 3pm", so the cap had already reset by the check; it now names a fixed far-off epoch (B837).
- Changed: a Yes with words on a Needs you CONFIRM that closes its task now also starts a new control session with the words, which lists at the top of Chats and keeps no sent response; a chat that cannot start keeps the sent response and the toast and run log say so (F452).
- Fixed: the question card, and the item filed under Needs you, carry a chat's DECIDE question whole (up to 2000 characters); it was cut at 240 characters with the options and links counted, so a long link left about 100. A spaced em dash (now an en dash) or `BLOCKED:` in it no longer ends it in its item. A question filed before the upgrade with the cut words is still the same question: not filed again, its answer and its explaining text still found (B840).
- Added: Settings, server side, for the Project file group (commands, files, patterns, rules): every key there now saves or is refused with the reason and nothing changed, for a value that would stop the run or lose the plan: a command the shell cannot read or whose program is not on this machine, a wrong placeholder, a bad regular expression or one matching an empty line, an empty or outside-the-project path, a missing rules or prompt file, a push remote that does not exist, a provider a role still names. `[plan] dir`, `[plan] repo` and `[run] home` (a reset too) save only while no run is up (the page-only process) and no task is in a worktree, one at a time, and the new place must already hold the same plan; `[run] notes` cannot be changed on the page, which works in that folder. A table written as sections (`[run.tools.x]`, `[run.join]`) is now edited in place, its other lines kept, not refused. Each settings row has `warn` (what a risky change does) and `locked` (why it cannot change there now), shown on the page with F448b. Checks apply to saves only; hand-written values load as before. Code: agent_runner/setting_checks.py, agent_runner/toml_sections.py (F448a).
- Changed: on the run page, renaming a chat can be cancelled without a keyboard: the rename row has a Cancel button (✕) beside the field, and opening another chat (a press on its row, the switcher, a new chat) cancels it too, with that same press opening the chat; the old name stays and nothing is sent. Enter still saves, Esc still cancels. Why: on a phone one could get stuck in the rename box, also over a reload (F446).
- Fixed: a working branch (`[git] master_branch`) saved for everyone in Settings on one machine and pulled on another, whose main checkout still has the old branch out, no longer stops the run and commands there: they go on with the old branch, and the next start of the run switches as on the saving machine, a branch that machine does not have yet being made from the remote's; a value changed by hand still has to be checked out by hand (B833).
- Fixed: on the run page's Talk, leaving Talk for another view, chat or project stops the reply being read aloud (run speech or the browser's own voice, also one started with a play button); the rest of it, replies waiting to be read, and a reply that lands while Talk is left are not read, then or on coming back, and each keeps its play button. Before, the reading went on. A sheet or the drawer over Talk, or the page hidden, is not leaving Talk, and a person back before any of the reply lands hears it (B836).
- Fixed: on the run page's Status view, Merging no longer lists a false `ahead` row while a merge is built ahead: the helper thread B827 named `merge:ahead` was taken for a task, so Read task on that row failed (B834).
- Changed: Talk's mic report names the open page (the fingerprint of the page as loaded, 12 hex digits) beside the run's version, and says whether it is the same as the page the run serves now, or not (with that one's fingerprint: not reloaded since it changed), so a report from a page not reloaded since a fix is told apart (B216b1).
- Changed: a task's brief now tells its session to read only the ranges it needs (`grep -n` or the file's outline first, no whole big file, no range read again that it already has and that has not changed), and to hand a broad search over several files to a read-only `Explore` subagent that returns file:line and a short conclusion; the subagent part is left out in harness loop sessions and lean sessions without the Agent tool. Nothing a task needs is cut from its reading. Landed 2026-11-25, after F412 (2026-11-24, limits on the outlines), so R20, which measures the savings, can tell the two apart (F451).
- Added: saving the working branch (`[git] master_branch`) in Settings is checked on the server: a missing or invalid branch, one of the runner's own (task/, wip/, pr/, leftover/), one checked out in another worktree, one without the settings file or task list, or (in PR mode) one GitHub does not protect is refused with the reason and nothing changes. A save moves nothing: the run and every command go on with the branch there was, and the save says so; the next start of the run checks the new one out in the main checkout (a setting in runner.toml is first committed to that branch too), unless there are uncommitted edits, or tasks run, wait to merge or have a pull request: then it starts on the old branch, the run log says why, and the next start tries again. The settings snapshot's row has `picks` (found by itself with the branch now, the local branches), `now`, and `next` and `held` while a switch waits. Messages say working branch. A value changed by hand in a file still has to be checked out by hand (F447b).
- Added: an ask file's `shots` may now be .mp4 and .webm videos (same folders, uploads and asks, same 50 MB limit, content checked against the suffix); the run page's Needs you sheet plays each in place under Video or Videos above Pictures, `GET /shot/…` answers Range requests for Safari, and the terminal UI lists them under Videos. A picture named in a task's line and a control session's copied pictures stay pictures only (F445a).
- Fixed: on the run page on a phone, a tall question card no longer leaves the session shown whole for good, with no chips and no history: the card never makes the session's frame lower than 12 rows, so Claude Code's prompt is drawn and found again (B828).
- Added: the run page's printed addresses (run log, `agent-runner status`) end with a localhost link for this machine's own browser, whenever the page listens on every interface, so Talk's mic works without https; through Runner Home it is Home's localhost link, the launcher's `w` and the page-only process open it, and `c` still copies the ordinary link (B815b).
- Added: PR mode was tried end to end on scratch GitHub repos (docs/research/pr-mode-check.md): merge, change request, red CI, conflict, closed pull request; it stays off by default and is turned on in no repo for now, by the person's choice (T26).
- Changed: on the run page's Talk with Speech to words: Recorded, a mic press after a reply, or one that cuts the reply off, no longer waits for the Open mic to reopen: while a reply plays its stream stays up with no sound taken, and on an iPhone 15 a press hears its first sound in about 50 ms (about 80 ms when it cuts a reply off), where it took 0.46 s (1.14 s when cutting one off). Measured on a test page only: reply volume and earbuds are not yet checked by a person (F161c3).
- Fixed: the two places still taking the push remote's plan commits in now check for task id clashes, as the B822a merges do: a pull of a `[plan] repo` clone, and a plan edit's push (`plan add` etc. in the main checkout) when the remote has moved. An unpushed task under an id the remote uses for another task gets the next free id, and after: and the words that name it, and its long form, follow; the pushed one keeps its id, and a task with a `task/` or `wip/` branch keeps its id too and the log says so. The renumbering is printed on stderr and written to `run.log`; a conflict undoes it, and when ids were renumbered the plan edit's push merges the remote in instead of rebasing. A task added on both sides and noted only on our side is no longer kept twice (before, only the other direction, noted on the remote's side, worked) (B829).
- Fixed: on the run page's Plan queue, the row grip of a row with no row menu (a running or under-way task's) stood outside the card, 16px left of its edge, because `.card>.grip` had no grid column of its own and was placed from the card's padding box; it now has one and sits inside the card, where it is on a row with a menu, shut and open (B830).
- Added: on the run page's Plan queue, a task's three-dot menu has Wait for…: press it and tick the rows it waits for (its present waits start ticked; several allowed, running tasks too, and Parked rows and search hits), then Done or Cancel in a bar (Esc cancels). Rows it cannot wait for are dimmed and say why; unticking all clears its waits; the row shows the new wait at once, and a refusal shows its reason with Retry. Not on releases, parked or started rows, nor rows that wait on the person or a check. No drag meanwhile (F442).
- Added: `[models] provider` moves every model written as a bare name to one provider (claude, copilot, codex, gemini, ollama or your own), with opus, sonnet and haiku mapped to that provider's models through `[models.tiers.<provider>]` (built-in for copilot, codex and gemini); a model written as `provider:model` keeps its own. In the run app it is Provider, the first row of Models in Settings (F443).
- Fixed: in PR mode, after the feedback round on a closed pull request the run log names that pull request's number (it said #0); a new pull request has the time it was opened in Needs you (it kept its record's old time, so it looked minutes old at once); and during a GitHub outage a run log line that differs only in GitHub's request id (or a time of day) is written once instead of every minute (B823).
- Fixed: on the run page's Status view, an opened Merging row whose merge the run log has not yet mentioned no longer reads "Its merge is built and tested, or waits its turn."; it says "Testing the merge" while a gate runs on its merge, "Waiting to merge" while another task's merge is in its gate or being fixed, and "Not merged yet" when the run cannot tell (B831).
- Fixed: Devices and a device's page follow the app's style: the title and verdict are said once, meters line up, details and sparkline sit under their meter, and Clean is beside More (B818c).
- Fixed: a merge that takes the push remote's commits in (the merge before the gate, the PR mode merge, and the merge a refused push of a task branch makes) now checks for task id clashes first: a task this side added (on the task branch or in an unpushed plan commit on the local main) under an id the push remote uses for another task gets the next free id, and lines that name it (after: too) and its long form follow; the pushed one keeps its id, and `run.log` says so. The same task on both sides is left as one. A clashing task that already has a `task/` or `wip/` branch keeps its id and the log says two tasks have it. Before, both stayed under one id with nothing in the log (B815 twice) (B822a).
- Changed: on the run page's Talk with Speech to words: Recorded, the Open mic is not listened to until the mic is pressed: with no listen on, every piece of sound is dropped at once, and a clip has no sound from before its press (the second of pre-roll is gone; a mic held again while the last words are made still keeps the sound of that hold). The talk line at rest and the mic's label say `the mic is open, not listening` (F161c2).
- Fixed: on the run page's Plan queue, a task a slot works on now says "s2 is on it · 4 min", and one under way another way (merging, taken by hand, or waiting to resume) says "Being worked on", where both said "Ready to start when a slot is free"; a blocked row keeps "Waits for you", and with no run up a task that waits to resume still says it waits for the run to start (B824a).
- Fixed: the plan had two tasks under id B815; the phone question card task ("a tall question card can leave the session whole") is now B828, and B815 stays the run page links task (parts B815a, B815b) (B822b).
- Changed: a stop now (`s!`, `stop --force`, `X` pressed twice in `agent-runner ui`, Stop now on the run page) ends the whole run at once: sessions, merges and their gates and fix sessions are ended, the run exits within a few seconds and waits for none of them (only briefly for a git command moving the main checkout and for recording what landed), `[run] on_exit` runs detached and the next run holds its slot until it ends (past `[run] command_timeout`, not 60 s), and `stop --force` ends a run that has not begun the stop in 5 s (B827).
- Fixed: in PR mode, a note on a blocked task whose pull request was closed, whose session blocked it in a feedback round, or whose 3 tries ran out now reaches its session however it was opened again (plan unblock, confirm or change); before, only the answers of plan confirm and change did, a plan unblock note was lost (the session was told no answer was noted, and for a closed pull request an identical one was opened). With no person's answer in it, it is told as a note, not as what the person said; an answer to an earlier question is not told again (B820).
- Added: `plan edit ID --wait-for X,Y` sets what a queued task waits for to exactly those tasks, and `--wait-for none` clears it (a blocked task reopens with its notes kept; a person's check that waited goes back to Needs you); the run app's `set_waits` does the same. Refused with the reason and nothing changed for an unknown or done task, a circle, a started task, a release, a shelved one and similar. In the Plan queue (run page and terminal UI) a task blocked on open tasks now reads what it waits for, where it read "Waits for you" or blocked (F441).
- Changed: every Plan queue row has a row grip (and so the touch lift) except a release that has started (runs, merges, is taken or waits to resume), a parked, removed or search row; the server says so in each row's `grip` (`ui_model_queue.grip_on`), and `plan move ID before|after OTHER` now moves a running, taken, claimed, resuming or merge-waiting task (`top`, `bottom`, `in` and a place under Parked still refuse it) (B824b).
- Fixed: with a `[plan] repo` set (an external plan), `agent-runner plan` with no arguments printed the index and then failed with an IndexError and a non-zero exit; it now exits 0 (B821).
- Fixed: in PR mode, the message a feedback round gives the task's session now tells it to rewrite the file its pull request's text is made from (what, why, how to try it, risk) when the feedback changes any of those; before, the pull request's body could keep the old text after the change. The body was already rebuilt from that file on each push; only the instruction was missing (B826).

## 0.73.0 (2026-11-25)

- Fixed: on the run page's Plan queue, a shut waiting release row says "Waits for everything above" or "Waits for 3 tasks" (or "next") instead of naming its tasks; opened, it still lists them (B825).
- Added: a short AGENTS.md (under 3 KB: where things are, how to run one suite, style rules, the docs) that `[run] rules` in this repo's runner.toml points at, so slots read it instead of the README; a test checks its size and that every path in it exists (D8).
- Fixed: on the run page, the messages shown while a chat's terminal loads are laid out at the terminal's own text size, font, columns and row height, so nothing rewraps or changes size when the terminal draws (they were 14px in a narrower column before), and a list right under a paragraph has no blank line before it, there and in the session history, as Claude Code 2.1.332 draws it (B819).
- Fixed: a run restarts on changed agent_runner code as soon as main's tree differs from the one it started on, not after main has held still for 10 min (at most 1 h); while the restart is due no new merge starts, those under way finish and the restarted run takes the held ones up (B227).
- Added: a real `high` task level: `plan add --pri high` and `plan edit ID --pri high` tag a follow-up `(follow-up, high)` and file it at the top of the leading section, behind critical and earlier high ones. A run tries ready high tasks after the critical ones and ahead of the rest, wherever their lines stand, and one that cannot start yet holds nothing back; only critical gets the merge order, the alone turn and an interim release. The terminal UI shows a ready high task as `high` (yellow) and the run page says so in words, the Priority control (p in the terminal UI) steps normal, critical, high, normal (low steps to critical) instead of toggling critical, and a moved release loses a high tag as it does a critical one. Guide and brief now tell agents "high priority" means `--pri high` (F438).
- Changed: a brief's `[plan] outline` map runs only for files on the task line over 300 lines, and all the outlines in one brief stay within 2 KB (2048 bytes); a file that doesn't fit gets an even share, its lines picked evenly through the file and labelled `outline (trimmed evenly: N of M lines)`, with a note giving the command for a whole one. Before, every file on the line got its outline, up to 6000 characters each (F412).
- Changed: on the run page, a question card hides while you are scrolled up and is back at the bottom (F437c).
- Added: in PR mode, `[git] pr_max` (default 5; 0: no limit; Settings > Merging > Open pull requests) starts no new task while that many pull requests are open on GitHub; each open one shows its link and state (CI red, changes asked, conflicts with the main branch, approved, waits to be merged, waits for review) in `agent-runner status`, the run page's Status, the terminal UI and Needs you (F420).
- Changed: on the run page, while a question card is open (whole, or its Undo row), the key row is not shown, neither the keyboard button's nor the one in place of the chips on touch; it comes back once the card is answered, gone, minimized or marked (Chat about this), and the keyboard button still opens it under the card for that question only (F437b).
- Changed: tapping a device under Devices (Runner Home and a project's All projects level) opens its Device Vitals inside the run app, with a top bar that has the menu and Back to Devices, the theme, and the sidebar swipe. Browser Back and a reload keep the place; it refreshes every 30 s; a device that does not answer says Not answering, why, and has Retry (B818a).
- Fixed: a Tailnet address (https on Tailscale) is offered only while `tailscale status --json` says BackendState Running, everywhere a run's or Home's links are shown; otherwise the plain http links, with no error, and the saved Serve rule is left alone. `home install` offers no `tailscale serve` command while Tailscale is not connected (B815a).
- Changed: the device page in the run app acts: Headroom has + slot for each run up on that device, and Runner footprint has Clean, a tick list (the safe ones ticked, the rest not) with Remove ticked and Cancel; a refresh changes neither the list nor the ticks, both stay when Home is out of reach, and the answer shows in the section. A device alert's Clean opens the device in the app. The old separate device page is deleted: /device?id=ID (token kept) redirects to Home's app with that device open, also on a peer's Home (B818b).
- Fixed: `plan add` refuses (exit 3, nothing written, the task named, even with `--force`) an add whose text and fields equal an open or blocked task's, so the same task is not filed twice. Whitespace, id and kind letter, level, the `(alone)` tag, order within comma-list fields, notes and BLOCKED do not count; split parts are not exempt; the check runs under the plan lock and also reads the other git worktrees' TODO.md, so another slot's unmerged follow-up counts. Done tasks are no obstacle, and releases (kind V) are exempt. Before, `--force` skipped the only check: a control session ran the same add with it twice, four minutes apart (B817).
- Changed: Talk with Speech to words: Recorded: the press that opens Talk (nav row, Home's Talk button) starts the mic inside that press, whatever the Permissions API says, so the browser may ask there and the first mic press finds the stream open (no getUserMedia, no context start). A refusal there is not asked again by itself nor by the next Talk press; a later mic press still asks. A press while a reply is read or dictation has the mic opens nothing. A reload keeps its rule (only where `granted`); released when Talk is left or hidden, as before. Before, without `granted`, the first mic press opened it (F161c1).

## 0.72.0 (2026-11-25)

- Fixed: a split task's row in the run page's Plan queue and the terminal UI's queue reads "Split: 2 of 4 parts landed" instead of Ready or what it waits for (blocked, held, parked and running rows keep their words; a dropped part is not counted); Drop on it, also when parked, first asks, naming the parts that stay open (the page with titles, the terminal UI by id); before, the question did not mention the parts. Status's reason why a slot is idle counts such tasks as waiting for their parts (B811b).
- Added: `agent-runner setup` asks once at a terminal whether the run audits by itself (default no); Settings on the run page has a switch for Audit by itself (`[run] auto_audit`), Every 25/50/100 tasks while it is on, and the Audit model beside it (F422).
- Fixed: a `plan edit` that changes only `--files`, only `--pri` or both no longer tells control sessions the item was changed (before, only a lone `--pri` was silent), and the same event again (same task, what, author and reason) is one Settled line per session: not told again within 120 s of the one told, and it replaces one still waiting to be typed; a different author, verb or reason, an edit whose text differs, or the same event after another event of that item came between is still told (B812).
- Fixed: on the run page on touch, holding a finger on the scrim beside the drawer (or other places with no words) no longer selects the whole page; on touch nothing is selectable but the words people read and copy (messages, history, task text, questions, code, fields), buttons never are, links keep their own menu; a button held and released now counts as a press instead of selecting its label. Mouse-only machines are unchanged (B814).
- Fixed: a split task (its line says "(split into …)") still at level later stands in the queue on the run page's Plan view and in the terminal UI, not in Parked, while one of its open parts is neither parked nor shelved; with every open part parked or shelved it stays in Parked. `guide queue` now says to file a big ask's title `--pri later` only until its parts are filed, with `plan edit ID --pri normal` as the last step (B811a).
- Changed: on the run page, a question card's ✕ (Dismiss question, F192b) is now a Minimize question button at its top right: a tap makes the card one line, the question cut short with a Show question ^ that opens it again, kept per browser and project over a reload, per chat and question. It sends and answers nothing, so the question stays under Needs you, and a question dismissed before stays hidden (F437a).
- Changed: on the run page, a control session's question under Needs you shows what explains it (B809c): the popup has the explanation under the question, formatted (headings, lists, tables, code, bold), links tappable, one over 600 characters folded behind "The rest of the explanation", its pictures under Pictures; the card has its first sentence; the subtitle of both is the session's name and project, not "Control session N asked the person"; Full task is left out of that popup; an item without the text shows as before.
- Fixed: a control session's DECIDE question that the run files under Needs you keeps, in its ask file, the text of the message above the DECIDE line (the message before it when it is a bare DECIDE), the session's name and project, and copies of the local pictures that text names when they are in the project or that session's scratchpad; questions already waiting get it once from the session's transcript, if still there. The pictures show as the item's pictures (B809b).
- Changed: a release auto release queues on idle waits only for the tasks ahead of it when it was queued and their parts; a task later put above it no longer holds it, its work lands in the next release. Before, `after: all` was worked out live, so it could wait longer each time work was queued above it. Releases by count already start at once (F195a, shipped), and a release a person queues (`plan add V`) or moves still waits live for everything above its place (F435).
- Changed: the control brief (`agent_runner/guide.py`) and the task brief (`agent_runner/brief.py`) tell agents to write a DECIDE that reads alone days later without the chat: it names the project, the thing and the problem in plain words, never "this", "it", "like this" or "What should I do?"; each answer says what happens and is clear without the chat, never a bare task id; two choices crossed in one bracket are two DECIDEs; one about a page gives its link after the bracket (B809a).
- Fixed: on the run page on touch, opening the sidebar drawer (a swipe that opens it, or the menu button) while a text box has the focus now hides the keyboard; the draft stays (B813).
- Added: an audit changes by itself only its findings file and dead references in docs, the glossary and lessons; anything else it finds goes on one pick sheet of at most 10 questions, and `done` and the merge refuse a diff past that fix limit (F418).
- Added: `[run] auto_audit = { every = 50 }` queues an audit task by itself once 50 tasks have landed since the last audit and the run is idle; an audit is a research task that looks at what changed since for what is stale, dead or wasted, and writes its findings to `plan/audits/<ID>.md` (or `docs/audits/`), with a token cap (`[run] audit_tokens`, 1,000,000) and its own model (`[models] audit`); `plan add R "(audit) …"` queues one by hand (F417).
- Added: in PR mode, a review comment or change request by someone with write access, or red CI or a conflict with main, resumes the task's session on its pull request, with at most 3 tries each before Needs you; a pull request closed without a merge goes to Needs you instead of only being logged (F423).
- Added: PR mode (`[git] pr = true`) for a repository on GitHub: each finished task opens one pull request for a person to merge, and the runner never merges or pushes main (F419).
- Added: `done` runs a removal check before its gate (F416): when a task's diff deletes or renames a file, test, setting or command, it lists what still names it, and a dead path in code, config or CI refuses `done` until it is gone; the rest is answered once with `done --named "1 filed B12; 2-3 kept because …"`.

## 0.71.0 (2026-11-25)

- Changed: in the terminal UI (`agent-runner ui`) with no run up, the Status panel says Not running and names T (start), with no slot, pause or stop keys; T starts the run without blocking the UI, and the panel says Starting the run… while it starts, or Not started: why after a failure (T again retries). When the run comes up, the panel, tab and each selection stay as they were. Adding a task and messaging a chat work with no run up (F402c2).
- Changed: with no run up, a queued task that nothing else keeps says `Waits for the run to start` on its Plan row (`goes first` when critical), the run page's add toast and the TUI's add line say it waits, and Home, + Task, + Chat, message boxes and Plan queue actions keep working while slot controls stay hidden (F402c1).
- Added: Home clears old build output by itself in a project whose run is off: a runner worktree no process works in and nothing wrote build output to for 3 days loses its recognised build output (git-ignored folders marked CACHEDIR.TAG or CMakeCache.txt, Cargo profile folders), never a repository, notes file or uncommitted file; no setting, and the Clean button stays (F424).
- Added: on the run page, a question card has a ✕ (Dismiss question) at its top right that hides the card, kept per browser and project over a reload; it sends and answers nothing, so the question stays under Needs you (F192b).
- Changed: with no run up, the run page's Home opens with a Start card (Not running, Start the run; Starting the run… while it starts; Not started: why, with Retry or Discard, after a failure), and Talk is a plain button; the run-off banner no longer shows on Home or Status unless a chat is open, and Runner Home's off page is only the fallback when the page-only process cannot start (F402c).
- Fixed: on an open run page that Runner Home answers with nothing serving the project (its page-only process ended idle while the page slept, and the redials got 502), the lost-connection bar says The run page is closed with a Reload button after about 8 s, instead of waiting on redials. Reload is a page load with Home's key, so it starts the page-only process again (off page in between, then the run page) and keeps what is typed, as Refresh does; the off page no longer takes the typed words. Nothing starts by itself, so `page-only stop` is not undone by an open page, and the bar goes once the page answers again (F432).
- Fixed: on the run page, in a chat on the harness loop, Chat about this words that are queued no longer hide the question card; only a queued message that is not about the question does (so a held option is still sent). The chat's `.now` file says it in `answers`; a chat whose process started before the update has no `answers`, and any queued words there still count as the answer until it is restarted (F433).
- Changed: a run's stop keeps its run page up (the page-only process takes it over, as before, and `agent-runner page-only stop` ends it; none after a suspend or shutdown stop or with `[run] web = false`). While no run is up the run page says The run is not running, with Start the run on every view but Status; an open page reconnects by itself after an error answer, its chats and drafts kept; a page-only process left idle ends only where Runner Home can start it again (F402b3b).
- Fixed: on the run page on touch, a long press on a chat's or slot's session no longer opens the sheet "The session's text"; at the live end it selects the word under the finger (the browser's selection), held while the history keeps the place, and where no history can be drawn it does nothing (B792).

## 0.70.0 (2026-11-25)

- Changed: on the run page, a question card's question that the person chats about (Chat about this) stays asked by the run itself (/live's ask): `chat_question.ask` reads past the messages that begin `About your question “…” (not my answer): ` (queued ones too) and Claude's replies to them, so the card survives a reload and shows on other devices, and goes when the question is answered in other words in the terminal or on another device, or another question is asked. Before, the page kept the card in memory only. In a chat on the harness loop, words queued in it still hide the card until they go in (F430).
- Changed: one helper, `agoWords()`, says how long ago everywhere, so a tool's check reads "checked now" and hours run to 48 h, not 24 h. With nothing that needs you, Home and Runner Home's all-projects view show the one line "Nothing needs you." (no card or icon), and Runner Home's Devices with none says "No devices." (F426f).
- Fixed: `plan restore` of a dropped blocked task puts it back blocked, with its BLOCKED text, its ask file and secrets (kept by `plan drop` on this machine only: secrets 1 day, the rest 30 days), and the tasks the drop freed wait on it again as they were, except one changed since it reopened or one something works on; on another machine or after 30 days it comes back blocked without the ask file and the freed tasks. The Plan queue's row menu has Remove on a blocked row too (B808).
- Added: on the run page's Plan, hold a queue row (a task, a release, the Next release row) still for 350 ms on touch and it lifts; drag it to move it, as the grip does, with the same look and edge scroll. A move, a scroll or a second finger first means no lift, and a lift opens nothing (F429d).
- Fixed: six writers used one temp file name (NAME.tmp) for the files they write whole (the voice file, the run page's chat order, the since mark, runner.local.toml, Home's registry home.json, and a shared file committed through plansync.commit_file, settings for everyone), so two at the same moment could fail with FileNotFoundError or move the other's half-written text into place. Each write now has a temp file of its own in the same directory, removed on failure (agent_runner/whole_write.py); changes to the voice file and Home's registry by commands and the Home server now run one at a time under a file lock (voice.lock, home.lock in the config folder), so none is lost, and when the lock cannot be had within 10 s the change is made without it (B807).
- Added: on the run page's Tools page, each tool's and device's card shows its tool buttons: a button is busy while its command runs (the tool's others wait, another tool's do not); its question is asked in place, and "Use it anyway" names the holder when someone has the tool; the result or failure, with its last output lines, is at the foot of the card; the device Add/Edit sheet adds, edits and removes a device's buttons (F428d).
- Added: a conflict in the glossary file (`[plan] glossary`, GLOSSARY.md) is joined by term entry with no setting: terms added on either side are both kept, and an entry changed on one side takes that side; one changed differently on both sides, or a side that does not parse, goes to a fix session and the run log says why (T31).
- Changed: on the run page's Status view, four sections: Run (the Run card with its state, notices and controls; the slots change there), Working (a row per slot, idle ones too), Merging (the tasks that merge now, also after their slot went on) and Usage. Landed lately, releases, the run log with its Since chips and the + Slot button are gone from it (History and Plan have them). Every agent row opens in place, one open row per list: a Working row has its last words, Open session, Read task, Cancel (asked in the row), Drop and Chat last; a Merging row its step, Open session, Read task and Chat; an idle slot says why nothing starts and has Remove a slot. Home's "N working, M merging" counts the same merging tasks, and the walkthrough's landing step points at History (F426e).
- Changed: `done --blocked` now refuses, before its gate runs and with nothing blocked, (1) a CONFIRM or BLOCKED line over 200 characters with no ask file (it used to only note it; a DECIDE is still only noted) and (2) a CONFIRM or BLOCKED line that says it waits for an open task or release (e.g. "release V5 …, then this reruns") with no `--after`; each refusal says how to write it. A BLOCKED with `--after` or `--until` is not refused. The task brief now says the line starts with what the person does, the reason second, and no task id without its title, and that a wait on a task is `--after` and a wait a check can read is `--until`, never BLOCKED (B795).
- Changed: a chat's question filed under Needs you and its question card on the run page are one: choosing an option on the item settles it, an answer given there closes the card, and a question that still waits is not filed a second time when its chat is resumed and left (F192a3).

## 0.69.0 (2026-11-25)

- Fixed: `s!` (`stop --force`) now runs `[run] on_exit` for each session it ends, in its slot; before, it ended them without it, so e.g. a device lock it frees stayed held until the resumed session ended. The sessions still resume in the next run. The run waits for every on_exit still running, also one from a session that ended just before `s!`, at most 60 s from `s!` (or `[run] command_timeout` if that comes sooner); one still running is stopped and the log says so (B803).
- Fixed: a task filed on main after the merge it would start on (F198) used to start on that merge even though the merge's plan has no line for it, so its plan brief was empty and `done` and `done --blocked` refused with "no task" after the gate passed. Now a task starts only on a merge whose plan has its line (a merge built ahead that has it will do); otherwise it waits for the merge and starts on main, as before F198. A plan outside the repo is one copy, so nothing changes there (B805).
- Changed: on the run page's Talk with Speech to words: Recorded, when the browser ends the Open mic's stream (track ended) while Talk's mic shows, between listens and with no reply being read, the page opens it again by itself, where the Permissions API says granted; at most 3 times (REC_ENDS) until a press listens, Talk shows anew or Speech to words is picked again, then it waits for Talk to show anew or a press. Before, it waited after the first end. An end during a listen (its words go out) or while a reply is read, and an opening by itself that fails, are not tried again by itself until Talk shows anew; a press still tries. Not proven to be the cause of a hold that found no Open mic at the press (B804c).
- Added: on the run page's Plan, three dots beside each queue row (a task, a release, the Next release row) open its icons in place: hold (or play, while held), to the top, and remove, which shows a Removed card with Undo for 20 seconds (F429b).
- Added: on the run page's Tools page, a shared tool in runner.toml with a `page` shows its web page's address and state (running, stopped or failed) with Start, Use and Stop on its card, as a device's card does (no start command: Use alone; `:PORT` links to the host the run page was opened on); a Needs you item whose task's `needs:` names it has Use LABEL, or Open LABEL in Tools while it is not running (F428b).
- Fixed: writing `control-settings.json` in the Notes dir could fail when two processes (a control session starting, or the control server) wrote it at the same moment: both used one temp file name, so the second move could find it gone and a control start could fail with FileNotFoundError. Each writer now has a temp file of its own, removed when the move fails (B806).
- Changed: Cancel replaces Take back on the run page's slot rows and in `agent-runner ui` (key C, asked first with the minutes worked; H there no longer does anything): `plan cancel ID --yes` stops a running task's agent, keeps its work on wip/ID and parks the task, so no run starts it until it is unparked (F426d).
- Added: a shared tool in runner.toml and a device may have tool buttons of their own (`[[run.tools.<name>.buttons]]`, and `buttons` saved with the device): each a label and a command that runs once and ends, with an optional question asked first; POST /tools `op: press` runs one, one at a time per tool, and GET /tools lists them (F428c).
- Added: on the run page's Plan, a thin grip on each queue row; drag it with a mouse, or focus it and press arrow up/down, to move the task, release or Next release row; a running row has none (F429c).

## 0.68.0 (2026-11-25)

- Added: a shared tool in runner.toml may have a `page` (an http/https address, or `:PORT` of this machine) and a `start` command, served and started as a device's web page is, by `run device start|stop|show NAME` and POST/GET /tools (F428a).
- Changed: a task's id is a kind chip with its kind's word in the kind's colour (bug red, feature blue, release purple and filled, concept teal, tests green, research gold, docs indigo, cleanup gray; a project's own kinds gray) on the run page's Plan, slot rows, Needs you, Landed lately, History and Concepts, and in the terminal UI's queue rows; `agent-runner status` prints `bug B216 Title` in its slot, merging and lately lines, while `since` is unchanged. An icon-only control shows its name as a hint while hovered or held (F195b).
- Fixed: on the run page's Talk with Speech to words: Recorded, when the stream gives no sound and is opened afresh within a listen, the talk line says "Starting the mic…" until sound comes again, where it went on saying "Listening…" (the first opening already said Starting). A Hold let go before the mic opened or took sound, or within 0.5 s of the first sound where the press found the mic not open, and which brought no words, now says "The mic was still starting. Allow it if the browser asks, hold until this line says Listening…, then speak" (then the usual details in brackets) instead of "Heard nothing" or "The mic was stopped before it was on". A short hold whose words came is still sent; a hold that listened from the press still says Heard nothing (B804b).
- Fixed: `[run] on_exit` now also runs when a running task is stopped by `plan drop`, `plan change --restart` or a take back (and when a queued resume is taken back, dropped or changed); it was skipped, so e.g. a device lock it frees stayed held. And after every session end, nothing starts or resumes in the slot until on_exit has ended (at most `[run] command_timeout`, then stopped with what it started and logged); before, the slot's next task could start while it ran. A stop (not `s!`), an upgrade restart and idle wait for it. On a halt the run waits up to 5 s for it before it throws the work away; a slower one then holds the slot and a changed task starts when a slot is free (B801).
- Added: `plan hold ID` keeps a queued task, or a release, at its place in the queue and no run starts it until `plan unhold ID` ends the hold; the queue row, run page and terminal UI show it as held, outside Needs you, and an `after: all` release does not wait for a held task (F429).
- Added: `plan move` of a release task makes it wait for the tasks above its new place (`after: all`, any critical tag removed), and that cut only: the auto release setting and the next cuts are unchanged; when it is the next cut it is marked `moved: yes`, so the automatic count neither cuts it early nor queues another beside it until it lands. `plan drop` of a release auto release queued skips that cut and only tasks landed after the removal count (`plan restore` undoes it); `plan hold|unhold|move|drop|restore next-release` act on the Next release row, and a task or release that is running, taken or merging cannot be moved (F429a).
- Changed: on the run page's Talk with Speech to words: Recorded, a press that finds no Open mic makes the Mic report say why: none yet, freed for a reply, resting, track ended by the browser, page hidden, or an opening under way; then the permission and the audio context's state, and the ms of getUserMedia and of the context's start. An empty answer from the run is logged as no words, not "words came" (B804a).
- Fixed: on the run page, coming to Talk from another view, chat or project, or back to its tab after a minute or more away, shows the mic again instead of the message box left up; unsent words stay the box's draft and come back with the keyboard button; a redraw or a reply landing never closes typing; under a minute away (an app switch, a refresh of the page) leaves it; the mic or the box is now kept per browser tab, not per browser; where the mic cannot be used the box stays (B802).
- Fixed: on Linux, a page-only process, or a run started by bare `agent-runner` (Home's Start run too), that is started inside a systemd service (Runner Home's) is now put in a systemd scope of its own, so stopping or restarting that service no longer ends it and the chats it started (before, systemd ended all the service's processes). Where `systemd-run --user --scope` does not work it is started as before. A device's start command already did this; all three share `plat.service_scope` (B800).
- Changed: on the run page's Plan view and in the terminal UI's queue panel there is no Releases group or heading: each open release is a row of the Queue at its place in the plan order, a task does not move past one, and the auto release's count is a dimmed card before the task it stands before, also while open releases only wait for open tasks; New release is its own card above the Queue. A tap on a row's words opens it in place, and its grip and menu controls stay beside that, not in it (F195c).
- Fixed: on the run page's Needs you, a Stuck item whose reason starts with numbered steps ("1) do this. 2) do that") showed "Stuck" alone as its first step and its summary; now the summary and first step are the first real step (B797).
- Changed: on the run page, a Talk Hold with the browser's recognition uses one continuous recognizer (rec.continuous) that stays through pauses until the release, instead of one restarted after each pause (on an iPhone the restarted one heard nothing); not yet proven on an iPhone. If it ends by itself while held it is started again as before: the talk line says "The mic is off, wait until it is on again" until the mic is on, and after 3 s with no speech begun "Nothing is heard. Let go and press again" (with ", these words are kept" when words came before). Text a recognizer repeats, drops or begins anew in one Hold is joined once. The mic report's try line says continuous or not continuous. Tap, auto listen and Recorded are unchanged; a hold the system took (touchcancel) stops after 5 s with no new words (B216a1).
- Fixed: in a project whose roles and kinds all name another provider, a cut-off session on a claude model (a task's own model), or one queued to go on with a claude model from `[models] fallback`, was resumed while the Claude API was unreachable and died at its first call. Now it alone waits until the API answers, and the run log says once that it cannot resume; sessions on other providers resume as before. Only with Claude Code as `[run] agent` (B799).
- Added: on the run page, a History view after Plan (the NAV row's History): a Find in history field, Landed (the newest landed tasks), Releases (past ones) and the Run log, with a landed or release row opening to What changed, Report a problem and Chat last (F426c).
- Fixed: a task on a claude model in a project whose roles and kinds all name another provider, on a machine with Claude Code, no longer starts past `[run] session_max` or `weekly_max`, or while the Claude API is unreachable; past a cap it alone waits (or starts on the first free `[models] fallback` provider), other tasks start as before, and when nothing else can start the alarm names the held task and says it cannot start until the reset. `force` lifts the cap (B791).
- Fixed: a BLOCKED Needs you item without steps in its ask file (or an old wizard script) is split by rule into a Why section above What to do, steps, "After that" notes and "V5 has landed"; only words after a step's colon that report no failure are still What you should see, and nothing is lost (B794).
- Added: Runner Home opens a project whose run is not up through the page-only process: a page load of `/p/KEY/` with Home's key starts it in the background; Home's off page shows as the wait and turns into the run page once it answers, and stays if it cannot start (why goes to Home's log; the next opening tries again). Home's list still says off; nothing starts without the key, or from a pick, fetch, frame or prefetch (F402b2).
- Fixed: on Windows only, when a harness loop bash tool call is stopped (Escape in a chat, a timeout, the end of the chat), its Git Bash children end too (before, `sleep 61; echo x`, `(sleep 61; echo x) & wait` and `sleep 61 | cat` left sleep.exe and cat.exe running, as taskkill /T does not reach a child whose parent is gone); the command now runs in a Windows job object (agent_runner/job_object.py, on the runner's Python). A call that ends by itself still leaves its background processes running, and where Windows makes no job it runs as before (B798).
- Added: a sent response (F425a) is a row in the Chats list's Quiet group, in the sidebar and the Chats switcher, sorted with the quiet chats newest first: its item id and title, with a dim "new" until it is opened once (per browser). It has no dot, no count, and is never in the top list by itself; it is shown also with `[ui] chat_quiet` off. Opening it shows the question, answer, note and a message box, and starts no session. Words sent there start a new control session (`response_chat`) and the row is replaced by that chat. A response already gone sends nothing and keeps the words; a chat that did not start and is discarded brings the row back. (F425b)
- Added: on the run page, a chat whose last answer ends on a DECIDE line with options gets a question card above the message box: the question and one button per option, the recommended first. A tap sends that option as the person's message after 5 s, with Undo; Chat about this marks the question above the box, and what is sent is an ordinary message about it, never its answer. The card comes back after the send (F192a, F192a1, F192a2).
- Added: `plan block ID --until CHECK` and `done --blocked WHY --until CHECK` make a block wait on until checks (several comma-separated, all must pass); a bad check is refused before anything is blocked. Such a task is not under Needs you and no slot takes it; it shows as what it waits for, `plan unblock` frees it, and an `after: all` release does not wait for it. The run does not run the checks yet: F427c does that (F427b).

## 0.67.0 (2026-11-24)

- Changed: on the run page, the Status view has no Needs you section; Home keeps it (C50).
- Fixed: on the run page, a session's history (a chat or slot) could keep the light look's near-black text on the dark ground after a light/dark flip, because the terminal's light and dark style sheets have the same length and only the length was compared; the sheets themselves are compared now. A flip while the history is scrolled up (or touched) now also draws its lines in the new colours, those copied from the screen included, with nothing moving (B787).
- Added: an until check (`version:X.Y.Z`, `login:PROVIDER`, `tool:NAME` or `check:NAME`, the last a `[run.checks.NAME]` command in runner.toml) is read by this machine alone, with no agent session, and answers passed, not yet or cannot run; the blocked tasks that wait on one come later (F427a).
- Changed: a slot on a task filed from a control session's `DECIDE:` question may run `plan add` in the other project that question names, when the person's answer is a yes (a word of yes, or one of the question's options that is not a no; a project only the options name counts only when the answer names it); its other plan writes and `done` there, other tasks' slots and unnamed projects stay refused, and a later "do this instead" withdraws it (B785).
- Changed: on the run page, Home is about the person: Talk is one full-width button above the message box, which has no dictation button; shortcut chips (Last chat, Add a task, Pause or Go on, Since my last look) come before Needs you, then one card of two rows opens Status and Plan. Agent cards, queue rows, the release card, What needs me and New concept are gone from Home, and the walkthrough's session step points at Status's slots (F426a).
- Added: a project whose models all name another provider needs no Claude Code: a missing `claude` holds nothing, no Claude login, usage, API check or headroom limit is read or shown, and `agent-runner setup` picks the other roles too and runs its session on the harness loop when no role needs Claude Code (F406h).
- Fixed: on the run page, a Talk Hold with words followed by a pause no longer sends the first half as the whole message when the mic's restart heard nothing or failed; those words are kept, the talk line shows them with Send as it is, and the next listen goes on from them (B216a1).
- Changed: a control session's first message (in Chat or Talk, or `control --new --ask`) no longer gets a `<runner-waiting>` block of Needs you items, only the person's ask and the lines for attached files; the control brief says a first message that is a bare reply or names an item ("yes", "R43: tags please") is settled after running `needs`, and any other is answered without mentioning waiting items. Older transcripts with a block still read clean where a Held message is shown (a chat's messages waiting out a usage limit). Before, the block filled the chat bubble, and in Talk nearly every ask carried every item.
- Changed: Talk's Speech to words: Recorded opens the mic's stream when Talk shows (also after a reload) where the browser's Permissions API already says `granted`; otherwise the first press opens it, and it stays open between listens. A press on the open stream listens inside the press, the clip starting with up to 1 s of sound from before it; older sound is dropped, and sound from before a press alone is not sent. It is released at once when the page is hidden, within 0.5 s when Talk is left, a chat or the Mic test opens, or typing mode shows, and opened again when Talk's mic shows. While a reply plays, a stream opened on `granted` is closed and opened again after; where a new stream could ask again, it only rests. If opening by itself fails, or the mic is taken away (a call), it is not tried by itself again until Talk shows anew; a press still tries. The open mic shows as a dot on the mic button (`.mic.open`) and `Tap to talk, the mic is open` on the talk line at rest. Before, the stream opened on the press (F161c).
- Added: Talk settings has Speech to words: Recorded, where the page records what you say and posts it as WAV to the run's `POST /recorded`, which sends back the words; the same Tap, Hold and auto listen, and the browser's recognition stays the default (F161b).
- Changed: a run's stop no longer closes its run page. Before the run says `run stopped`, it starts a detached page-only process that takes the page over (same address, port and key; web.url and the Tailscale Serve https rule kept, with or without Runner Home), and a run started right after takes it back. If the handover fails, the run still stops, the page closes and the run log says why. No page stays after a stop with suspend or shutdown, or with `[run] web = false`; Ctrl-C, a kill or a crash still takes the page with it. Before, a stop closed the page (F402b3a).
- Changed: on the run page, the message box's send arrow forces only when it reads Force send: with the box empty, the session working and a sent message still queued, a press sends what is queued at once (`chat_to` with `force` and no text, one Escape). With words or an attachment it is the plain Send and queues. After a send or a force the arrow is disabled for about 1 s while the session works and the box is empty, so a double tap never forces (F190c).
- Fixed: a Needs you item's data (`need_detail.detail`, used by the run page's card and popup and the terminal UI's pane) now has the task's whole title (its first sentence, no longer cut at 60 characters) and a summary that is the whole first thing asked (no longer shortened by `ask_short`: first sentence, with no asides in brackets or paths, up to 120 characters). A DECIDE with no question mark and no ask file's summary has its question as its whole first sentence, no longer repeated in the background. The terminal UI's Needs you row and `status` keep their one short line. The run page's card ellipsis is not changed by this (B793a does that), so the card does not yet show it all (B793b).
- Added: every successful answer to a Needs you item that opens no chat (a button, a DECIDE's typed words, a pick sheet's picks, Done with inputs, a pitch's no that settles it) is kept as a sent response in `<notes>/responses`: item, title, question, answer, note, time; a secret only by its name. The newest 30 are kept. The run page's snapshot lists them as `responses` (newest first), and the new action `response_chat` (response id and words) starts a new control session about one, and the response then goes; without words it starts nothing. Nothing on the run page shows them yet, F425b does that (F425a).
- Changed: on the run page, every Needs you item's card and popup is headed by what is asked (the detail's summary, or a DECIDE's question, as before), whole, with the task's title small under it, left out when it says the same; the card's and popup's heading, title and what-to-do text are no longer cut (no ellipsis, no line clamp). Before, only a DECIDE was headed by its ask, the title was cut to one line on the card, and the what-to-do text was cut to two lines (B793a).
- Changed: on the run page's Plan view, the Releases group is one card: the open releases, the auto release's count, then New release; the newest landed release is no longer in it. An open release opens to the tasks it waits for (each opening in place to its text and actions), or to its text when it waits for none; opened, its line says only the count and what it does not wait on; its actions are Drop (until it starts) and Chat, now inside the fold, and Do it here and Priority are no longer offered on it there. One row per list is open (each release's tasks, Releases, Queue, Parked, each group of search results). The search field stays at the top while the queue scrolls. Chat is the last button on queued, parked and shelved tasks (F426b).

## 0.66.0 (2026-11-24)

- Added: `POST /recorded` on the run turns a clip the page recorded (16 kHz mono WAV) into words with whisper.cpp, installed by `agent-runner speech install whisper`; nothing on the page uses it yet (F161a).
- Fixed: on the run page, a new chat's or slot's first message is no longer cut off behind the top bar while the agent works; a session that is not full now rests with its first line just under the top bar, idle or working (before, a short idle one stood on the message box), until its words no longer fit (B786).
- Changed: a task whose slot sessions end with no commits in two runs in a row, its plan text unchanged, is blocked `DECIDE:` under Needs you with what its last session said, instead of starting a full session again each pass. `<notes>/no-commits.json` counts across restarts; a task told, reopened or edited in between, or a run with commits, counts afresh, and a `take` does not count. Until the block is committed the dry run says the task ended twice with no commits and needs a person. Before, one task (R45 in iFizBox) was started 18 times (B774).
- Added: a control session on the harness loop (a chat on another provider's `[models] control`) works in the run app as a Claude Code one does: its frame shows its terminal, its chips are Working and the model, Stop and Force send send Escape, `/live/cN` reports its status, since, queued and `harness: true`, and its terminal is drawn again from the last 32,000 characters printed. The read tool shows an image to its model. An ended chat of the other kind has no Resume and is not restarted (F406g).
- Added: the launcher's `w` on a project whose run is not up opens its full run page and starts no run: a detached page-only process (one at most per project; Linux and Windows) serves it, with Runner Home or without. New chats, messages, Resume and plan actions work there; no slot, task, merge or push starts, run_up stays false and `status` says no run is up. A run that starts takes the page over (same key, same port; an open page reconnects by itself). It ends after 10 minutes with no page open; no chat ends with it (F402b1).
- Fixed: on the run page, the jump button (Jump to bottom) no longer stands on its own full-width strip above the message box, which cut the history off. It floats over the lines just above the box, with its own fill and border and no ground behind it, so text shows on both sides and can be pressed, selected and scrolled; it still glides to the live end (B788).

## 0.65.0 (2026-11-24)

- Fixed: `plan add` and `plan edit` refuse a text (or a place after `@`) with a stretch that is mostly paths that exist in the current folder, separated by spaces (at least 6 more of them than of its other words): it is a glob the shell expanded. They exit 2 and file nothing (`--force` does not override), and say to quote the glob, as in `--files 'dir/**'`. A text that names a few paths, or a comma-separated list of them, still files. Before, only paths given as separate arguments were refused, and one task's line had grown to 27 KB of paths (B773).
- Changed: a pick sheet is published by the runner (F411). `agent-runner sheet ID --publish` checks and renders it and publishes it to claude.ai with the `publish-page` one-shot, with the page's db capability so Send still writes the picks there, and prints the URL (kept in `<notes>/sheets/ID.url`, so a second publish updates the same page). A slot no longer needs the Artifact tool for it; its brief says to run this. With no Claude Code program or `[models] feed` on another provider, the sheet stays on the run page at `/concept/ID_sheet`.
- Changed: `[run] auto_release = { every = N }` cuts a release at N tasks landed since the last release: it starts at once with what has landed (critical, at the top, no `after:`, as `plan add V --now`), where before it waited for the whole queue and an open release stopped the count, so it might never go out. A release that only waits for open tasks (`after: all` with the default brief, or one auto release queued) is cut rather than a new one queued; another waiting release stays and a new one is queued. Two releases never run side by side (F195a).
- Fixed: a task brief over 24,000 characters on an interactive Claude Code slot never reached the session: the first message pointed at the system prompt, but the start's flags were built before the brief file was written, so the first start had no `--append-system-prompt-file`; the session said it had no brief and stopped, and the task ended with no commits. The flag is now on the first start too. The run also reads each task session's transcript and, when the brief did not arrive (no brief in the system prompt, or a cut first message), ends the session and says so and why in the run log (B775).
- Added: on the run page, a chat's or slot's session scrolls back through its history: a drag (touch) or a wheel up (desktop) over the session draws the transcript above the screen, as Claude Code draws it, and back at its end the live session shows again in the same frame, with no line moved. A jump button (Jump to bottom, with a dot when there is something new) glides back to the live session. Scrolling of the page's other views is as before, and a session's history names files in the session's own folder relative, as Claude Code does (F191b).
- Fixed: Device Vitals' Clean could delete git-ignored work with a merged worktree (`git worktree remove` deletes ignored files) while its list said "nothing uncommitted". Now a worktree comes ticked only when what git ignores in it is build output recognised by its tool's mark (a CACHEDIR.TAG folder, CMake build folder, Cargo profile folders in a target folder, venv, node_modules, egg-info, .pyc) or a link; any other is listed unticked and the line names what it holds. A tick for a worktree whose ignored files changed since the list is refused. A git repository inside a build folder counts as held, except a CMake-fetched one under _deps with no change or commit of its own (B776).
- Fixed: two harness loop sessions refreshing one provider's login at once no longer remove it from Pi's `auth.json`: the second finds the fresh token, keeps the login and uses the token without refreshing again (B771).
- Changed: this repo's merge joins a conflict in CHANGELOG.md itself, with no fix session: `[run] joinable` holds it and `[run.join]` runs `tools/changelog_join.py`, which keeps both branches' new entries once and puts an entry written before a release under Unreleased, not the released version (C47).
- Fixed: on the run page, on a touch device, a tap on the slim message box while the session still scrolls with momentum stops the scroll and opens the message box with the keyboard, and it stays open; before, the scroll went on and the box did not open (B218b1).
- Added: `[models] control` takes another provider's model (`<provider>:<model>`): a control session then runs on the harness loop in chat mode (many turns, waits for the person between them, control brief as system text, closes when idle and reopens as Claude's do, `agent-runner control --resume SID` goes on by session id). No Remote Control (so no control server), push, Artifact or Monitor there; pages go through publish-page and `plan concept --page` takes `/concept/ID` for one with no claude.ai link. Its git fence: no push in the project, no commit/merge in the main checkout, no edits of its tracked files (F406f).
- Added: `/live/NAME` has `queued`, how many messages sent to the session are still waiting in Claude Code's queue, read from its queue entries in the transcript so a reload keeps it; background events are not counted, and it is 0 when idle. `chat_to` with `force` and no text sends one Escape, so Claude Code takes the queued messages in as its next turn; no text is typed, so nothing is sent twice, and with nothing queued or the session not working it does nothing. If the interrupted prompt went back into Claude Code's input, Enter sends it from there; two presses at once interrupt once. Nothing on the page uses it yet (F190b).
- Changed: on the run page, one tap on the slim message box of a chat or slot opens the full message box with the keyboard on a touch device too; before, a phone needed a second tap. The draft and the session's size stay (B218b).
- Fixed: Copilot on a GitHub Enterprise domain works past the login: the harness loop's token refresh, model list and model calls all stay on the stored domain, also when the token names an address off it (githubcopilot.com); a model the domain does not list for the account is refused with the ones it lists (of those the login package knows). `--enterprise` and the asked domain also take `https://company.ghe.com/`, trimmed to the host, and `run login` lists the host (F406b).
- Added: the run page's Settings signs in model providers. A `[models]` role, kind or fallback that names a provider with no login says so on its row, with Log in, and its tasks wait for the login (the Save is kept). Log in, also on each provider under Advanced > This machine > Providers, opens one login sheet for claude and every provider: Copilot asks github.com or a GitHub Enterprise domain first, the device code is shown in words, and a typed key goes only to the terminal. Without the page's key the `run login` command is shown as before (F406c).
- Added: `agent-runner setup` asks at a terminal which providers to use (Claude Code, GitHub Copilot, Codex, Gemini, Ollama), logs in to each pick there, and writes the first pick's `[models] code` and `fix` to runner.local.toml, asking for a model id unless the pick is Claude Code; a kind in `[models.kinds]` on another provider moves to the pick. With no terminal it asks nothing and prints the login commands; with no Claude Code it says what cannot run yet and starts no session (F406d).
- Changed: the run app's page is sent gzipped when the browser accepts gzip, compressed once per page version and project, with an ETag and `Cache-Control: private, no-cache`, so a switch back to a project gets a 304 with no body; before, it was sent whole and uncompressed, `no-store`, on every switch of project. The key is still checked first, so a matching ETag with a wrong key is 403. This holds on the run page, through Runner Home's `/p/KEY/`, on Home's own page and on the page Home shows for a project with no run up. The run page's other answers stay `no-store` (the terminal page is cached this way already, F206), and `/events` is never compressed (B769a).
- Fixed: on the run page (and Runner Home's page), a pressed project shows at once that it is opening, until its page comes; before, the old page stood still about 0.7 s on a phone. The project's row in All projects and its card say "Opening…" with a moving dot, its Open button is dimmed as busy, and at the project's own sidebar level (Alt+1 to 9) the sidebar says "Opening NAME…"; a toast says it when none of these is on screen. The mark goes when the page comes back (Back), the load fails, or after 20 seconds (B769b).
- Changed: on the run page's Settings, a change no longer saves at once. A switch, pick, stepper, typed value, kinds row, Reset or More…'s "Change on this device" or "Change for everyone" collects on its row ("Not saved yet"), and a bar at the foot of Settings says "N changes not saved" with Undo (drops them) and Save (writes them all, each to its home; those for everyone are one commit). After a Save it says "N changes saved" with Undo (puts the earlier values back; one changed since by something else is left and said) and a close x. Unsaved changes are kept per browser when the page is left or reloaded. A change the run does not take comes back in the bar with why on its row; the others are saved (F202b).
- Added: `agent-runner setup` asks, when ttyd is not found, to install it with this machine's command (run only on yes), since the run page needs ttyd to show sessions (F403).
- Added: the run page and Runner Home serve the Provider logins as data, `GET /logins` (F406a): each provider in `[models]` (the built-ins and `[models.providers]`) with its name, whether it is logged in and where (`ok`, `where`), its login terminal (`terminal`, '' if none), why it has none, and the state of its login (`login`: '', running, done or failed, with what it said and which tasks reopened). Never a secret. `GET /terminal/login-PROVIDER` opens `run login` in a terminal, the only place an API key is typed; Copilot on a GitHub Enterprise domain is `login-copilot~company.ghe.com`. Runner Home serves it with no run up, and a login there reopens the tasks parked for it in every project. Nothing on the page shows it yet.
- Changed: on the run page, coming back to Settings after 5 minutes or more away clears its search (Find a setting); a shorter trip keeps it (F204b). Away is another view, a thread, or the page hidden; a trip counts over Refresh of the page too. The Changed filter and unsaved words in other settings fields stay as they are.
- Fixed: on the run page, + Chat at the top right of an open chat or a slot's session is disabled for one second after the file picker closes (a file picked or cancelled), as + Task on Home and Plan already is, so a double press in the picker cannot start a chat. It comes back by itself, also while a redraw waits; attachments, Send and the sidebar's + Chat are not held (B768).
- Added: Settings > Advanced > This machine: Claude Code program is now a picker of the Claude Code programs found on this machine (PATH, ~/.local/bin, ~/.claude/local, /opt/homebrew/bin, /usr/local/bin), each with its name, version and path; a pick waits in the Settings bar until Save. A kept wrong value stays listed, marked not found, with the reason, and Other path… takes a wrapper. Under it, Providers lists each provider's login, and says a provider is chosen per role in [models] (F405)
- Added: an other device can have a web page (an http or https address, no sign-in in it), set in the Tools page's Add/Edit sheet with an optional start command and its working directory. `run device start NAME` and `run device stop NAME` (also `POST /tools` ops `start` and `stop`) run that command detached, outside the run and session, so it outlives them; `run device list` and `show` say whether it is running, stopped or failed, and a failed one shows its last 20 output lines with stored secrets hidden (F407)
- Added: a device's web page on the Tools page: its card shows the address and state (running, stopped or failed), with Use (opens the page in a new tab), Start and Stop; a page with no start command has Use only. Over plain http Start and Stop are disabled, Use works. A Needs you item whose task names such a device shows Use NAME, or Open NAME in Tools while it is stopped or failed (F408)
- Fixed: a person's answer typed in a chat as a task's `run ask` ran was lost. `plan tell ID` on a task no slot runs now drops nothing: if the task asks the person it prints the question and the exact `plan confirm ID "TEXT"` or `plan change ID "TEXT"` to run if the text answers it, otherwise the `plan note ID` to run; `plan confirm` and `plan change` also settle an ask the run has not blocked yet (e.g. its block is held by a merge), so it never shows under Needs you and the session resumes with the answer (B767).
- Fixed: on the run page, without ttyd, the card "The session cannot be shown here" in a chat or slot listed the install commands of every system and then this machine's again. Now it is one sentence with only the command of the machine's package manager, shown as `code`, named once; the list of all commands appears only where no package manager is found. On Windows, a ttyd that winget installs while a run is up is now found (in winget's Links folder or its package folder under `%LOCALAPPDATA%\Microsoft\WinGet`), though that run still has the old PATH, so opening the chat again shows the session with no restart (B761).
- Changed: `[models] review`, `docs` and `feed` take another provider's model (`<provider>:<model>`), as the task's session does. The spec review on another provider, or on a task on the harness loop, is `agent-runner review [ID] [--base BRANCH]`: a fresh read-only one-shot given only the task's diff and brief, which prints its findings (the brief says to run it before `done`). A `docs` model on another provider leaves the edits to the task's session, and a `feed` model on another provider keeps the run page's local copy with no claude.ai page; `publish-page` then exits 0 and `done` takes `/concept/<ID>` as the concept's page. The harness loop's `--tools a,b` limits a one-shot's tools (F406e)
- Changed: while `[run] agent` is wrong, in a settings file or in what the run itself loaded, the run stays up and starts no agent session (no task, no resume of a cut-off one, no fix or repair session, no control session, control server or one-shot page), and never another agent instead, also when the run still has a good agent loaded from before the wrong value was saved. Running sessions go on and finished work still merges, with a merge that needs a fix or repair session waiting as `task/<ID>` until it is fixed; control sessions a shutdown cut off and messages held for a usage limit wait too. `run control`, `control --new`, + Chat and Resume answer with the problem and its fix, the run log says it once and again when it is right, and everything starts again on the next tick once the value is fixed or the program installed, with no restart (B764c).
- Fixed: `plan tell` and `plan change` to a slot whose agent has just run `run ask` (its end mark `<notes>/slotN.end` is written) no longer type into the ending session, where the text was lost though it printed told or, for a tell, said no live pane and gave `plan note`. Now a tell waits until the ask is parked, then fails (exit 1) with the question and the exact `plan confirm`/`plan change` commands; if the session has not ended within 30 s, it prints the same and says to run the command once it has ended. `plan change` notes the change in the plan (exit 0), prints the same and does not stop the slot, so the parked work is kept. A `run finish` or `run wait-for` end mark changes nothing (B770).
- Changed: a red CI run's task names its failing tests: the first five on its line, all of them in its long form, which holds the log's FAIL lines and tracebacks before the last 40 lines. Keyed by workflow and failing test: while the workflow's task is open, a failing test it does not name is added to it; a closed task that names one is opened again, its earlier fixes' commits linked; a dropped task stays dropped and a new one names the test. A log that names no test works as before (T25).

## 0.64.0 (2026-11-24)

- Changed: at a terminal, bare `agent-runner` (the run picker) no longer starts a run when you pick one that is not up: picking a row always opens its launcher, the second screen. There `s` starts the run in the background (logged as started by picker), and the launcher then shows the run up with its link, or the error. No pick, and none of w, t, c or Enter, starts a run; a bare `agent-runner` without a terminal, `agent-runner run`, `--attach` and every Start control still do. Where there is no TUI (Windows, no tmux) the launcher has no `t`, shows the reason in a dim line, and Enter opens the run page (F402a)
- Added: on the run page's Plan view, a Find a task field at the top finds tasks by words or task id, in any case and in any order, over open, parked and done tasks (the whole plan text, not only titles; all words must match). With text in it the matches replace the groups, best first (an exact id, an id prefix, titles, then the rest of the text); the x clears it. Served by the read-only `GET /plan-search?q=WORDS` (F212).
- Fixed: on the run page on a phone, the first lines of a new chat or slot no longer stay behind the top bar: a drag down brings them clear of it (B766).
- Fixed: on the run page, a chat's session, found on an iPhone 15 Pro: (a) when the session redrew with a row more or less, its text jumped a line for a frame or more; the page now places the frame in the same frame as the redraw. (b) a chat never opened: the stand-in messages moved up when the session's chips came; the chips row is there from the first frame. (c) a network that goes silent with the socket still open (a cellular dead zone) looked live for the whole outage: now after 5 s with no answer and no session output the moving line and Reconnecting… show over the live screen, and the first answer dials again at once (about 1 s on the phone, was about 13 s). The page also asks /live one at a time and gives up after 8 s, so dead requests no longer pile up. (F206a)
- Changed: on the run page's Status view, the Run card's controls (Slot -1, Slot +1, Pause / Go on, Stop / Take the stop back, or Start the run when no run is up, and More…) now stand above the slots, under the state line and notices, with a line between; before, they came right after the last slot and looked like its own Drop and Take back. Each has an icon beside its word (minus, plus, pause, play, stop, undo, dots). The words, what they do, and the looks of busy and the main button are unchanged (B763a).
- Changed: a run that is up reads runner.toml and runner.local.toml again when they change, between its ticks, with no restart. A file that does not parse or a bad value changes nothing, and the run log says why; running tasks keep their own model and budget caps. Keys that apply on the next run only (`[run] web`, `web_port`, `web_https`, `home`, `notes`; `[plan] dir`, `repo`; `[git] master_branch`, `no_push`) still need Restart the run (F202a).
- Fixed: Settings refuses a wrong `[run] agent` and shows the reason on the setting's row, writing nothing (B764a). Before, any text was saved, and a wrong one broke the run page. Now a save, on this device or for everyone, refuses `pi`, `copilot` (name the model in `[models]` as `"<provider>:<model>"`) and an empty value; a save on this device also refuses a command that is neither on PATH nor a file (a relative path is from the main checkout). A save for everyone skips that last check, as other machines share it. Reset still works; a value already in a settings file is not changed by this yet.
- Fixed: a wrong `[run] agent` already in a settings file (a removed one, `pi` or `copilot`; empty; not text; or a command not found on this machine) no longer takes the run app or Home down (B764b). Before, `pi` and `copilot` stopped every command and Home lost the run's page. The settings now load, and the run page's Run card, Home, `status`, the run picker and the TUI say the problem and its fix in one line, as e.g. `[run] agent = 'pi' was removed: set it to "claude"; other models go in [models] as "<provider>:<model>"`. A run that is up keeps its agent when a wrong one is saved by hand, and the line is said then too. Holding starts while it is wrong is B764c, not in this change. `[run] backend = "pi"` and AGENT_RUNNER_BACKEND=pi still fail at start.
- Added: `[git] no_push = true` (off by default) is a no-push policy: the runner pushes nothing, and every session it starts (task, repair, control, one-shot) makes `git push` fail in any repository with git's message, so `--no-verify`, `-c` and child processes do not get around it. Settings > Merging shows it as Never push. It is a guard, not a sandbox (docs/REFERENCE.md, ### No-push policy) (F400).
- Added: the run page serves a session's whole history as data, `GET /history/NAME` (F191a), for a chat or a slot. It is read from the session's transcript in pages: the newest first, `&before=MARK` for older and `&since=MARK` for new. Tool calls are folded with their results, and diffs are shown as Claude Code shows them. It has the same access as `/feed`. Nothing on the page draws it yet.
- Added: on the run page, the Settings search (Find a setting) has an x while it has text, on phones too (the browser's own x, missing on iOS, is hidden); it clears the search, shows the full list and keeps focus in the field. The field stays the same element as the list changes, so typing no longer loses autocorrect on a phone (F204a).
- Fixed: on the run page, an open chat and a slot's session have + Chat at the top right of the top bar; it starts a new chat at once and keeps the old chat and its draft. Not in an empty new chat view or a starting chat; the other views keep their own + button. When the bar is tight on a phone, the title shortens first, then the run pill (B762).
- Added: on touch in the run app (Home's page too), pulling down past the top of the main view or the sidebar refreshes the page, as on a normal site: the locked document leaves the browser's own pull-to-refresh nothing to fire, and an installed Home Screen app has none. A spinner follows the finger, is ready past 70px, and letting go does what the Refresh button does (typed text is kept). Not over a sheet, popup or concept, in a text box, or in a chat's session, which keeps its own scroll (F401).
- Added: `tools/windows_vm.sh --all` runs every `tests/test_*.py` of the worktree on the Windows VM, one `-- FILE: passed|failed, N.Ns` line per file and a last summary line (exit code of the first failing file; 2 when there is no VM). The Windows CI section of docs/REFERENCE.md now runs it before a merge instead of the GitHub ci workflow, which is disabled since 2026-11-24 (too many emails).

## 0.63.0 (2026-11-24)

- Changed: while a critical `(alone)` task is ready and only this run's running or merging tasks hold it, the run starts only critical tasks (non-alone critical ones still start) until the running tasks have ended and merged; then the alone task takes its turn. Before, normal tasks kept starting, also on top of a merge under way (F198), so the slots never emptied and a file split (F200b) started only when the tasks it was for were done. A non-critical `(alone)` task still holds no start. No hold when a task in the way will not end by itself (a taken-by-hand or other runner's alone task, one waiting for a usage reset, a merge held by edits in the main checkout or crashed, the branch of a closed task), or when the alone task is tried this run, parked too often, being split, or its shared tool is missing. The dry run says `C1 runs alone next` (F208).
- Changed: a control session (chat) that files a restyle with `plan restyle` also counts as about that restyle and its build task, as with a concept under `plan concept`, so it is told the settled line when someone else settles it, not when it settles it itself (F211).
- Fixed: on Windows, starting a background run from an interactive terminal no longer crashes. The "run started by" record (run.log, events.jsonl) asked for the terminal's name with os.ttyname, which Windows Python lacks; it now records tty `terminal` there, and `no tty` as before when there is no terminal. macOS and Linux are unchanged. Not yet checked on a real Windows machine (B760).
- Changed: under Runner Home, on the run page, switching to another project (the project list in the sidebar, Alt+1 to Alt+9, an All projects card or its Open button) opens that project's Home view; before, it carried over the view last open in this tab (e.g. Plan). Coming back down from All projects to the project you were in still restores what was open, a reload reopens its place, and a Needs you link opens its item (F203).
- Changed: on the run page, a chat's session is one frame, kept loaded out of sight, and only the open chat stays connected. Switching chats shows the chat's last screen at once, dimmed under a thin moving line until the terminal has drawn, so there is no blank frame and no move; a chat not seen in this page shows its latest messages. A dropped connection keeps the text and dials again by itself (250 ms, then up to 15 s), and says Reconnecting… after 5 s. An ended chat keeps its last screen with its Resume card above the message box. The chat's title in the top bar opens the chats with their last line and Rename this chat at its foot, where a tap on the title used to rename; chat to chat has no slide. The terminal page is gzip-compressed and kept by the browser. On attach, a slow viewer gets a 256 KB queue and then a redraw, and is dropped only after 60 s of taking nothing, for sessions started after the upgrade (F206).
- Changed: a control session (chat) also counts as about a concept or DECIDE it filed itself, so it is told the settled line when that is settled elsewhere: the concept and its build task (filed with `plan concept`), a task it blocked with `plan block ID "DECIDE: …"`, and its own open question the run filed under Needs you when closing it (told again if the chat is open again). These are kept per session id in `<notes>/settled/<session id>.filed`; the chat that settles it itself is not told, and a concept and its build leaving Needs you with no command is one line, not two (F209a).
- Fixed: on the run page and Runner Home, a refresh no longer replaces the text field being typed in, in the Add a project sheet or a device sheet on the Tools page, when nothing else in that sheet changed. Typed words used to sit in the sheet's markup, so any refresh after typing drew the field again and broke autocorrect. Typed words for Add a project still come back after closing and reopening. Also, a device opened for editing a second time shows its saved values (emptied fields are drawn again), and the device sheet's note on renaming now always shows when editing: "If you rename it, a task that needs it keeps the old name until it is edited." (B222b)
- Fixed: on the run page, typing in a Needs you sheet's reply box (or an input of a give item) no longer breaks autocorrect or replaces characters (B222a). A refresh (a new age, notes, steps, buttons) used to draw the whole sheet again, field included; now the field in use stays the same element and only what changed around it is drawn. Typed words still come back after closing and reopening.
- Changed: on the run page, the Chats list (top and Quiet) runs newest to oldest by last activity instead of a hand-kept order; pinned chats stay on top in their own order, and only pins drag to reorder (F201).
- Fixed: Talk on iPhone: the mic button's press lets the browser play replies, so the reply to a voice message is read with no tap on the speaker (B166).
- Changed: on the run page, a chat's or slot's bars hide and come back more slowly, 400ms (`--dur-bars`) instead of 250ms; the top bar, notices, message box, slim message box and dock stay in step. Other `--dur-slow` motion keeps 250ms, and it is still instant under reduced motion. The person on an iPhone found it too quick (B218a).
- Changed: on the run page, a concept card has one Chat button, which opens the empty new chat view about that concept; nothing is sent until the person sends, and the first message carries their words with the concept's chat text (page link, local copy, guide concepts). The second New chat button, which started a session at once, is gone; the TUI's N is unchanged (B219a).
- Fixed: a finished research task whose diff changes code the person has not answered to ship or asked for no longer lands unasked by riding along in another task's merge (B225). Before, only the task whose turn it was got checked. Now it is left out of other tasks' merges, of a merge built ahead, and of a merge adopted from an earlier run that holds it, which is built again rather than reused; its own turn still blocks it on a DECIDE under Needs you, as before. Findings-only research, and code the person shipped or asked for, still ride along.
- Fixed: `run done` no longer commits a file its own stdout or stderr goes to (`run done … > done.log 2>&1`); it compares the file's device and inode with the staged files and leaves it uncommitted in the worktree, so an empty log no longer reaches a merge as code. At the merge of a research task, a new empty (0 bytes) file that is not findings does not count as code: a commit on top takes it off the branch first, so the findings land without it and the person is not asked. A diff with real code too still counts the empty files (an `__init__.py`, a `.gitkeep`) with it and asks as before; an existing file emptied is still code, and tasks that are not research are unchanged (B224).
- Fixed: a DECIDE's heading under Needs you is its question, whole, on the run page's card and sheet and in `agent-runner ui`, with its task's title small under it, instead of the task's cut-off first words. Its background follows as plain paragraphs (two lines on the card), then its answer buttons; What to do shows only when its ask file has steps. Other kinds are unchanged (B223b).
- Fixed: a DECIDE under Needs you is a question, not steps. Its text used to be split into a "What to do" list; now, without `steps` in its ask file, it has none: the rest of its words are background paragraphs, and its notes are kept. Its question is the last sentence that ends in a question mark (else the ask file's `summary`, else its first sentence), and that is the card's line too; `agent-runner needs` shows the question instead of the first sentence, without the options bracket. CONFIRM and BLOCKED are unchanged (B223a).
- Changed: on the run page, a scroll jump that a press causes glides (F189a): Talk going to its end when you send or switch mic and typing while scrolled up, a refused Done or Rename going to its field, and the arrow keys in the slash menu. Your own scroll takes it over; under reduced motion it is instant.
- Changed: on the run page, a fold that opens in place moves what it pushes and its card's lower edge on a press, a sheet that takes another's place moves from there, a concept page slides in from the right, a new Talk chat fades in, a chat row's buttons and the session's key row slide in, and the outbox popup fades out; under reduced motion it is instant (F189b).
- Changed: parts of a split task (siblings such as P13a and P13b) run side by side when both name `files:` that do not meet and neither has `after:` the other, as any two tasks do (`shared_files` aside). A part naming no `files:` still waits for every other part, and they for it, also one finished and not merged yet. A task and its own part still never run together; a clashing part is still reported as waiting for a sibling, and a clashing sibling never starts on top of a merge under way (F198 unchanged) (F199).
- Fixed: a research task whose diff changes code is held with a plainer DECIDE under Needs you (B221). It says what the change does, that it is finished but held because the task was research, and what each answer does, with two buttons: Ship them (recommended) or Queue them as their own task. Only the answer's own words are read, so a note that quotes the question no longer merges the code; and when the person's own words asked for the code (`asked for:` in the commit message, checked against their request, answer or `plan tell`), it is not asked at all.
- Fixed: on the run page, a double press in the photo/file picker (iPhone) could land on + Task and open a new task chat (B213). Now, from the picker closing (files picked, or cancelled where the browser says so), + Task on Home and Plan is disabled for one second, across redraws, then works again by itself; attachments and Send are not held.
- Added: Talk settings has a Mic test… sheet (B162b1) for looking into a mic that is on but hears no words, e.g. on an iPhone: four tries, one press each, with an Earbuds choice (Not said, Off, On) and no message sent. Copy mic test copies a report of the tries so far (times, letter counts, sound levels, the earbuds choice, never words or device names), and the mic report (Copy mic report) now also says what the page did before the press (time since load, sounds started, listens with and without words).
- Changed: a task that clashes with finished tasks only by files, and only with ones all in one merge under way, starts at once on top of that merge in its own worktree, not after the gate. It lands only after that merge is on main; if the merge is refused or built again, its own commits are moved onto main alone (in a fix worktree) or parked as wip/<ID>, and an unlanded commit never reaches main. Not for (alone) tasks, releases, siblings, tasks in an ordered section, after: waits, or a task that also clashes with a running task (F198).
- Changed: the slot brief (in every project, a project's own prompt template included; not a Concept (K) task, which builds nothing) and the guide (`agent-runner guide` and its queue page) tell agents to put a new area in a module and a test file of its own, unless the project's rules or layout say otherwise, and to split work into parts that name different files (`--files`, the test file too), with `--after` between parts that must share one; a session told to split a too-big task gets the same rule. Tasks on the same file wait for each other, so this lets several slots run at once and merge more cleanly (F200a).
- Fixed: turning Remote Control off (`[run] remote = false`, or `control = false`) and restarting the run now ends the control server (B220). Before, a restart that reads the settings replaced the run's process in place, so the run kept its pid and start time; the start's sweep took the control server for its own and left it up, so the Claude app kept notifying of remote sessions. A start with Remote Control off now ends any recorded control server, whichever run key it was recorded under; with it on, the server is kept as before. Control sessions are not ended by this, as before.
- Changed: the guide and the concept (K) brief no longer tell an agent to put "Go with" answer buttons (`pick-links`) on a concept page; they did not work in the Claude app. The person picks in Concepts or Needs you on the run page, or in the chat (C40a).
- Added: the example project ships with agent-runner. `agent-runner demo [DIR]` copies it to a folder of its own (default ~/agent-runner-demo; refused when the folder exists), makes it a git repo whose origin is a bare repo inside its .git (no network), and prints the next step; no agent starts until the person starts a run. `agent-runner demo --remove [DIR]` takes away only a folder the command made, with its run worktrees, and refuses while a run or session is up there. Its plan has three tasks that run side by side, some with after:, one DECIDE under Needs you, three done. examples/demo.sh uses the command. To see how a run works on something that cannot hurt, also from a uv tool or pipx install (before, only a clone had examples/hello) (F194a).
- Added: under Runner Home, with no projects, Home offers Try the example project beside Add a project. It makes ~/agent-runner-demo (or takes the one already there; another folder there is refused, with why), lists it and opens its page; nothing starts. On the example project's pages a walkthrough of seven short cards points at the parts of a run, one at a time, with Back, Next and Skip; the sidebar's Walkthrough row brings it back (F194b).
- Added: in the example project, `agent-runner ui` shows the same seven walkthrough steps as the page (one shared list, `agent_runner/page/084-walk.logic.js`), worded for keys: `<` back, `>` next, `/` skips it and shows it again. Where you are is kept in the project's `.runner/walk.json`. A step focuses and marks its panel (F194c).
- Added: `agent-runner` in a folder that is not set up (no settings file, no plan, no run log) names `agent-runner demo` in one line, in the run picker too (F194c).
- Changed: on the run page, a chat's or slot's bars going over the text on scroll are one motion on `--dur-slow` and `--ease` (B218). The top bar and a notice's row slide off the top edge and fade, as Talk's bar does; the message box shrinks into the slim message box and grows back from its bottom edge, which stays still, while the dock's words ride down onto the slim row's place and the slim row fades in, so the two are never both readable. A reversal mid-way goes on from where it is. No text line or the frame moves, hidden things take no taps, and the draft is kept.
- Fixed: Talk could cut off the end of what the person said (B216). (a) Words shown as heard but not yet final when a listen ended (a release, a tap, the recognizer ending) were dropped once an earlier piece was final; now all heard words are sent. (b) In Tap, a short pause no longer sends: the mic listens on and sends when 2 seconds bring no more words (once 2 more if speech has begun); a tap sends at once, auto listen still ends at a silence, and a hold is unchanged except that, if the system takes the touch, it waits the same 2 seconds, and after words it starts listening again at once (before, up to 250 ms later after a short listen). (c) The mic report has a line for what ended a listen that sent words (e.g. `sent 16 letters, ended by a pause`), and growing results are one line. Words already heard also go out when the recognizer cannot be made again.
- Fixed: on the run page, scrolled up in a chat's session, the floating round menu button no longer covers the text; it fades with the rest of the top bar and takes no taps, and the bar returns as before (B215). The drawer's edge swipe still opens the menu, and keyboard focus on the menu button shows the bar.
- Added: a Manage releases setting (F193a): `[run] releases`, on by default, in Settings above Release by itself, for a project that needs no releases to turn off. Off, no release is queued by itself, a New release is refused, `status` has no release line and `agent-runner plan` no Releases group; an open release stays in the queue as an ordinary task, and a typed `plan add V` still works.
- Added: in the terminal UI (`agent-runner ui`), with Manage releases off (F193c), the Status panel has no release tab or release line, the Queue no Releases group, R does nothing in Status and Queue and is gone from the key hints and the `?` keys list, and an open V task is an ordinary queue row. On, nothing changes.
- Added: on the run page, with Manage releases off (F193b), the Plan view has no Releases group, the Status view no Release section, and neither has New release buttons or an empty heading; the claude.ai run page copy has no release rows, and an open V task is in the Queue as an ordinary task. A New release already sent stays shown until it is settled. On, nothing changes.
- Added: on the run page's Settings, with Manage releases off (F193b2), 'Release by itself' is hidden, also from the search, the Changed list and its count, and its value is kept; the 'Features, fixes, tests' row no longer names releases, also in the search. The Manage releases switch always shows, a save is followed at once, and turned back on, everything returns with its value. On, nothing changes.
- Changed: control sessions and slots no longer show the diff Claude Code prints under a Bash command that changed a file (e.g. "Updated plan/TODO.md +1" and its green block), which took much room on a phone (F188). The run's settings for them carry `bashEditDiffEnabled: false`; Edit and Write diffs are unchanged, and a session already open keeps showing it until it starts again.
- Changed: on a phone, a chat row's three dots (⋯) in the run page's chat list no longer open a bottom sheet. They show Rename, Pin/Unpin and Delete as icon buttons in the row itself, over the title's right end. Delete takes the dots' place, so two taps on the same spot delete the chat, with Undo shown in the row and no further confirm. One row is open at a time; a tap elsewhere, Esc, one of its buttons or closing the drawer closes it, and that outside tap does nothing else. Desktop hover buttons are unchanged (F187).
- Fixed: a task with `after: all` (a release, say) or `after: all above` no longer waits forever on (1) a task whose unfinished `after:` chain leads, through any number of tasks, to a Parked or Stretch task, which a run never starts; or (2) a split task with an open subtask that is blocked for you (Needs you), shelved, in Parked or Stretch, or itself stuck on one of those, or a task waiting on such a split task (B209). The split task's other subtasks that can run still hold it, and all hold it again once you answer or the task is brought back. A split task whose line does not say `(split into …)` holds it as before while it has a `task/<ID>` or `wip/<ID>` branch, since it can still land. `status`, `plan ID`, `plan waiting` and `plan reopen` say it as 'not waiting on: P1 (after P1b)'.
- Fixed: the run page's message box always shows its send arrow at its own size, not a wide Force send text button whenever the session works (B208). The arrow is Force send (bolder, with a second arrowhead, labelled Force send) only while the session works and the box has words or an attachment; otherwise it is the plain Send. It changes in place, so focus and the caret stay. Before, the wide Force send button showed even with an empty box. What sending does and Stop are unchanged.
- Fixed: a task with `after: all` (a release, say) or `after: all above` no longer waits forever on a task whose unfinished `after:` chain leads, through any number of tasks, to one blocked for you (Needs you) or shelved (B207). Before, the release skipped the blocked task itself but waited on the one that waits on it, so the run sat idle. Tasks that can still run hold it as before, and once you answer, both hold it again. `status`, `plan ID`, `plan waiting` and `plan reopen` say e.g. 'not waiting on: B415 (needs you), R89 (after B415)', now also for `after: all above`, and `plan ID` prints the `all above` line.
- Fixed: the run page copy (on claude.ai) shows a Needs you DECIDE's options after its ask, as its answer buttons label them, e.g. "Full (recommended) / Small" (B203). Before, since F181c takes the options bracket off the question, the copy drew only the ask, so the options were missing.
- Fixed: under Runner Home, the run page's record of when you last opened each chat is kept by project (B205), as `ar-seen:<project>`. Before, opening c1 in one project overwrote another's c1, which could show a chat as needing a reply wrongly, and only the first project visited took all its chats as read. A page whose address names no project keeps the plain key. The old record is not carried over under Runner Home, since it does not name its project: the next visit to each project takes its chats as read.
- Fixed: on the run page, words typed in the message box of a chat still starting stay in its box when the chat gets its name, or when it is sent again with Retry (B202). Before, they were left behind under the stand-in's key and the box came up empty. If the named chat's box already held a draft, the moved words come after it, on a new line. Dictation that is running carries on into the named chat's box.
- Fixed: under Runner Home, every project's run page shares one localStorage, so the chat keys now name the project (B200): `ar-draft:<project>:c1`, `ar-hist:<project>:c1` and `ar-sent:<project>`. Before, c1 of one project showed or kept another's message-box draft, sent-message history and sent messages. A page whose address names no project (the run's own) keeps the plain keys. What was kept under the old keys is not carried over under Runner Home, since it does not name its project.
- Fixed: a task's pick sheet (`<notes>/sheets/ID.json`) is removed as its ask file is (B204), when the item is answered, ticked or dropped, its task reopens, the run blocks it again, or a new session starts on the task. Before, the sheet stayed, so a typed `go` (`sheet ID --go`) on a later ask ran the old one. The published page is not touched.
- Added: a New release card (F186). The Plan view's Releases group ends with one, and Home's and Status's release part lists each release and then one; it has `release_wait` (only while a task works) and `release_now`, and says what is open: "V17 is already queued." or "V16 is releasing now; V17 is already queued." With a release open, a press asks in place, "V17 is already queued. Queue another release?", before `plan add V` runs; the Yes carries the ids it was asked about, so a double press or a double Yes never queues a second release unasked, and a stale page or TUI asks too. In the TUI, R in Queue opens the release tab, and D drops the release that waits. A release that has not started has its own Drop, asked first ("Drop V17? It leaves the plan, and nothing is released."); one a slot runs, merges or a person took is refused. A slot's Drop and `plan add V` in the CLI are unchanged.
- Changed: a DECIDE's short answers are buttons from the brief (F181d). The slot brief and the control brief ask for a bracket that ends the question, before any link, e.g. `DECIDE: Which look? [Full (recommended) / Small / No change]`; a slot's `run ask` gives its options in `<notes>/asks/ID.json` instead, since a bracket there gives no buttons (the run appends words after the question). One DECIDE per question. A pick sheet is now only for a choice with more than one question, or whose answers each need a why. A control session's question over 240 characters is cut before its bracket (and the links after it), so the bracket survives when it is filed under Needs you.
- Added: a Needs you DECIDE with a pick sheet has answer buttons (F181b). On the run page's card and popup and the TUI's answer tab, "Go with the recommended picks" runs `sheet ID --go`; when the sheet has exactly one question, each of its answers is a button too, the recommended first and marked "(recommended)", and runs `sheet ID --picks "ID picks: q=b"`. The popup's note goes along, and no AI session starts. No sheet buttons when the DECIDE has no link, the sheet does not read, its questions were already answered, the item has inputs, or the ask has its own options (ask file or bracket), which win; answers that are too long (over 80 characters) or the same give only the Go button. The chat's first message still lists the sheet's questions.
- Added: a Needs you DECIDE's options are answer buttons (F181c). `options` in `<notes>/asks/ID.json`, or a bracket that ends the question (`[Full (recommended) / Small]`), gives one button each on the run page's card and popup and the TUI's answer tab, the recommended first and marked "(recommended)". A press sends that name at once, with the popup's note, and no AI session runs; Reply with other words stays. An item with inputs has no option buttons and keeps its bracket.
- Fixed: a message sent from the run page to a control session still starting is held in the Outbox as pending, 'waiting for the chat to start', until the session takes input (bracketed paste on, and its own first message typed), then the held messages go in order; it holds only later messages to the same chat. After 2 minutes it fails as 'Not sent: c3 is still starting, so it could not take the message', with Retry, Edit and Discard. Talk's words wait the same way on the run's side, up to 120 s. Not on Windows, where nothing is held (B158).
- Added: the run page's https address on Tailscale (F96). With Tailscale connected and the run page on every interface, the run serves it through `tailscale serve` on `web_port+1` and prints `https://<host>.<tailnet>.ts.net:8771/?t=…` first in `status` and the run log, so the browser gives the microphone to Talk; `[run] web_https = false` turns it off. The run turns its Serve rule off at its stop, and a rule it did not make is left alone. Behind Runner Home the run makes none. Without it (no Tailscale, port+1 taken, serve refused) the run stays http only and logs 'run page: http only, <why>' once.
- Added: the Claude login banner has a Log in again button (F126b). It opens a sheet that runs `claude auth login` in a terminal, served by the run or, with no run up, by Runner Home: `1. Open the sign-in page`, then `2.` paste the code the page gives into the field and Send code, since a phone cannot paste into a terminal. The login stays up 10 minutes after the last browser leaves, so the code matches; once it is renewed the banner and sheet go with the toast 'The login is renewed'. Without ttyd the sheet says how to install it.
- Added: the run page and Runner Home (its All projects view too) show one Claude login banner (F126a), a row under the top bar, when the Claude login is under 3 days from its end, has ended or is missing, e.g. "Claude login expires in 2 days: log in again (claude auth login)". It has one button, Log in again (F126b), and clears by itself after a new login. A run's page speaks for the run (only with `[run] agent` claude); Home speaks for its machine (only when one of its projects has `[run] agent` claude).
- Added: trusted networks (F136). `agent-runner home trust add NETWORK` (a CIDR, or `tailnet`) lets devices on it open Runner Home and a run's page without `?t=`, with no restart; `[ui] trusted_networks` does the same for a run's own page. Off by default, and loopback is never trusted.
- Changed: each open release has its own row (F185). The plan view's Releases group (above Queue on the run page, in the TUI's queue panel, `agent-runner plan` and the claude.ai copy's queue box) lists every open release once, e.g. `V17 Release · waits for 2: F1 one, F2 two`, and `status` has one `release:` line per release; the newest landed one follows as `V16 Release 0.62.0 · released 17:06`. Before, only the first had a row and the rest were near-identical 'waits for everything before it' lines.
- Added: with Runner Home running, the Claude login warning is pushed once a day per machine (local date) as a device alert, "needs you: box: Claude login expires in 2 days: log in again (claude auth login)", in the events of each running project whose [run] agent is claude; `since` shows it and `since --follow --needs-you` sends it. The day is kept over a Home restart; with no run up it is tried again on the next sample, and once the login is renewed nothing is pushed until a new warning comes (F126c).
- Fixed: on a phone or tablet, Return in the slash menu picks the highlighted command, where it could close the menu and make a new line. On touch the pick ignores Shift (a soft keyboard that auto-shifted may send Return with it; unchanged on a computer: Shift+Enter is a new line), and a Return whose keydown comes as keyCode 229 or without a key name picks at its line break (beforeinput). Composing never picks; a command typed in full still gets a new line. Not yet checked on an iPhone (B188).
- Added: `status` and `agent-runner ui` show one line when the Claude login is under 3 days from its end, has ended, or is missing, e.g. "Claude login expires in 2 days: log in again (claude auth login)" (F126). It is not shown with an API key, an auth or OAuth token in the environment, on Bedrock, Vertex or Foundry, with another ANTHROPIC_BASE_URL or an apiKeyHelper, or for a [run] agent other than claude; on macOS, where Claude Code keeps the login in the Keychain, a missing file is not a warning.
- Fixed: on Windows, a client of a session's 127.0.0.1 port that never sends its token is dropped after 5 s; it had stayed connected, though with no output sent and no input taken. An emoji typed or pasted into an attached console, whose two halves come in two reads, is no longer turned into replacement characters, and the console modes are put back even when its output is gone (F146).
- Changed: the run app's motion can be seen (F147). A chat's view slides in from the right over the one before, and back out, with its sidebar title carried to the top bar; your message springs to its place in Talk, or leaves the box upward and fades toward a real session; a reply's blocks fade in one after another, and only added words fade as it grows, with a wave of dots while at work; lists glide to their new place and a new card rises in; counts and state words roll; buttons spring back after a press; the drawer and sheet follow the finger and settle at its speed. Reduced motion still turns it all off (docs/STYLE.md, Motion).
- Changed: All projects is the first row of the run app's sidebar, with a count of what needs you in other projects (hidden when Home lists one project). Tapping it turns the same sidebar into the project list (Overview, Running, Idle, Off, Devices) and the main page into the Overview; a project turns it back. Alt+1 to Alt+9 jump to a project, Back and a right swipe in the open drawer go up a level, and switching keeps the tab and draws the last snapshot at once. The Overview has Needs you over all projects (three, then Show more by project), then running, idle or paused, off, and by name; each card shows its tasks by title, what landed today, one main button, and a … sheet (Pause or Go on, Slots, Stop, Unlist; Stop and Unlist ask first). An off project has its own page with Start run, which turns into its app once the run is up. Start, pause, slots and stop go through an outbox kept over a switch, with Retry on failure, and Home runs each one once. Each view has one + button top right (Project, Task, Concept, Slot, New talk, Device), and + Chat only beside Chats. Settings is not changed (F150).
- Fixed: a control session whose `control --title` text starts with a part of a part's id, such as F162a2, was named "<repo> · N · F162a2 ..." instead of "<repo> · F162a2 · ...". It now takes every id the plan takes (B201).
- Fixed: the run page and `agent-runner ui` refused a Needs you item whose id is a part of a part, such as F162a2 ("a task id (F83), not 'F162a2'"), so its inputs could not be sent and its Why it waits, Chat, task text and row actions (Drop, Later, Take back) were refused. They now take every id the plan takes (B199).
- Fixed: an attachment left unsent in one run page message box no longer shows in the next box, where it would have gone with that message (B182). Each box keeps its own unsent attachments, as it keeps its draft: they are there when you come back, an upload still going lands in the box it was added in, a chat still starting keeps its attachments when it gets its name, and the New version popup's Refresh brings each back to its own box.
- Fixed: a message sent from the run page no longer reaches its control session twice in one prompt (B161). The run started before F137's ids existed but served the newer page, so two open tabs that shared the stored outbox each posted the same message, and the two senders' pastes and Enters interleaved. Now one tab sends an outbox item (the one it was written in; another tab takes it over only once that one is gone for 20 s or closed), and a tab back from the background no longer sends or writes back its old copy; under Runner Home each project has its own outbox (it was one for all projects of the address). The run page keeps the ids it has acted on in `<notes>/acts-once.jsonl`, so a repeat after a restart gets the first result (an action cut off midway by the restart runs again); and a lock per session inbox (`<inbox>.lock`) keeps a paste and its Enter from being split by another sender (run page, TUI, feed).
- Fixed: the Needs you popup no longer repeats Full task as Why it waits when the agent left no session; it takes the keyboard focus and Esc returns it to the card (F162a2).
- Changed: a Needs you item's fixed answers (Yes, No, options, Done) are one list now, the run's RUN_CONTROLS (F180). An answer whose options changed since it was drawn is refused with "answers changed: look again", and an item shows at most 12 fixed answers; nothing else looks different.
- Fixed: in a Needs you item's details, a step after a ";" that follows what to see is a step again (F162a1). In "Tap Save: it says Saved; tap Undo; the list returns", "Tap Undo" had been listed under What you should see; now each piece after a ";" is classed again as a step or as what to see. Nothing of the ask is lost.
- Fixed: dropping every part of a `(split into …)` task no longer ticks the task as done when no part landed (B197). Once its last open part closes it ticks only if at least one part landed; if every part was dropped it stays open as one whole task, its `(split into …)` taken off, and `plan drop` says so and to edit the task if its text lacks the work the parts held. Dropping B195a and B195b had ticked B195 while its session ran. A dropped part is told by its `dropped: WHY` note.
- Fixed: a task `plan add` says is too big for one session is held before it runs (B196). It is written with `| split-by: <UTC time, 5 minutes ahead>`, and no run starts it before then, so its author can file the parts first. The hold ends at once when the first part is filed (`plan add A12 …`), when the task is edited to `(split into …)` or brought under the size, or on `plan move ID top`; `take` starts it any time. An edit that leaves it too big keeps the same end time, and a task a run's own agent files behaves the same. `status`, `plan`, `plan ID`, the run page and the TUI's queue say `waits to be split, starts in 4 min if it is not`, and the dry run says `waiting to be split`; while one is held the run does not show idle, so `once` and power off wait for it. Only `add` sets the field; a note, edit or approval that makes a task too big does not hold it. A slot had started B195 while its author was still filing its parts.
- Changed: All projects and the project switcher list projects with a run up (running, idle, paused) first, then those off, by name in each group (F148).
- Removed: a run no longer starts the runner feed or the board, on any OS (B195). It ends one an older version left, also one from before an in-place upgrade restart. Control sessions start no needs-you watch unasked, so nothing pushes Needs you items, pitches, releases or device alerts to the phone; what needs you shows on the run page, `agent-runner ui` and `status`, and "notify me when ..." still works on ask. `since --board`, `--feed` and `--run-pid` are gone. `[models] feed` now picks the model only for the run page's claude.ai copy.
- Added: shelved tasks show in the Plan view (F184). A task set aside from Needs you (`plan shelve`, Later) is listed under Parked, after the parked tasks and also when nothing is parked, with its title, id and what it waits on a person for. Its card opens the task's text and Chat; Bring back (`plan unshelve ID`) puts it under Needs you again, and Drop asks first. The TUI's Queue panel lists them last (U brings back, d or D drops). Display only: the task stays in TODO.md, still blocked.
- Fixed: on a phone, a chat scrolled up no longer shows the agent CLI's own input, its status lines or the key row. On a narrow window Claude Code's rule over its prompt is mostly the session's name, which a long name cuts with …, and the run page did not recognise it, so it showed the whole window; and Claude Code's "Jump to bottom", "N new messages" and "Waiting for your answer" pill, drawn over the middle of a line, was not seen as scrolled up, so the bars never went away. Now a named rule counts when it is as wide as the rule under the prompt and the prompt's > is on the next line, and the pill counts anywhere in a line when it stands in the middle of the window; a table, a markdown rule, or words that mention the pill do not count (B194).
- Fixed: Talk's Hold to talk holds again on an iPhone or iPad (press and hold listens, release sends; it had worked as a tap there), and on every device silence no longer ends a hold: if the recognizer ends by itself while the mic is held it starts again and keeps the words heard; only the release or a real failure (mic refused, no mic, two starts in a row cut off before any sound) ends it, and a release with no words sends nothing (B162a1).
- Fixed: opening a chat no longer moves it between Chats and Quiet (B193). A quiet chat you open stays gray in its place under Quiet, shown as the open row, also over a reload; an old chat whose unread reply opening it marks seen stays up while open and goes Quiet once closed. A quiet chat comes up only when something new is said in it, or it is pinned or renamed.
- Changed: the run page's Concepts view has a "New concept" button instead of its small + and Home has one beside Add a task (F183). Either opens an empty New chat view titled New concept; the first message starts a control session with "Concept: <text>", which shows the options page in that chat instead of queuing a K task. The inline new concept box is gone. The TUI's "+ new concept" row still queues a K task.
- Changed: a typed reply to a DECIDE on Needs you is its answer and runs at once with no session (F181a): `plan confirm ID "<words>"`, or `sheet ID --go` / `sheet ID --picks` for a pick sheet, on the run page and in `agent-runner ui`. Typed replies to other labels still open a new chat.
- Fixed: code in a diff in a session with the run's session theme is readable on the light page (F182). Plain code was mid grey (#616161); it is now the page's text colour, and the syntax colours that share no slot with the session theme's own have a light and a dark page value that reads at 4.5:1 on the added and removed rows. Claude Code draws this code in fixed 256-colour slots no theme names, so only the slots of the theme's base (dark or light) are filled: with a light base, slot 231, other programs' white text, stays white.
- Fixed: a chat's or slot's bars no longer move its text (B192). Its chips, message box and top bar only fade or slide over the text as the person scrolls up, and come back on scrolling down, at the session's end, or on a tap on the slim row; a line moves only by the scroll. The frame no longer glides or takes the first pixels of a scroll, except that while scrolled up with the bars away it takes part of an upward scroll to bring lines into the room the box left. The thin strip is now the slim message box: one 56px row with the draft or placeholder, and while Claude works Working and Stop. Claude Code's "N new messages" and "Waiting for your answer" now count as scrolled up too, so new output while reading no longer brings the bars back.
- Added: short asks for a person (F156). Every slot brief asks an agent to keep a CONFIRM, DECIDE or BLOCKED line, or a `run ask` question, to one short sentence (about 100 characters at most) and to write the rest to the task's `<notes>/asks/ID.json` (pictures under `<notes>/asks/ID/`): one action per step, words as seen on screen, no file names or code, no secrets. The file stays optional; `done --blocked` on a line over 200 characters that waits on a person and has no ask file says so once, names the file, and blocks all the same. The file and its pictures are removed once the item is answered, ticked or dropped, blocks again, or a new session starts on the task (`### Tasks waiting on a person` in docs/REFERENCE.md).
- Changed: a Needs you item on the run page (Home and Status) is one short card (F162): what is wanted and where in everyday words, the title, at most two lines of what to do, and Press for details. Pressing it opens a popup with the steps, what to see, notes, pictures, the agent's last words and the full task, and a reply box that goes with the answer. It replaces the More/Less fold. A task's `<notes>/asks/ID.json` can give the card and popup their own words, steps, expected list and pictures (`### Tasks waiting on a person` in docs/REFERENCE.md).
- Added: a run restarts on new code by itself (F149). With `[run] auto_upgrade` on (the default), a run from a source checkout restarts between merges once main's agent_runner code has held still for 10 min (at most 1 h after the first change), so one restart covers a batch. It keeps its slots and adopts its sessions. A run page never reloads by itself: a new version shows a popup, "A new version of this page is ready", with Refresh (which keeps what is typed) and Later.
- Changed: with `[run] auto_upgrade` off, nothing restarts a run by itself, not even on a newly installed version (before, any installed non-breaking version restarted it, e.g. after `uv tool upgrade`). `u`, `agent-runner upgrade` and Restart the run still restart it. Where a person must restart the run (auto_upgrade off, a breaking version, Windows), the popup says "A new version is ready. Restart the run to use it." Home's page says the same.
- Fixed: typing on a computer in a chat's session goes to the run page's message box while the agent CLI's prompt is hidden (B190). After a click in the session the keyboard was in the session's frame, so typed words landed in the agent CLI's own prompt, its normally hidden input showed, and Shift+Enter sent the first line alone (a terminal sends it as Enter). Now what is typed or pasted there goes to the message box (Shift+Enter a new line, the text kept whole). If the prompt already shows unsent words, Shift+Enter adds a new line in it. A menu or question still shows the whole window and gets every key. In the message box Enter still sends and Shift+Enter is still a new line.
- Fixed: text of several lines given to a plan change (Needs you answer, note, block, add or edit) is joined by a space in plan/TODO.md (B189). It was written with its newlines, so `run plan ID` and the brief showed only the first line and the agent lost the rest, and a later line that looked like a task line became a task. The task now stays one line and reads back whole; task lines already split are not repaired.
- Fixed: Talk's stop for a reply is the speaker button, not the mic (B174). The speaker is the one stop while a reply is read; the mic never stops it, and a press on it cuts the reply and listens at once. A reply that lands while the mic listens, or while another is read, plays after that, in order, and a sound that never ends is cleared by a check, so Talk no longer says "Speaking…" over silence.
- Added: devices (F169). The run app's Tools view adds the machines and test rigs agents reach over SSH or another way; a project says which it uses (Used here), and each one is a shared tool a task names in `needs:`. Secrets are write-only and kept on this machine (`### Devices` in docs/REFERENCE.md).
- Changed: Settings' Release by itself (Auto release) is two controls, Every (Off, 5, 10, 20 tasks) and When idle, so both can be on; changing one keeps the other, and with both on a count release and an idle one never queue two for the same landed work (F174).
- Changed: a setting saved for everyone is written to runner.toml at once (F173). It is committed alone on the shared branch and pushed as a plan edit is, and never queues a task. The Queued tag, the queued C task and its edit and drop are gone; a task Settings queued before still lands as a plain task.
- Fixed: a finished task that failed its test gate three times is no longer refused a fourth gate once it is fixed (B186). `done` keeps a hash of the worktree's content with each counted failed gate (uncommitted and untracked files count, ignored ones do not). After three failures, unchanged content is refused without a gate and changed content gets one more; a pass ticks and resets the count. Until that gate runs, `--blocked "CONFIRM: …"` is refused, so an agent no longer parks passing work as a false "CONFIRM: mark it done" Needs you item. The slot brief says CONFIRM is only for a check by hand the agent cannot do.
- Changed: no kept project chat (F176). The run opens no control session of its own and resumes none; `[run] control = true` now means it reopens the sessions a shutdown cut off (and, with `[run] remote`, keeps the control server up). Every prompt (the run app's Home box, a Status quick ask, Say what to change, a concept change, a typed Needs you reply, the runner feed) opens a new control session named for its ask, and numbers start at 2; an older c1 is a chat like any other. `agent-runner control` opens a blank one. The control server starts with `--no-create-session-in-dir`, so a stopped server keeps no session and each start gets a new environment.
- Fixed: a phone's Return key no longer sends a message (B181). On a touch phone or tablet Enter makes a new line in every message box, and only Send (or Ctrl/Cmd+Enter on a hardware keyboard) sends; a computer keeps Enter to send.
- Added: `[run] done_test` (F178). A command `done` runs before its commit in place of `test`, on a docs-only diff too (then `docs_check`, if set, runs as well): a build, an audit. A failing one ticks and commits nothing and counts as a failed gate; `--no-test` skips it. Merges still run `test` / `test_since`, so a passing done_test never lets a merge skip its gate (`refs/agent-runner/done-test/<ID>` marks it), and docs-only merges skip the gate as before.
- Added: a warning for a project with no settings file (F178). With no runner.toml, no AGENT_RUNNER_CONFIG file, and no gate or push_merge in runner.local.toml, the run picker and its launcher, the run page's Run card, Home's All projects and the TUI's Status panel say "no settings found, so no test gate and nothing is pushed". A run that is up says what it itself found.
- Fixed: a split task whose attempt was parked runs before its parts (B185). A session that filed parts (F2a, ...) and then failed left its attempt as wip/F2, and the run started F2a first, though F2a builds on F2's first part. Now the parked task goes first and its open subtasks wait until it lands. A `(split into ...)` task, one not parked, and a Stretch or Parked one keep the old order.
- Added: oversized tasks get split (F177). `[run] task_size` (10 by default, 0 = off) sets how big a task may be: its code files (files matching `docs_files` are not counted), plus 2 per numbered outcome, plus 1 per 400 characters of text (a long form is not read; concepts, releases and `(split into ...)` tasks never count as too big). `plan add`, `edit`, `note`, `approve` and `confirm` of a concept say when a task is over it and how to split it; control sessions split a big ask before queueing; the slot brief of such a task has the agent split it first and do only the first part. A task session past `[run] context_warn` is told once, as a turn ends (never mid-edit, not after its done), to commit what is solid, file the rest as a part and finish; nothing stops it if it goes on (both engines and the harness loop). Why 10: of iFizBox's last 383 tasks it flags 45, 39 of which peaked over 150k.
- Fixed: a command stopped for low memory no longer makes the agent ask the person (B184). Claude Code stops a background command when memory is low and says not to start it again unless asked, and an agent then asked. The slot brief now holds that stop as the person's standing go-ahead: the agent commits what is solid and runs `run wait-for memory`. Its slot is given up, its work is kept on waiting/<ID>, and the same session goes on with a message to run the command again once MemAvailable is 2 GB over `min_free_mem_gb` (a pause of a minute per stop). It needs no `[run.tools]` entry, shows on the queue row, `plan` and `status`, and is never a Needs you item. Under `min_free_mem_gb` no new session starts, and a slot's `done` gate waits for memory up to 10 min.
- Fixed: Pick links work through Runner Home (F167). With Home installed, a run listens on 127.0.0.1 only (F165),
  so no Pick link was made. Now a Pick link (`pick-links`, a pick sheet's Send) uses Home's Tailscale Serve https
  address, https://HOST/p/KEY/pick; Home routes GET /p/KEY/pick to the run with no Home token, because the link's
  one-use code is the check and the run checks it. With no run up, the link's page says to start the run. With no
  https address for Home's port, `pick-links` says so and gives the `tailscale serve` command. A run with its own
  https port still gets its Pick links as before where Home does not route it.
- Fixed: `run publish-page` and the run page copy and pitch pages now reach claude.ai (B180). They did not: the one-shot exited 0 with no URL. It had only `--tools Artifact`; Claude Code 2.1.330 then denies Read, and Artifact will not publish a file it may not read. It now has Artifact and Read, and a failed publish logs the end of its errors and answer, so a sign-in warning no longer hides the reason.
- Added: shared tools (F168). `[run.tools.<name>]` in runner.toml names something only one task can use at a time (a test phone, a device) with a `check` that says whether it is free, busy (and by whom) or missing. A task tags itself `needs:` (`plan add --needs`); the run never runs two tasks with the same tool, and holds a tagged task while it is busy or missing (at most 5 min when the check is unknown). An agent that finds its tool busy runs `run wait-for TOOL`: its session ends, its work is kept, and the same session resumes once the tool is free. Status, the TUI and the run page show the tool, and a missing one with tasks waiting is a Needs you item after 3 min. Without the setting nothing changes.
- Changed: Chat on a plan task, a concept or a setting, and Add a task open an empty new chat view at once, titled with what it is about; the session starts with the first message, and an unsent draft is kept per thing (F172).
- Changed: In Talk the chat fills the whole view and runs behind the top bar, the round buttons and the message
  box, which are see-through (solid under reduced transparency). The top bar slides off while the person scrolls
  up and returns on scrolling down or at the end, and the newest words stay clear of it at rest (F171).
- Changed: a chat or slot's real session shows its controls on the page (F170). The lines under Claude's prompt (the
  update notice, the status line, the mode, background shells and agents) lie past the frame's edge, and a chip row above
  the message box holds their controls: Working (Stop), the mode, shells, agents and Update (a sheet with the command,
  run on the run's machine). While Claude works the box has Force send, which interrupts and sends once Claude is at
  rest, beside Stop. `/` lists every command: the run's, Claude Code's, the project's, the person's and the chat's skills.
  Scrolling up hides the chips, box and top bar, with a thin strip that says Working. The session takes the run's own
  Claude Code theme, filled from the page's light or dark.
- Added: the run queues a file split by itself when free slots start nothing because 3 or more ready tasks wait for one file: one critical (alone) task splits that file and its test by area, with no behaviour change, then narrows the open tasks' files to match. Off with `[run] split_files = false` or Settings "Split busy files" (F200b).

## 0.62.0 (2026-11-23)

- Changed: the run app's Settings page is rebuilt (F166). About 24 everyday settings sit in Speed and limits, Landing work, Models and Chats, each with its control on its row; the rest are behind Advanced, and commands, paths, patterns and rules behind Project file, read only with "Ask a chat to change it". Each setting says where a change is saved: this device at once (`runner.local.toml`), or everyone as a queued C task on `runner.toml`, shown as Queued until it starts. A row's More… has the other home and Reset. Changed lists what differs from the default, and the lines the run ignores or moved. Search finds names, descriptions and code names, and a card with Restart the run says how many changes wait for a restart. `agent-runner settings` still prints the developer notes.
- Removed: the settings cut (F166). `[run] comment_policy` is ignored (write its wording in `prompt_extra`); `[run] merge_ahead` is always on; `[run] idle`, `stall`, `pause`, `fix_timeout`, `control_idle_quick`, `control_idle_talked` and `control_open` are fixed (30 s, 1200 s, 60 s, 1800 s, 5 min, 12 h, and the built-in phrases), and `run --idle`, `--stall` and `--pause` stay. `[run] model` and `fix_model` move to `[models] code` and `fix`. `[run] sessions` folds into `remote_slots`, now "open" or "always". An old file still works, and the run log has a note.
- Changed: a chat or slot in the run app shows the real Claude Code session through ttyd, filling the space above the message box, in place of the page's own thread (bubbles, folded steps, Older messages, the jump button). The message box keeps its send, attachments, mic, slash menu, drafts, Stop and outbox; a phone gets a touch layer and a key row (F114). Attach works on Windows 10 1809 and later (ConPTY, through a local port), and the `feed` terminal mode is gone.
- Changed: the terminal-style web page is removed (the /term route, `[ui] web`, the Terminal view / App view switch);
  the per-session terminal stays; an old `[ui] web` in runner.toml is ignored (C29).
- Changed: one address for every project (F165). With Runner Home installed, a run's page and its ttyd terminals
  listen on 127.0.0.1 only, on a free port that only Home opens; no link, log line or status names that port. A
  `[run] web_port` the person sets stays open on every interface, unless it is Home's own port. Without Home, the
  first run up keeps port 8770 and a second run listens on 127.0.0.1 only, its status and run log offering
  `agent-runner home install`. Installing Home while runs are up moves each run off the public port within seconds, with no
  restart; after `home uninstall`, a run serves its own page again from its next start. When Home is down while a
  run is up, `status` and the run log say so with the command to start it. On Windows a second run
  can no longer bind the same port as another run. Option links (`pick-links`) need a run page with a port of its own
  (`web_port` set): Home does not route them.
- Added: Home has a Talk button (F164), first in the row under the message box. One press opens Talk in the page,
  without a reload, and the mic does not start by itself. It shows always, as Talk does in the sidebar (where the mic
  cannot listen, Talk is typed).
- Changed: a reload of the run app opens what was open (B177): the view (Home, Talk, Status, Plan, Concepts, Settings
  or All projects) and the open chat or slot, kept per project and per browser tab, drawn in the first frame so Home
  does not flash. A reload never starts the mic or reads an old reply aloud. A link may name a view or a chat (`#plan`,
  `#c3`, `#s1`) and wins over what was kept. With storage blocked the page opens on Home.
- Fixed: Talk's sound over Bluetooth and a bad connection (B178). A reply is read in fewer clips, with silence
  playing between them so the Bluetooth route stays open; the audio session is set for the mic and for playback; a
  pause nobody asked for is undone once per reply. A clip with no answer is tried again twice, then the phone's voice
  reads the rest of that reply with a toast saying so. Toast errors are plain words, and the mic report also logs
  what happened to the sound.
- Fixed: the run app added to a phone's Home Screen stays one app when you switch project (B179). The project
  switcher, All projects, the project cards, Device Vitals and its Home link opened iOS's in-app browser, because
  without a manifest the app's scope was the folder it was added from. The cause was read from the code and not
  reproduced on an iPhone. Home and a run now serve a manifest and an icon behind the token, no-store; a concept's
  View opens inside the app, and links to other sites still open outside.
- Added: control sessions learn when an item they are about is settled elsewhere (F160). A chat about a task or a
  Needs you item (its title starts with the id, or it was opened from that item) gets one typed line from the run when
  someone else drops, changes, confirms, approves, shelves, restores or otherwise settles it. Sessions also re-read an
  item before they ask the person for it.
- Changed: control sessions leave blocked and Needs you items alone: not mentioned, listed, counted or asked
  about in answers, the opening summary or a status, unless they bear on what the person is discussing or the person
  asks ("what needs me?"). A status starts with its headline, with no "Needs you" line or group. A DECIDE line is only
  a question of the session's own about the work under discussion. No unasked pushes of existing items, except the
  needs-you watch of a run without the runner feed (F151).
- Changed: `agent-runner ui` always runs inside tmux. Before, it ran in any terminal and outside tmux its session
  tab showed the feed read-only (v for tool steps, Enter attached full-screen); now started outside tmux it re-execs
  itself in the project's tmux session (a new session named for the folder, or a window in it), and without tmux it
  refuses with exit 2 and the install line. On Windows it refuses (exit 2) and prints the run page's link. The feed
  pane and v are gone; a session with no socket says so with its link (F141).
- Changed: in `agent-runner ui`'s Sessions, n starts a new chat (a control session, without waiting for its link);
  N no longer does. Concepts' N, chat about it, is unchanged (F153).
- Added: run speech (F158). Talk reads replies with speech made on the run's own machine, played in one audio element
  that a tap on the speaker (or a play button, or a typed Send) unlocks, so later replies play by themselves. The default
  voice is Kokoro af_heart; Talk settings list every Kokoro voice, Piper en_US-lessac-medium (light) and the device's own.
  Install with `agent-runner speech install [kokoro|piper]`. With no engine installed, or when one fails, the browser's
  own speech reads as before. Text never leaves the machine.
- Added: approve to push (F98). With `[run] approve = true`, merges land but nothing is pushed until a person approves a
  pitch on Needs you (Approve, or Not this to undo).
- Added: New Talk chat (F157). In Talk the top bar's New chat button is now New Talk chat: it stays in Talk, stops
  listening, reading aloud or waiting for a reply, clears the shown conversation, and the next message opens a fresh
  Talk session; the old chat stays in Chats, open. Before, the button left Talk for an ordinary chat and Talk always
  went on in the live session. Elsewhere (sidebar, other views) New chat is unchanged.
- Changed: the run app reworked in one go, to written rules, `docs/STYLE.md` (F83, with F124, F143, F128, F129, F110,
  F97, B142, B134 and F85). Before and after:
  - Style: sizes, corners, colours and durations were one-offs; now tokens and shared helpers, checked by a test.
  - Motion: the drawer slid and little else moved; now the drawer, the sheet, new cards and messages, the mic and box,
    and state words move, 150 to 250 ms, transform and opacity only, none under reduced motion.
  - Scroll: a click or a refresh in a chat could jump to its end, and new cards pushed the page; now a refresh keeps the
    reading position in every view, a chat follows its newest message unless you scrolled up (a jump button), and a
    send goes to the end. A refresh also waits for a press or a text selection to end.
  - Views: Agents and Activity are one Status view in `agent-runner ui`'s order (needs you, run, usage, landed lately,
    release, log); the run's state shows as a pill on every page (F124).
  - Run controls: the card had slots, pause, force and stop; the rest was missing. Now the everyday ones are on the Run
    card and a More… sheet has every one, with its key: upgrade, restart, suspend, shut down, start, resume a cut-off
    task, release stale claims, moved-aside edits (W show, E restore, O O drop in the TUI). Upgrade, suspend and shut
    down ask first (in the TUI the key twice) (F124).
  - Drawer: the menu button only; now a swipe right from anywhere, following the finger, and left to close (F124).
  - Talk: a 132px mic over a chat box; now 64px mic and speaker with a keyboard button that swaps in the box, a play
    button on each reply, and Talk settings (read aloud, voice, tap or hold, auto listen) (F124).
  - Talk replies: a chat past 200 feed entries stayed on Thinking…; its reply is found by the entry's id (B134).
  - Needs you: Chat set a context on the Project chat; now it opens a new chat that shows the question and its answers
    (F143). No Drop on the page, and no confirm in the TUI; now Drop everywhere, confirmed first (D D in the TUI, D on
    the terminal-style page) (F110).
  - Chats: no sign of one that waits for you; now a dot on it, a dot on the phone's menu button while Home or Concepts
    has a count, and quiet chats gray at the bottom after `[ui] chat_quiet` (6h; false off) (F128).
  - Chat names: only the runner named a chat; now double-click (phone: ⋯, TUI: r) renames it, c1 too, through
    `agent-runner control --rename N NAME` (F129).
  - Settings: a text dump in the terminal; now a Settings view with this device's values and the project's (F97).
  - Queue: a title cut off; now a row folds open to the whole task (F85).
  - Esc in the message box interrupted only an open chat; now the session the page shows: c1 on Home, Talk's in Talk
    (B142).
- **Breaking: `[plan] release_alone` is gone (F130).** Tag the release `(alone)` instead (`plan add V --alone`, or
  `plan edit V7 --alone`; `--no-alone` clears it). Any task can now run alone the same way, so a major rewrite can stop
  other tasks starting beside it. A runner.toml still setting the key gets one warning in the run log and is otherwise
  ignored.
- **Breaking: the Pi backend is gone (F106d).** `[run] agent = "pi"` (any executable named pi, pi.cmd included),
  `[run] backend = "pi"` and `AGENT_RUNNER_BACKEND=pi` now fail at start. Write the model as `<provider>:<model>` in
  `[models]` instead, e.g. `code = "copilot:<model>"`: it runs on the harness loop, and `agent-runner login <provider>`
  (`run login`) adds the provider's login, kept in Pi's `auth.json`. `[run] agent` is now only the Claude Code
  executable (or a wrapper around it); `[run] backend = "claude"` is ignored with a warning, and any other
  `AGENT_RUNNER_BACKEND` value is ignored. `[run] agent = "copilot"` still fails, now pointing to `[models] code =
  "copilot:<model>"`. Also removed: the bundled `pi_hooks.ts` and `pi_idle.ts` extensions, the `.runner/pi-sessions`
  folder, the no-push git config Pi sessions got with `[git] push = false` (the git fence now holds every session),
  and Pi's resume after a failed model call.
- Removed: the terminal UI's chat. `agent-runner ui` has no Status chat tab, no Sessions chat, feed or pane tabs and no
  session message box, so nothing is typed into a session from it, and Ctrl+C always quits. Status tabs are log,
  release and controls (the quick asks s y w u are buttons on the log tab and keys in Status); Sessions tabs are
  session for a control session or an idle slot, and session and diff for a slot on a task; `c` selects c1 (F112).
- Added: `agent-runner ui` shows the real Claude Code session beside its panels. Selecting a session row (cN or sN)
  inside tmux splits a pane running `agent-runner attach cN` (sessions with an attach socket, Linux and macOS), which
  tmux keeps for mouse selection and copy; l, Enter or Ctrl-l focus it, Ctrl-h comes back. Outside tmux the session
  tab shows its feed read-only with its link (o open, y copy), and Enter attaches full-screen (F112).
- Added: Ctrl-f in `agent-runner ui` makes the session full-screen between the UI's top and bottom bars; Ctrl-f again
  puts it side by side. Inside tmux the UI binds Ctrl-f and Ctrl-h in tmux's root table, acting only in its own window
  and passing the key through elsewhere; a key the person already bound is left alone, and quit unbinds them (F112).
- Changed: N ('+ new chat') in `agent-runner ui` no longer blocks up to 90 s for the Remote Control link. It runs
  `agent-runner control --new --no-wait` on a thread, selects a 'c… starting...' row at once, and selects the cN row
  once the run's state lists it (F112).
- Added: `agent-runner control --new --no-wait` returns once the session starts, printing "control N is starting in a
  hidden terminal", without waiting for its claude.ai/code link (F112).
- Changed: offers from control sessions ("Want me to take it right away?") no longer go under Needs you. Only a question
  the session marks with a last `DECIDE: <question>` line is filed there, after `control_ask`; the brief asks for that
  line only when work waits on the answer. Any other quiet control session closes after the usual idle time, and the run
  log names the offer it did not file (F135).
- Changed: the run page (web) answers at once. New chat, a concept's New chat, the Concepts + form, Needs you buttons
  (answers and Later), concept option picks, quick asks, chat messages, Release and Unpark show their result
  immediately and are sent behind. New chat opens straight away as a "starting..." chat you can type into; it starts
  without waiting (`control --new --no-wait`), and what you wrote is sent once the chat is up. Run controls and the
  Talk view still send directly as before (F137).
- Added: the run page's Outbox, kept in the browser (localStorage), holds each such action until the run answers. A
  small pill shows "N sending" or "N failed · tap to see"; after a dropped connection or a reload, actions are sent
  again in order. Each action carries a client id and the run page runs an id only once (the last 500, in memory, so
  a restarted run page forgets them), so a resent New chat never starts two chats. If the run refuses an action it
  stays: a popup lists it with Retry and Discard (a failed message also has Edit, which puts the words back in its
  box), and a Needs you card comes back when its answer failed (F137).
- Fixes: the run page broke while a run was older than the page on disk (after an update, not restarted): Settings never
  loaded, and a Needs you card's Chat stayed in the Outbox as "Not sent: no such action: need_chat" (B164). Now a run
  serves the run app and the terminal-style page it started with until it restarts; a page that still meets an older
  run (unknown action or route) says "This run is older than this page. Restart it." with Restart the run (or
  stop and start it, where there is no restart control). Its Outbox item is kept and sent once the run restarts (a
  confirmed one, like a drop, waits for Retry), and a failed Settings read keeps the settings shown with Try again.
- Fixes: in the harness loop, the finish tool refuses until `done` or `done --blocked` has succeeded for the slot's
  task. It says to run `done`, or `run ask` when only the person can answer, and the session goes on. Before, a
  session could end with its task still open and nothing under Needs you (B155).
- Changed: the queued release shows as its own row on the run page and in the TUI, and `agent-runner status` says it as
  `release: …` instead of `last: V5 waits for everything before it`. With `[run] auto_release` on and no release queued,
  the row reads `Next release · auto at 10 landed: 6/10` (dimmed); a queued V shows `V5 Release · waits for 24 open ahead`,
  then `ready`, `blocked` or `building`. Once it lands, `lately` says `landed: Release 1.2.0 [V5]` and the count restarts
  at 0. J and K move no task past the release, and Enter on the dimmed row opens the release tab (F131).
- Fixes: `run finish`, run from a slot's agent on a `task/<ID>` branch, is refused until `done` or `done --blocked`
  has succeeded, even when the worktree has no uncommitted changes. The refusal says to run `done` or `run ask`. Before,
  B155 guarded only the harness loop's finish tool, so `run finish` typed through bash or in a Claude Code session could
  end the session with its task still open and nothing under Needs you (B156).
- Changed: with `[models] fallback` set, a new task whose model is claude's starts on the chain's first free provider
  when `[run] session_max` or `weekly_max` is reached (not forced), instead of waiting for the reset. A task with no free
  provider still waits, and STOPPED is raised only when such a task is all that could start. Nothing is written to
  capped.json; without a chain tasks are held as before. A session is now resumed only by the kind of agent (Claude Code
  or the harness loop) that ran it; an answered one whose task now runs on the other gets a new session (F142).
- Fixes: a new control session started from the run page or the terminal UI (Chat on a card, Add a task, quick asks,
  Take, Talk, an answer handed on while c1 is off) starts at once. It used to wait about 65 s (5 + 60) looking for its
  message in the runner feed's transcript, and then showed a false note about attached images. Its message stays on
  screen with a starting line until the reply, and any sent message stays until its own text is in the chat (kept over
  a reload); one that does not arrive shows Not delivered with Retry and Discard. A long turn no longer loses the
  person's latest prompt from the chat, and the chat says when older messages are cut off; a message sent mid-turn
  (queued) shows as the person's (B154).
- Fixes: Device Vitals' headroom said "No room for another agent: a usage cap is reached" past `[run] session_max` or
  `weekly_max`, though new tasks start down `[models] fallback` (F142). While a project whose run is up (with none up,
  any project) has a free provider in its chain (not claude, not capped, logged in), the usage cap now sets no limit and
  the line reads e.g. "Room for 6 more agents, on [models] fallback: a usage cap is reached". Memory, CPU and disk limits
  still hold; without a free provider it is as before (B157).
- Fixes: on an iPhone with the keyboard open, the run app's header went off the top and an empty band sat under the
  message box; now the app fits the space above the keyboard, in Talk, Home, Settings and the sheet too. Opening and
  closing the keyboard no longer shows a grey band or pushes the header away (seen on an iPhone 15 Pro, iOS 27), the strip behind Safari's bar has the view's colour, and the Outbox pill no longer
  covers a chat's text (B160).
- Fixes: Talk's mic on an iPhone could end at once with "Heard nothing (error: aborted)" (B162). Now only one speech
  recognizer runs at a time (a start waits for the old one's end, the box's dictation too); an abort before any words
  is retried once by itself, then Talk's status line says what to try in plain words, with the mic mode and the time
  to the error; a hold survives iOS taking the touch (pointercancel) and a redraw. The mic line says "Starting the
  mic…" until sound is really captured, then "Listening…"; the note carries the recognizer's own error message (on an
  iPhone 'aborted' stands for any failure, silence too, so the message tells them apart); a stop that never gets an end
  no longer leaves Talk listening for ever; a listen with no words shows a "Copy mic report" button: the events from
  press to end with times, words counted, not kept. The cause on the person's iPhone is still not proven.
  Hold to talk also heard nothing on an iPhone or iPad (the person's report: mic on 4 s, no words; the cause is not
  proven), so there Talk now works as Tap (tap to start, tap again to send); the mic line and Talk settings say so, the
  saved setting is kept, and other devices keep Hold.
- Fixes: run app on a phone: a vertical scroll could also open the sidebar drawer, and the page scrolled while the
  drawer followed the finger. Now each touch is one thing until the finger lifts: a touch that scrolled never becomes
  a drawer swipe, and during a drawer swipe nothing scrolls; a swipe must also be more nearly sideways (B167).
- Fixes: `run finish` said "`done` has not run" after a `done` that had passed, because a test suite of agent-runner's
  own gate, run in another slot, deleted the slot's finished mark: a run's start in a test cleared the mark of the
  folder it ran in. Now a run clears only its own project's marks; `run finish` also accepts a task whose tick is
  committed on its branch and tested at HEAD, and a `done` again on a ticked, committed task puts the mark back (B172).
- Added: the gate workflow (ci.yml) runs on request for a task branch before its merge (`gh workflow run ci.yml --ref task/<ID> -f
  system=windows`), so Windows-only code can be checked from a Linux slot; see docs/REFERENCE.md (T13).
- Added: `tools/windows_vm.sh` runs test files (default `tests/test_windows.py`) of a worktree, uncommitted changes
  included, on the Windows VM the machine already has, for contributors working on Windows code. It is a repo tool and
  not part of the installed package (T14).
- Changed: Runner Home's footprint walk (every 10 min) now removes ended sessions' temp folders itself and logs in
  Home's service log (the systemd journal) what it freed; before, only the Clean button did. A session has ended when no process names it, Claude
  Code's session registry (`sessions/<pid>.json` under `CLAUDE_CONFIG_DIR` or `~/.claude`) has it not open (pid alive
  with the same procStart), the runner will not resume or wake it (queued resume, unanswered ask, cut-off slot task,
  runner feed, c1's kept conversation, cN with a pid file), and nothing wrote to its folder for 1 h (runner worktrees)
  or 24 h (main checkouts, newly included, in Clean too). With an unreadable or missing registry no main-checkout
  folder goes; without /proc (macOS, Windows) none goes. Each is rechecked just before deletion, and symlinks are never
  followed out of the temp root. Worktrees and wip/ branches still wait for the person in Clean. The fixed 5 GB alert
  is gone: the alert comes when the temp folders left exceed 5% of the disk, names the size and the largest folder, and
  mentions Clean only when it has a temp folder to free; min_free_gb's alert is unchanged. Home's service now keeps
  `CLAUDE_CONFIG_DIR` from the installing shell: re-run `agent-runner home install` if you set it (F144).
- Fixes found by `ci.yml` on Linux and Windows: `agent-runner needs` no longer cuts an ask in the
  middle of a backticked command; a multi-line tell whose line ends are CRLF (as Windows pipes them) no longer doubles
  its newlines in a harness loop session; copying the run page link on Windows works when the clipboard tool is a
  .bat or .cmd (B150).
- Fixes: on Windows, `wizard` works with a default Git for Windows install (its installer puts only Git\cmd on PATH, so
  no bash was found): after PATH it looks for bin\bash.exe beside git, and with none it says in one line that Git Bash
  is missing instead of a traceback. System32's WSL bash is no longer used as a fallback (B159).
- Fixes: Runner Home restarts itself when agent-runner's package files change on disk (an upgrade, or a clone's pull,
  same version or not), once the change holds over two 5 s looks, and never while a request or terminal tunnel is
  open. Before, it kept the version it started with until the service restarted (B165).
- Fixes: on Windows Home restarts its scheduled task for the same reason; and Home run by pythonw.exe no longer
  stops at its start for want of a stdout (it crashed with AttributeError), its output goes to home.log. A Home older
  than this needs one sign out and in (or `home install`) to pick it up (F152).
- Added: on Windows 10 1809 and later, slots, c1 and other control sessions run in a ConPTY pseudo-console (stdlib
  `ctypes`, 200 by 50) instead of a hidden console. Their output goes to `.runner/slotN.log` and `controlN.log`, and
  `plan tell`, budget stops, a typed `/rename` and the run page's send and keys reach them. Before 1809 the hidden
  console stays; headless stream slots are unchanged. `attach sN`, `attach cN` and `attach N` do not attach to a ConPTY
  session yet (they print where the log is), and `agent-runner list` lists control sessions on Windows too (F145).
- Fixes: a person's messages to a control session that hit the usage limit were lost, since Claude Code answers such a
  message with only an error and never retries it. They are now held and typed into the session in one message once the
  limit is over; `status` says how many are waiting and when they go (B170).
- Fixes: a person's message to a control session was also lost when its reply had begun and the usage limit cut it
  off, and when the session was started from a Claude app (through the control server). Both are now held too. The
  runner cannot type into an app session, so once the limit is over it copies that conversation into a numbered
  control session and types the held messages in there, once; the app chat itself is left as it is. Messages of an app
  chat the person closed, or that were answered there meanwhile, are left alone (B173).
- Fixes: a repair session's `FLAKE:` line was split on spaces as well as commas, so one quoted test name was filed as
  several flaky-test tasks (four critical tasks for one flake). It is now split on commas only, a quoted or backticked
  name stays whole, and the repair prompt states the names format (B176).

## 0.61.0 (2026-11-23)

- Added: the run page (web) deletes chats. Each row in the Chats list has a trash button, shown on hover (always
  on touch screens); the Project chat (c1) has none. A click deletes at once, no confirm: the row dims and an Undo
  button takes the trash button's spot until the person clicks anything else or leaves the page, and only then is
  the delete sent. Ctrl/Cmd+click picks chats, Shift+click picks a range from the last one clicked; with 2 or more
  picked a "Delete N" bar shows, with the same Undo, and Esc drops the pick. Deleting ends the control session (its
  process, pid file and title go; the transcript stays, resumable), so it leaves the list and no run start reopens
  it. New ui_model action `delete_chats {names: [...]}` refuses a list naming c1, backed by
  `control.end_control(n, why)` (F118).
- Added: the TUI drops with `d` in every left panel that lists things, with the panel focused. Sessions [2]: on a
  slot working on a task it drops the task (as `D` did); on a control session cN (N>1) it closes it: its process,
  controlN.pid and controlN.title go, the transcript stays (resumable), and the run log says "control N: closed
  from the TUI"; on c1 it only says c1 is the run's kept session. Queue [3] drops the task, Needs you [4] drops the
  item (plan drop), Concepts [5] drops the concept; Status [1] has nothing to drop. `D` stays as an alias where it
  worked before (a slot's task, a queued task). The bottom hint line and the `?` keys list show `d` where it
  applies; in the main pane `d` is not a drop key (a pick's `d` option keeps it). New function
  `control.close_from_tui(n)` (F116).

## 0.60.0 (2026-11-23)

- Added: runner tools on Claude Code. `agent-runner finish "summary"` ends a slot's session at once after
  `done`, its summary in the run log. `agent-runner ask "question"` parks the task under Needs you (`DECIDE:`),
  its work kept on `asked/<ID>`; the person's answer resumes that same session with the answer as its next
  message. A git fence (a PreToolUse hook in every slot's `--settings`) denies `git push`, `git reset --hard`,
  `git clean`, `git checkout -- .` and edits in the main checkout or another slot; it replaces the no-push git
  config, which only Pi keeps (F102).
- Added: Device Vitals in Runner Home. Home lists Devices, one card per machine with a plain verdict ("Room for
  3 more agents", or its top problem) and CPU, GPU, RAM and disk meters; a card opens that machine's vitals:
  Headroom (the smallest of the memory, CPU-load, disk-above-`min_free_gb` and usage-cap limits, at most 6, with
  a + slot button), Machine (CPU, GPU, memory, disk and temperatures, each with a 24 h sparkline from samples
  Home takes every 30 s and keeps for a day, about 300 KB), Runner footprint (worktrees, session temp folders,
  logs, `wip/` branches, each sized) with a Clean that lists what it removes first and only removes ended
  sessions' temp folders, worktrees merged into the main branch (run off, nothing uncommitted) and the `wip/`
  branches you tick, Sessions (CPU and memory per slot and control session), and More for per-core, every
  sensor, top processes and the largest folders. Disk under `min_free_gb`, a CPU or GPU at 90 °C, memory nearly
  full and session temp folders over 5 GB show under Needs you on Home and go to each running project's runner
  feed, which pushes them. Homes find each other through `agent-runner home peer add LINK` (`peer remove`,
  `peers`) or Tailscale (a tailnet machine whose Home takes this Home's token), so one Home shows every device.
  Read with the standard library; what a machine cannot read is hidden, never shown as zero (F95).
- Added: Runner Home. `agent-runner home install` sets up an always-on per-user service (systemd `--user` with
  linger on Linux, launchd on macOS, a scheduled task on Windows) that serves one token-gated page on port 8770
  listing every project (folders in `~/repos` with a `runner.toml`, plus `home add PATH`): running, idle or
  off, what needs you, and Start run, Pause, ±1 slot and Stop. Open routes to the project's run app through
  Home, so one link reaches every run. Install prints the link and a QR code; `home status`, `home list`,
  `home remove PATH` and `home uninstall` go with it. Off until installed. With Home installed, a run that finds
  its page port taken serves its page on a free port, which Home opens; without Home nothing changes (F94).
- **Breaking: a run on 0.59 or older cannot adopt across 0.60.0** (its sessions are in tmux panes this version
  no longer reads), so stop the old run (`agent-runner stop`) before upgrading; it neither auto-upgrades nor
  restarts itself onto 0.60+ (C28).
- 0.60.0 replaces the 1.0.0 tag published earlier the same day, and the v1.0.0 tag and GitHub release
  have been deleted (v0.60.0 is the Latest release). A run already installed at 1.0.0 must be reinstalled
  (`uv tool install --force` or re-pull) to get 0.60.0 and later, since it sees them as older (F119).
- Changed: a release (kind V) no longer runs alone. It still waits for what is ahead of it (`after: all`, or
  its own `--after`) to land, then starts even with other tasks running, and tasks start beside it. While it
  is busy the merge holds every other merge and push, so it releases exactly what was on main when it
  started; the run log and the dry run say why (`T5: waits to merge: V10 is releasing`). `[plan]
  release_alone = true` keeps the old behaviour (nothing beside it) (F99, F100).
- Breaking: tmux is gone. Every OS runs the hidden way, as Windows already did: each slot, c1 and every other
  control session, and the runner feed run in a terminal with no window (a pty shim; Windows: a hidden
  console). Bare `agent-runner` starts the run as a detached process (no `ar-<repo>` tmux session, no
  default-command panes), and `agent-runner run 3` runs in the foreground of its terminal. `[run] mux` and
  `run --mux` are removed: a leftover `mux` key is ignored with one warning line (C26).
- `agent-runner attach` (and `attach run`) is the run view: the run's log, followed live, and the runner keys
  typed there (`s`, `s!`, `p`, `f`, `+`, `-`, `slots N`, `z`, `x`, `u`, `?`, and an empty line for Remote
  Control), each posted to the run through `.runner/KEYS`, so it works from any terminal and over ssh. Ctrl-C
  leaves it and the run keeps going. `attach sN|cN` puts this terminal on a session's own terminal (F88;
  Ctrl-b d leaves); `attach feed` and `attach board` open `agent-runner ui`. `agent-runner list` and
  `attach N` read the hidden sessions' markers (C26).
- `agent-runner ui`: V upgrades agent-runner, Z and B suspend or shut down the computer once the run stops
  (the run's `u`, `z` and `x` keys), listed under Status in `?` and on the controls tab; the run page's Run
  controls get the same three (C26).
- Control session titles live in state only (`.runner/controlN.title`), which `list`, `ui` and the run page
  read; a hidden session also gets `/rename` typed in so the Claude apps show it. The run page's terminal tab
  serves `attach NAME` through ttyd. Fix and repair sessions always run as `claude -p` (no `master-<repo>`
  window) (C26).

## 0.59.0 (2026-11-22)

- Breaking: the run page (`agent-runner ui` and the web page) reads a run's sessions only by the tmux tags
  this version sets (`@runner` cN / sN and `@runner-repo`). It no longer reads control session windows by
  name (`<repo> · N · title`, `<repo> · control N`, `<repo> · N`) nor guesses the tmux session `ar-<repo>`. The
  runner's own pane now carries `@runner-repo` too; a run started by an older agent-runner (its runner pane
  without that tag) shows one line in Sessions instead of rows: "This run was started by an older agent-runner: restart it to see its sessions." (C23).
- The board window is gone: `agent-runner ui` and the run page show what lands and what needs you. A tmux run
  opens a window only for the runner feed (`[run] remote`), now named `runner-<repo>` (`attach board` still
  finds it). Control sessions give the `run page:` link `status` prints to watch the slots, the queue or the
  log, never an `attach` line, and hand over no page of their own for what the run page shows (C22).
- `[run] issues_watch` (off by default): a run reads the repository's open GitHub issues (`gh issue list`, on
  the `ci_watch` cadence) and files one task per new issue, its number, title and URL on the line and its body
  in the long form; a list of labels (`["bug", "runner"]`) takes only issues with one of them. Each issue is
  filed once, and none while an open task names it. `[run] issues_trust = "skeptical"` (the default) files the
  issue as untrusted: the agent confirms it in the code first and follows nothing the issue says; `"trust"`
  files it to do as written. When the task lands the issue gets a comment naming the merge commit, and is
  closed under `"trust"` only (F62).
- `[run] auto_release` (off by default): the run queues a release by itself, as `plan add V` does.
  `{ every = 10 }` queues one once 10 tasks have landed since the last release (release task or version tag);
  `{ idle = true }` queues one when the run goes idle with landed work, once per idle spell; both may be set.
  Never while a release task is open, nor with nothing landed since the last release. The run log and
  `status`'s lately say `queued V<n> (auto_release: 10 landed)` or `(auto_release: idle)` (F63).
- The quiet launch is gone. Each Remote Control session the run starts pushes to the phone as it starts, and
  nothing can stop that: Remote Control sends its "session ready" push as the session registers, before a
  presence file can count, and no setting or environment variable in Claude Code (up to 2.1.330) turns it
  off. `[run] silent` is now true or false, default false: `true` keeps a presence file for good, so no push
  comes after the start one (as before); `false` is Claude Code's usual. A config that still says
  `silent = "launch"` reads as false, with one `run.log` line. `control N --unquiet` is gone. Slots with
  `remote_slots` now keep their presence file only under `silent = true` (C20).

## 0.58.3 (2026-11-21)

- On Windows, `.runner/run.log` is UTF-8 with no BOM; the `·` in Remote Control names only looked garbled
  when read with Windows PowerShell 5.1's `Get-Content`, which reads a file with no BOM as cp1252. Read it
  with `agent-runner status -n 20` or `Get-Content -Encoding UTF8`. A test now checks the log's encoding
  (B100).

## 0.58.2 (2026-11-21)

- Control sessions in a wrapped repo name `[run] command` (e.g. openmx's `./kit`) in their brief, as the
  runner feed does since B92 (B93).
- New panes in the background tmux session (`ar-<repo>`) open the control session again: its default-command
  and environment target `=sess:`, since tmux 3.8 rejects a bare `=sess` and new panes opened a plain shell
  (B94).
- An inline concept page is updated, not queued, when a reply praises it but asks a question or a change; only
  a plain go ("build it", "queue it", "go with B") queues the build (B95).
- A handed-on ask (`control --new --ask`, from the runner feed) that gets number 1 starts a fresh session
  under its given name instead of resuming c1's kept session (B96).
- `upgrade` picks how to update by agent-runner's own install, not `sys.prefix`: a clone pulls, pipx upgrades
  with pipx, any other install with `uv tool`. A wrapper running system python3 with uv's packages no longer
  runs `git pull` in site-packages (B97).
- The control brief stays under 9,500 characters (Claude Code showed only a 2KB preview of the 21.8KB brief):
  the core rules are inline and the long ones behind `guide <topic>` (summary, output, queue, watch, settings,
  glossary, voice); a long voice file is pointed at (B98).
- `plan add V` skips the duplicate check, so a release whose text names the work it waits for adds without
  `--force` (B99).

## 0.58.1 (2026-11-21)

- The runner feed in a wrapped repo names `[run] command` (e.g. openmx's `./kit`) in its prompt and hints, and
  allows both that command and the runner itself, so it can hand an ask to a control session. Before, it named
  the bare runner, which skipped the wrapper's settings, and refused the wrapper's own command (B92).

## 0.58.0 (2026-11-21)

- Fewer settings (C14, from the R7 audit). An old runner.toml or runner.local.toml still works: each old key
  is logged at the run's start with what to write instead, and a renamed one still applies under its new name.
  - `[run] backend` is gone: the backend follows `agent` (an executable named `pi` runs on Pi) and
    `AGENT_RUNNER_BACKEND=claude|pi`. An old `backend = "pi"` is read as `agent = "pi"` (beside a wrapper not
    named pi it still runs on Pi); write `agent = "pi"`, or set `AGENT_RUNNER_BACKEND=pi` for a wrapper.
  - `[run] batch` is folded into `batch_max`: `batch_max = 1` is no batching. An old `batch = false` is read
    as `batch_max = 1`; past `max_unmerged`, that holds one slot free per extra waiting task (the half-batch
    step is 1).
  - Every slot gets `AGENT_SLOT=<n>`, and `[run] slot_env` (now `[]` by default) only adds to it. Before,
    setting `slot_env` dropped `AGENT_SLOT` unless it was repeated.
  - `[run] control_close` is folded into `control_idle`: `control_idle = false` closes no idle control session.
    An old `control_close = false` is read as `control_idle = false`.
  - `[run] control_ask_idle`, `control_file_asks` and `control_ask_kind` become one `control_ask = "2h"`:
    false keeps a session waiting on its open question open (nothing filed). An old `control_ask_idle` is
    read as `control_ask`; an open question is always filed (as an F task) before its session closes.
  - The `[needs]` table is gone: its heading is always "Needs you" and each item shows its age; its order is
    `[run] needs_order`. An old `[needs] order` is read as `[run] needs_order`.
  - `[run] flaky_kind` (T), `ci_kind` (B) and `control_ask_kind` (F) are constants.
  - `[run] timeout` is renamed `command_timeout` (it covers the gate, a retest, hook commands and `done`'s
    gate); an old `timeout` is read as `command_timeout`.
  - `agent-runner settings` comments no longer start with a task id (`B26:`, `F17:`, …).
- A run with no test gate (`[run] test` empty) says so: the run's start, `run --dry-run` and `status` show
  "WARNING no test gate ([run] test is empty): merges go to main untested", and its merges stay local unless
  the config sets `[git] push_merge` itself; each merge logs the `git push` to publish it. Before, it merged
  and pushed untested work without a word (B36).
- A hand plan edit in the main checkout no longer pushes the shared branch when merges stay local (no test
  gate and `[git] push_merge` not set, or `push_merge = false`): it warns "merges stay local, and this edit
  with them" and names the `git push` to publish them. Before, it published the untested merges a run had
  kept local (B86).
- `agent-runner cost --files` names what to split or stop re-reading: each file read (a Read, or what `cat`,
  `sed`, `grep`, … printed) by its results' tokens times the turns they stayed in context, with its
  re-reads, then the tokens exact-repeat commands added after their first run. In 20 slot sessions,
  `runner.py` held 25% of file-read tokens and 95 of its 110 reads were re-reads (F26).
- Two slots that file the same follow-up no longer give two tasks: before a merge, each task the branch added
  is held against the open tasks the target branch got since the branch forked (`plan add`'s same likeness
  check), and on a strong match it goes into that task as a note ("N2 filed the same as Y2 (folded at the
  merge): …"), logged as "folded Y2 into Y1"; lines the branch wrote that name it name the kept one. Before,
  `plan add` in a slot saw only that branch's plan, and two sessions did the same work (B33).
- c1 no longer grows until it compacts: when a person starts a new run and c1's kept session last stood over
  `[run] context_warn` (150k by default), c1 starts a fresh session and its opening summary says so in one
  line; 4 of 32 control sessions had passed 150k. A restart keeps the session whatever its size: the
  self-restart on an upgrade, a run within 6 hours of a crash, kill or Ctrl-C, and a run started within 5
  minutes of the last one ending (F27).
- A slot session whose context grew too big says so: past `[run] context_warn` (150k tokens by default, 0
  off), its exit line and `since` add e.g. `B32 peaked 168k (over 150k): runner.py 61k, test_runner.py 22k`,
  the files (or kinds of call) whose results filled it most. 10 of 51 slot sessions in two weeks passed 100k
  unseen. Soft only: nothing is stopped; the fix is a smaller task or a split file (F25).
- A hidden run on Linux and macOS (no tmux, or started outside a tmux session) now has control sessions: c1
  starts with it, and `control --new` no longer fails with "no tmux session", each in a terminal with no
  window through the hidden slots' shim, its output in `.runner/control<N>.log` (with `[run] remote`,
  `control --new` still prints its claude.ai/code link). A hidden run has no board window, so its control
  sessions keep their own needs-you watch instead of counting on a runner feed that is not there (F59).
- `status`'s `merged N in the last 24h` counts tasks, not merge commits: a task that fast-forwards (the
  first task of a fresh repo, or any whose branch main had not moved past) now counts, and a task that left
  two merge commits, or merged twice, counts once. It reads the run log's landed tasks, and with no run log
  the task ids heading the main branch's commit subjects (B78).
- When Claude Code changes something agent-runner reads from its internals, you are told instead of things
  going quiet: a transcript with none of the entry types it knows, a Remote Control pane that shows no
  claude.ai/code link in time, or `remoteDialogSeen` gone from `~/.claude.json` each give one needs-you line
  per Claude Code version, `<project> needs you: Claude Code X changed Y; Z no longer works`, in the runner
  feed and the control sessions' watch. Local only: nothing is filed (B45).
- A style for the future too: approve a concept's style and say it holds from now on, and the control session
  shows a restyle page (each current page or screen that changes, before and after) and runs `plan restyle
  "<style>" --page <url>`. Every queued task that touches the interface is held on it, kept; a running one is
  told to stop at a clean point, commit and write its journal, and is parked as `wip/<ID>` (one already in its
  test gate or merging lands, listed on the page). Approving the restyle reopens them all with the style in
  their note. `--dry` lists what it would hold, park and let land (F19).
- Your wording sticks: a voice file you shape by talking. "say X not Y", "shorter", "no ids" or "stop calling
  it Z" makes a control session add one line (`agent-runner voice add`, naming the file it went to); when you
  ask "what?" or rephrase what it said, it says it again plainly and offers one line to add, added only on
  yes (`[run] voice_learn = "off"` stops the offers). The global file is `~/.config/agent-runner/voice.md`
  (`[run] voice` moves it); a `.runner/voice.md` with lines overrides it for one project (`voice add
  --project` starts it as a copy of the global lines). Every control session's brief, the runner feed's
  system prompt and the task agents' brief (for the commit messages status and since show) carry it. "show
  my wording" is `voice show`, "forget X" is `voice forget X`, which removes one line and lists the matches
  when several hold X (F21).
- Needs you lines name their project, so a person who runs several knows which control session to answer in:
  status and since head the list `iFizBox needs you:`, `since --follow --needs-you` prints `iFizBox needs you:
  … [R43]` (`iFizBox: looks stuck: …` for the others), and a held run's desktop notice says `iFizBox needs
  you: run stopped: …`. Answers stay in their own project: `plan confirm|change|shelve` with an id only another
  project has says `nothing needs you here about 'R43' in <project>` and changes nothing (F33).

## 0.57.0 (2026-11-20)

- A release kind, `V`. `plan add V` files a release at the end of Next that waits for everything ahead of it
  (`after: all`, no `--after` needed), with the default release brief when given no text (bump the version,
  move CHANGELOG Unreleased under it, commit to main, check the release workflow and `gh release view`). It
  runs alone: the run starts it only once no other task runs or waits to merge, and starts nothing beside it,
  so it releases exactly what landed. `plan add V --now` (or `--pri critical`) files an interim release that
  does not wait. A release is never refused as a duplicate of another one (F38).
- Research tasks merge only their findings. A task whose kind means research (`R`, or a repo's own `[plan]
  kinds` entry that starts "research") lands when its diff changes only the plan directory, the journal or
  the new `[run] findings` globs (default `docs/research/**`, `research/**`). One that touches code is parked
  and blocks with `DECIDE:` naming the code files: answer `follow-up` or `merge anyway`. Its brief says to
  write findings, queue follow-ups with `plan add` and change no code (F36).

## 0.56.0 (2026-11-20)

- No more stray `%9/.runner/run.log` folders in the repo (or `tests/`). A control test stubbed every
  `subprocess.run` with a tmux pane id, git's answer included, so `log()` took "%9" for the main checkout and
  made it in the current directory. `toplevel` and `main_checkout` now take git's answer only when it is an
  absolute, existing directory (`toplevel` stops with an error, `main_checkout` falls back to the checkout),
  and the test stubs answer only tmux (B52).
- `--after all`: a task that waits for everything queued ahead of it, worked out live, so a release needs no
  wait list kept up by hand. `plan add`, `plan edit` and `plan block` take it, for any kind of task; the task
  starts once no open or blocked task above it in TODO.md remains, in any section, tasks queued above it later
  included. Parked (`--pri later`) and Stretch tasks and shelved ones don't hold it. `status`, `plan ID`,
  `plan reopen` and `plan waiting` show `T5 waits for everything before it (N open)` instead of an id list
  (F35).
- One hidden slot mode for every OS, tmux optional. A hidden slot runs in a terminal with no window: on Linux
  and macOS a pseudo-terminal from Python's standard library (`pty`), its output in `.runner/slotN.log` and
  `plan tell` typed into it through `.runner/slotN.in`; on Windows a console of its own whose window starts
  hidden. Each runs through a detached `run --slot-shim`, so a restarted run adopts it, and lands through the
  same worktree, `done`, gate and merge as a tmux slot. You watch it through `status`, control sessions and,
  with `[run] remote_slots`, Remote Control. `[run] mux` / `--mux` is `tmux` or `hidden`; the default is tmux
  inside a tmux session, else hidden, so a run without tmux (or outside a tmux session) is hidden, not an
  error, and bare `agent-runner` without tmux starts the run as a detached process. **Breaking:** the
  sequential run (`--no-tmux`, `mux = "none"`, the no-tmux fallback that committed in your checkout with no
  worktree and no merge gate), Windows Terminal tabs (`wt`) and visible console windows (`console`) are gone;
  `--no-tmux` is refused, and `wt`, `console` and `none` in `[run] mux` run hidden. `remote_slots` stays off
  by default and is now marked not recommended (every slot start pushes to the phone) (F40).
- Control sessions grill before queueing (after mattpocock/skills grilling, domain-modeling and to-tickets, MIT):
  on "grill me", "poke holes" or "stress-test it" they ask rounds of numbered questions, each with its
  recommended answer and worded so yes accepts it, look facts up themselves instead of asking, take one reply per
  round (`yes`, or `1b 2a` as on a pick sheet), and stop when nothing is left open. Settled words go to the
  glossary, an ADR is offered only for a hard-to-reverse trade-off, and the task's text carries the answers; an
  ask that becomes several tasks is shown as a numbered breakdown of vertical slices (prefactor first, ordered
  with `--after`) and queued on one yes. `agent-runner guide grill` holds the how. New `[run] grill`: `ask` (the
  default, only when asked), `big` (also before queueing a big or vague feature ask) or `off`. GLOSSARY.md gains
  same work and sweep (F20).
- Every repo the runner works keeps a GLOSSARY.md: each entry names one thing as the person says it, as the app
  shows it and as the code calls it, with a plain definition and the words to avoid. New command `agent-runner
  glossary [TERM]` (`show`, `add`, `forget`, `seed FILE`, `scan [WORD]`) writes it and commits itself in the
  main checkout, as plan commands do; a repo with none gets one on the first add. The first control session in a
  repo without one seeds 10-20 terms from the app's UI strings and code names straight away; control sessions
  add a term the person uses without asking and mention it in passing, offer a rename when the person, screen
  and code use three words for one thing, re-say things in glossary terms on "what?", and offer an ADR only for
  a hard-to-reverse, surprising trade-off. Slot prompts say to name new things with its terms and add new ones.
  `[plan] glossary` names the file; `false` turns it off (F22).
- Run events are structured: `log()` takes an event kind and task id, and each line with one is also a record
  `{time, kind, id, text}` (plus its fields: `why`, `left`, `slots`) in `<notes>/events.jsonl`. `since`,
  `since --follow` (and so the runner feed and its phone pushes), `status`'s "lately", the stop countdown and
  the background launch's wait for the run read those fields instead of matching run.log's prose, so
  rewording a log message changes nothing they print. run.log stays the plain log a person reads; its lines
  from before events.jsonl existed are still read for since and status. The runner's pane colours a line by
  its kind (F41).
- GLOSSARY.md (after mattpocock/skills domain-modeling, MIT) names agent-runner's own words once each: run,
  slot, task, kind, control session, c1, runner feed, board, take, gate, fixer, merge worktree, concept, Needs
  you (CONFIRM, DECIDE, BLOCKED), shelve, claim, notes dir, remote; each with a plain definition and the words
  to avoid. The slot prompt and the control brief now say in one line to use a repo's GLOSSARY.md terms when it
  has one (any project the runner works), and the control brief says c1, not "control 1" (D1).
- Docs-only changes skip the slow test gate, decided by the diff, not the task's letter: a merge (or `done`)
  whose files all match the new `[run] docs_files` (default `*.md`, `docs/**`) runs only `[run] docs_check`
  (a link/anchor check, if set) and logs `docs only, gate skipped`; a mixed diff runs the gate as before. A
  take or slot task that only edits docs or the plan no longer needs a hand-typed `--no-test` (F37).
- `[run] auto_upgrade` defaults to true: a run upgrades agent-runner by itself when a newer release is out
  (once no merge runs, never across a major version, nor on Windows) and restarts on it. Set
  `auto_upgrade = false` to upgrade only with `u` or `agent-runner upgrade`. `run --upgrade` is gone: `u`,
  `agent-runner upgrade` and the auto upgrade cover it (C6).
- The control brief and the agent-runner skill (GUIDE) are rewritten after mattpocock/skills
  writing-for-agents (MIT): the control brief is 3,886 words down to 2,794, GUIDE 1,333 down to 1,011 (what
  every session loads; the three topic pages below, 1,036 words in all, load only when their case comes up).
  What only one branch needs moved behind a pointer: `agent-runner guide take` (doing a task here, now), `guide
  concepts` (show options inline, approve or revise a queued concept) and `guide needs` (answering what needs
  the person: confirm/change/shelve, wizards, pick sheets) print it, and GUIDE and the control brief say when
  to read each. Prohibitions now come with the positive target ("keep the main checkout clean", "start it
  only when asked"), restatements of `--help` (plan subcommands, stop/pause flags) are gone, and the summary
  steps are numbered once. The slot prompt and the merge fixer and repair prompts state the same rules as
  what to do. Every behaviour is kept; the tests now check the moved rules in their topic pages (C2).

## 0.55.0 (2026-11-20)

- `agent_runner/runner.py` (9,100 lines) is split by responsibility into thirteen modules, each under 1,500
  lines and importing only those below it: `state`, `brief`, `sched`, `slots`, `watch`, `join`, `land`,
  `merge`, `control`, `status`, `feed`, `loop`, `cmds` (runner.py's docstring lists what each holds). Code
  moved, behaviour unchanged: `runner` re-exports every name, and `runner.X = v` still reaches every module
  that uses X. Open tasks that named runner.py now name the modules they touch, so they can run side by
  side (C3).

- Idle control sessions close at two more speeds: one the runner opened for a single ask (a reply from the
  feed) that ended with a task queued, no open question and no second message from the person closes after
  `[run] control_idle_quick` (5 min); one the person sent a second message in stays `[run]
  control_idle_talked` (12 h). Everything else keeps `control_idle`; false turns a
  tier off, and c1 is still never closed. The runner's `/rename` and hook or system turns no longer count as
  the person speaking last (F56).

- Control sessions push what the person asked to hear: "notify me when" on the session's own background
  work (a subagent or `take` it started) now ends in a PushNotification when that work reports, not just a
  line in the conversation; finished or stuck takes and anything that needs the person are pushed unasked
  while they are away, and a session that cannot push says so instead of promising to (B81).
- `agent-runner settings` prints every runner.toml key with its default and what it does, generated from
  the runner's own defaults (and their comments), with where to set it (runner.toml vs runner.local.toml),
  how (a runner.toml change through `take`, never in the main checkout) and when it applies (the next run).
  The skill (`guide`) and the control brief point at it and recommend a change in one line,
  `[table] key = value`, when what the person says fits a real key (too many control sessions:
  `control_idle`; fewer agents: `slots`; no phone pushes: `silent`), and make it on yes (B28).

- Slots verify before asking: the slot brief tells agents to try `~/.claude/ACCESS.md` and the `## Tools`
  section of the repo's CLAUDE.md (ssh hosts, preview servers, headless checks) before turning a check into
  an F task for a person. `agent-runner setup` adds an empty `## Tools` heading to CLAUDE.md
  when it has none (B80).

- A session opened by hand in a runner repo where no run has started yet (a fresh repo in the desktop app)
  gets the control brief too: any agent-runner command adds, once, a SessionStart hook
  (`control --brief --user`) to Claude Code's user settings (`~/.claude/settings.json`). It prints the brief
  only in the main checkout of a repo with `runner.toml`, `plan/TODO.md` or `.runner`, and nothing in a slot
  worktree, a control session the runner started, a repo whose own F53 hook prints it, or anywhere else;
  it is quick and silent on any error. `[run] install_skill = false` turns it off with the skill (B79).

- `[run] control_idle` defaults to 3h (was 1h): idle control sessions 2, 3, … close after 3 hours quiet;
  `control_ask_idle` stays 2h (T11).

- `plan edit ID "TEXT"` corrects a task in place: TEXT replaces its whole description, appended notes included,
  so a corrected instruction no longer sits after the stale one; the id, checkbox, BLOCKED text, follow-up tag
  and `| files:`/`after:`/… fields stay. `--files`, `--after`, `--test`, `--journal` change those fields, and
  `--pri` retags the task and moves it where `add` files that level. It commits as `plan: edit ID`, goes back
  in the pool like a noted task, and a slot running it is told "Your task changed" as on `plan change`.
  Control sessions use it to correct a task and `plan note` only for extra detail (F45).

- `agent-runner --help` puts what a person types first (start, attach, control, status, since, pause, stop,
  slots, wizard, guide, plan) and the rest under "Mostly for agents (you can run these too)", one short line
  each. Bare `agent-runner wizard` runs the one waiting wizard, lists them when several wait, or says there
  are none (F48).
- `agent-runner setup` makes the repo in this folder ready for a run: it commits any uncommitted work to a
  backup branch `runner-setup-backup-<date>` (your checkout stays as it was) and says its name, writes
  `runner.toml` if missing with a guessed gate, and starts one full Claude session that reads the repo and
  writes the goal and a first task list through `plan goal` / `plan add`, the gate and a short notes section
  in CLAUDE.md or AGENTS.md. It ends with what it set up and `agent-runner` to start. On a repo with a plan it
  asks first (`--yes` skips the question). It heads the person section of `--help` (F49).
- Choices come as a pick sheet. An agent that blocks with `DECIDE:` on options writes them as plain questions
  with 2-3 answers each (no option numbers) to `.runner/sheets/<ID>.json`, renders the page with
  `agent-runner sheet <ID> --html FILE` and publishes it: questions grouped by kind of change, answer buttons
  with the recommended one preselected and labelled, a collapsible Why, and a sticky bar with "N changes
  picked", Recommended and Send. Needs you, the feed and the control brief show one line, "<what is ready>.
  Pick on the sheet or reply go", with the sheet's link. Send gives a reply line (`R7 picks: backend=a …`);
  pasted in the chat, the session runs `agent-runner sheet R7 --picks "…"`, and "go" runs `sheet R7 --go`
  (the recommended set). Either reopens the task with each answer spelled out in its note. `[run]
  questionnaires = false` turns it off (F18).

## 0.54.0 (2026-11-20)

- A session you open by hand in a runner repo (the Claude desktop app, a terminal, an IDE) is a control
  session too: at run start the runner adds a SessionStart hook (`control --brief --hand`) to the main
  checkout's `.claude/settings.local.json`, per machine and never committed, so slot worktrees never get it.
  Control sessions the runner starts already have the brief from `--settings` and skip this one (F53).
- Releases reach your phone: when a merge brings a release onto main (a newer version heading at the top of
  CHANGELOG.md, or a new version tag), the run logs `<repo> X.Y.Z released: <first changelog line>`,
  `since --follow` prints it, and the runner feed sends it with PushNotification. Control sessions take
  "notify me when X" ("ping me when B56 merges", "tell me when the run is idle"): they say what they will
  watch for, watch `since --follow` (or poll `status`) with Monitor, push once when it happens, and stop (F51).

## 0.53.2 (2026-11-20)

- Windows: no more visible `...\Scripts\python.exe` console for the background run, the Stop hook's timer or
  `attach`'s helper. They started with `DETACHED_PROCESS`, and uv's `python.exe` launcher then gave the
  real python a new, visible console; they now start with `CREATE_NO_WINDOW` (B64).

## 0.53.1 (2026-11-20)

- `s!` (`stop --force`) on a session that never began (held at a dialog, so no transcript) no longer queues
  it to resume: `claude --resume` found no session and the slot sat there. The task starts afresh (B63).

## 0.53.0 (2026-11-20)

- Windows: slots no longer hang in their hidden console on Claude Code's "Do you trust this folder?" dialog.
  The runner wrote the trust to `~/.claude.json` under `C:\Users\...`, but Claude keys folders
  `C:/Users/...`, so it never saw it (B61).
- The runner deletes its own `wip/<ID>` and `wip/<ID>-N` branches, here and on `[git] push`, once the task
  is ticked or dropped (F23): after the merge that ticks it, on a `plan drop` of a running task, at the start
  of a run and every 10 minutes for tasks ticked or dropped by hand. An open or blocked task's wip stays.
  `wip/main-checkout-*` (a person's uncommitted edits) is never deleted: each is listed under Needs you in
  `status` and `since` with its age and file count, and the new `agent-runner wip [show|restore|drop NAME]`
  lists, shows, restores it into a `take` worktree (`wip restore NAME ID`, uncommitted) or deletes it here
  and on the remote.

## 0.52.0 (2026-11-20)

- Spec review before `done` (F28, after mattpocock/skills code-review's Spec axis, MIT): the slot prompt has
  the agent give a fresh subagent only `git diff <base>...HEAD` and `plan brief <ID>`, asking for what is
  missing or partial, what was not asked, and what looks wrong, each quoting the task. Missing and wrong get
  fixed before `done`; an unasked extra is reverted (and filed if worth keeping). Skipped under
  `[run] review_min_lines` (default 50) changed lines when the task has no long form. Every commit message
  ends `review: nothing`, `review: fixed <what>`, `review: filed <IDs>` or `review: skipped (small)`.
  `[run] review = false` turns it off; while on, lean Claude sessions also get the Agent tool.
- `plan restore ID [WHERE]` brings a ticked or dropped task back from `DONE.md` to `TODO.md` as open `[ ]`,
  same id, its text, fields and sub-items kept and its `dropped: WHY` note removed; at the top of the leading
  section unless WHERE (as `plan move`) says. A mistaken tick or drop no longer means re-adding the task
  under a new id. An unknown or still-open id is an error.
- **Breaking:** `plan answer` and its regex reply-guessing are gone, with `[needs] map_replies` (now
  ignored, with a warning). The control session and the runner feed map a reply that names no item ("yes",
  "B", "later") to the item's id themselves and run `plan confirm|change|shelve ID`, asking the person which
  one when they cannot tell. This also fixes `plan add`'s duplicate check: a second `_words` in plan.py had
  shadowed the first, so it matched on ids, fields and stop words again.
- Bare `agent-runner` in a folder holding `runner.toml` or `plan/TODO.md` but no git (a downloaded copy of
  `examples/hello`) makes it a repository with its files as the first commit, then starts the run; it used
  to print the usage. Outside a runner folder it says why git refused, not the whole usage (B58).
  `examples/hello/runner.toml` drops the removed `[run] mode`.

## 0.51.0 (2026-11-20)

- `plan add … --last` files a task at the end of Next with `after: all above`, a marker the run resolves on
  every pick to each task above it in its own section that is not done (ones added later included), so an
  end-of-queue task like a release waits for the whole section without a hand-kept `after:` list going
  stale. Tasks blocked on a person don't hold it until they reopen, and Follow-ups never do. `plan reopen`,
  `plan waiting` and `status` say what it still waits on. The release task T5 uses it now.

- The idle-stop waiter (`run --stop-waiter`) exits as soon as the session it watches is gone, also during
  its grace, instead of sleeping out the grace (up to hours) and then signalling a pid that may since belong
  to another process.

- A session that ends on a usage limit is a cut-off like any other: its worktree stays as it was and it
  resumes in its slot (at most 3 times), instead of the run dropping its transcript and sleeping the slot to
  the reset. The special usage-limit path (`limit_only`, the backends' `limits`) is gone; the `session_max` /
  `weekly_max` caps on starting new tasks are unchanged. Also removed: the agent evaluation probe
  `tests/agent_matrix.py` and `docs/AGENTS-EVAL.md` (`pi auth check` checks a Pi login).

- **Breaking:** the GitHub Copilot CLI backend (`[run] agent = "copilot"`) is gone; Pi with its
  `github-copilot` provider replaced it. A config that still names it stops the run with a message saying
  what to set instead: `backend = "pi"` and `model = "github-copilot/<model>"` (see
  [docs/SETUP.md](docs/SETUP.md#pi-and-enterprise-copilot)). Dead code went with it: the unused Pi extension
  writer, a shadowed `pi_argv0`, the `feed_images` and `alive` aliases, the hidden `run --mode` flag (a
  wrapper still passing it now gets an argparse error) and the empty config-rename table.

- A waiting task whose line guesses a whole directory (`tests/**`, `dir/*`) no longer waits just because a
  running or merge-waiting task touched one file in it; it still waits for a task whose line names a file or
  glob there. This repo's runner.toml sets `shared_files = ["CHANGELOG.md"]`, and the `plan add` guides say to
  name the exact test file, not `tests/**`.

- `status` says how the run is getting on: `merged 11 in the last 24h · 23 tasks left (2 blocked)` (tasks left
  leave out Parked and shelved ones; `status --window 2h` counts over another window), and, when a release
  task is queued, `release: waits on 7 of 25 tasks (T5)`. The control sessions' opening headline uses both,
  and a "how close is release?" is answered from that line, in everyday words.

- A slot's brief now tells it to check the access this machine already has before blocking with `BLOCKED:`
  on a login or token (`gh auth status`, `wrangler whoami`, the service's own CLI login, `ssh -T`,
  `~/.claude/ACCESS.md`) and to name the exact command that failed and its error in the `BLOCKED:` line.

- When a message handed on from the runner feed shows images that Claude Code recorded no saved path for (it
  changed how it records them again), the new control session's first message says so, with the Claude Code
  version, and asks the person to send the pictures there again, instead of the pictures vanishing silently.

- `plan goal` prints the `Goal:` paragraph above TODO.md's first heading, and `plan goal "TEXT"` replaces it
  (prefixed `Goal: ` when TEXT has none; added after the title line when there is none yet) and commits like
  other plan edits. The title, the fields-format line, other paragraphs, headings and task lines stay
  byte-identical. A stale goal no longer needs a task in a worktree to reword it: the control brief says to use it.

- `control --new --ask` passes on any file the person drops in the runner feed, not only images: a .zip,
  .p12 or .txt that Claude Code saves to `~/.claude/uploads/<sid>/<id>-<name>` (an attachment of type file)
  reaches the new control session as "The person attached NAME, saved at PATH: Read or open it before you
  answer", even when the feed drops or mangles the @-mention. `control --image` is now `--file` (`--image`
  still works); files Claude Code re-reads after a compaction are not counted as attached.

- `control --new --ask` again passes on a phone or remote screenshot: Claude Code 2.1.329 records such an
  image as an isMeta entry with `[Image: source: PATH]` text instead of an `inlined_image_paths` attachment,
  and the feed now reads those paths too (deduped; a later text-only message still forwards none).

- The run closes idle control sessions, so the Claude apps' session list stops piling up: every 5 minutes it
  reads the transcript of each live control session N (never c1) and ends it (its process, `controlN.pid`;
  the transcript stays, resumable) once it has been quiet an hour, Claude spoke last, its last message is not
  an open question or offer ("?", "want me to", "should I"), and nothing runs in it (a background task or
  Monitor; the needs-you watch does not count). One left on an open question for 2 hours has that question
  filed under Needs you as a DECIDE item (the question and the session link), then is closed. New `[run]`
  settings: `control_close`, `control_idle` (1h), `control_ask_idle` (2h), `control_open`,
  `control_file_asks` and `control_ask_kind`.

- Wizards for hand steps: a slot agent that blocks with `BLOCKED:` on steps only a person can take (a login,
  a signing cert, a secret, a dashboard click) is told to also write a bash wizard to
  `<notes>/wizards/<ID>.sh`, from the vendored `agent_runner/wizard_template.sh` (mattpocock/skills, MIT):
  one stage per step, URLs opened, hidden entry for secrets, `.env` / `gh secret` writes, a confirm before
  anything irreversible, checked with `bash -n`. Needs you shows `run: agent-runner wizard <ID>` under the
  item; `agent-runner wizard <ID>` checks the script, runs it in the main checkout, and confirms the item
  (`plan confirm`) when it ends well (`--check`: parse only; `--path`: where it is). New `[run] wizards`
  (default true).

- Control sessions opened with an ask are named after it in the Claude apps' session list: `control --new
  --ask TEXT` is "<repo> · N · <first words of TEXT>" (up to 5 words, about 40 characters; "screenshot" for
  an image-only ask) instead of "<repo> · control N", on Remote Control and as its tmux window. N stays, so
  higher is newer and `attach cN` still works; control 1 and a blank `control --new` keep the old name.

- "Waiting for your OK" is now **Needs you**, and reads plainly: each item is one line saying what is asked
  and what to reply (`Check the push reached your phone - reply yes/no`, `Pick an option for the new menu -
  reply A/B/C`), with its age (`2h`) first and its link on a line of its own, oldest first. The
  CONCEPT/CONFIRM/DECIDE/BLOCKED labels stay in the plan and in `plan waiting`, but no longer show in
  `status`, `since`, the feed or the control sessions' opening. A block on a person is stamped `(asked
  <time>)` when it is filed, which is where the age comes from. A reply that names no id ("yes", "B",
  "later", "use SQLite") goes to the one item it clearly answers: `plan answer "<reply>"`, which control
  sessions and the runner feed now run; it asks which one when the reply could fit several. New `[needs]`
  settings: `heading`, `ages`, `order` (`oldest`, `newest`, `plan`) and `map_replies`.

## 0.50.3 (2026-11-20)

- Control sessions show a concept inline for any "show me first" wording ("show me a concept first", "mock it
  up"), not only "concept X": they no longer queue a K task for it, nor `take` one on "do it here" (a K queued
  by mistake is dropped and the page written in the session). The agent-runner skill says the same.

- Images reach the new control session from a runner feed started by an older runner: `control --new --ask`
  reads the calling session's transcript (`CLAUDE_CODE_SESSION_ID`) for the handed-on message's images, and
  `<notes>/remote/feed.sid` only when that is unset. A feed started before 0.50 never wrote feed.sid, so it
  forwarded no pictures and the control session went looking for screenshots on the desktop instead.

## 0.50.2 (2026-11-20)

- Changes reach a running agent instead of restarting it. `plan change ID TEXT` on a task a slot is running
  notes the change as before, then types `Your task changed: TEXT` into the slot's tmux pane (Claude Code
  queues it for its next turn) and leaves the agent working, instead of ending its session, throwing its
  work away and starting over. `plan change ID --restart TEXT` keeps the old stop-and-restart, and so does a
  slot with no live pane (Windows terminals, a session that ended), which the command says. New
  `plan tell ID TEXT` sends a note to the running agent without editing the plan, and fails when no slot
  runs ID. Both go through the run (`<notes>/tell/<ID>.json`) and print e.g. `told s1 (F297)`. The control
  brief maps "tell it…" and small corrections of a running task to them.

- Pictures sent to the runner feed reach the control session it opens: `control --new --ask` picks up the
  images attached to the person's latest message in the feed (the saved paths Claude Code records in the
  feed's transcript) and passes them on as `--image`. The feed no longer has to do it, which a feed started
  before 0.50.1 (one session from the run's start to a real stop) never knew to, nor reliably did on Haiku.

## 0.50.1 (2026-11-20)

- A control session's needs-you watch no longer posts "Still watching. Nothing needs you right now." every
  five minutes: it starts the Monitor with `timeout_ms 1800000` (the cap) instead of the 5-minute default, and
  on a timeout with no lines re-arms it with no text at all, speaking only for a line it printed. The runner
  feed's Monitor does the same.

- The runner feed no longer drops pictures when it hands a message on: `control --new --ask TEXT` takes
  `--image PATH` (repeatable), which adds a line per image to the new control session's first message, naming
  its path and saying to Read it before answering. The feed's brief passes each image the message came with
  (the path the apps note it is saved at).
- `plan drop` and `plan change` on a task the run is on now stop it too, instead of only editing the plan
  while the slot's agent worked on and its branch could still merge. The command leaves a request for the run
  (`<notes>/halt/<ID>.json`); within seconds the run ends that slot's session, deletes task/<ID> here and on the
  remote, resets the worktree (nothing is saved: the work is unwanted) and frees the slot. A change then starts
  the task again in that slot from the new text. A dropped task whose finished branch waits to merge is deleted
  unmerged, and a cut-off session waiting to resume it is taken back. The command prints what the run did, e.g.
  `dropped F297; stopped s1, removed its work (reset s1, deleted task/F297, deleted task/F297 from origin)`.
  `plan change` now takes an open task as well (noted, stays open), not only one waiting on a person.
- Control sessions queue "do X after T181" with `plan add … --after T181` (or `plan block ID --after T181`
  for a queued task) instead of starting a watcher or Monitor that waits for T181: the run starts the task
  once those merge.
- The control brief maps more everyday requests to their commands: "park it" / "low priority" (`plan add
  --pri later|low`), "do that next" (`plan move ID top`), "never mind" (`plan drop`), "split that up" (`plan add
  ID`), "sleep or shut down when done" (`stop --suspend|--shutdown`), "pick that back up" (`resume ID`), tasks
  held by a crashed run (`plan claims`, `plan unclaim ID`) and "where are the tokens going" (`cost`).
- "concept X" / "sketch options for X" in a control session now shows the options there and then: the control
  session writes the page of 2-3 options and a recommendation itself, publishes it and opens it inline, instead
  of queuing a K task that waits for a run slot. It queues a concept only when the person says queue it, later
  or add a task.
- The runner feed ("<repo> · runner") carries on across restarts that are not a stop. An upgrade's restart
  (auto_upgrade, `u`) execs in place, so the board window and its feed stay up as they were. When the feed does
  have to start again (its board window was replaced or closed, the feed exited, a crashed run was started
  again), it resumes the same Claude session (`--resume`, its id kept in `<notes>/remote/feed.sid`), so its
  history and its app entry carry on instead of a new one. A stop still ends it, and the next run's feed is a
  new session. A resume that fails at once (the transcript is gone) makes the next start a fresh session.

## 0.50.0 (2026-11-20)

- Old Remote Control entries no longer pile up in claude.ai/code and the apps. Claude Code has no command to
  end or archive a session from outside. It archives its own entry when it exits on SIGTERM, SIGHUP or Ctrl-C,
  and an entry stays listed only when its process dies without that (SIGKILL, a crash, a reboot, a power-off
  right after a stop). The run now records the Remote Control processes it starts for itself, the runner feed
  and the control server, in `<notes>/remote/`. A stop ends them with SIGTERM and waits up to 20 s for them to
  archive themselves before the run exits, suspends or powers off. The next start does the same for any an
  earlier run left (a control server that run's restart adopts stays up instead: no new entry). None is
  SIGKILLed: one that outlives the wait is left running and named in run.log, and a feed the board had to kill
  is named at the next start, so you can archive it by hand. Control sessions are yours and stay up, and
  sessions the run did not start are never touched.
- The background run keeps a board window, "board-<repo>": `since --board` (what landed, started, stalled or
  needs you, the last 6 hours then live), under a line saying to steer from a control session. No LLM, so no
  tokens; it leaves the last-look mark alone, and the run opens it again within 30 s when it is closed.
  `agent-runner attach board` goes there.
- With `[run] remote` on, the run opens c1 beside it again (0.49.0 left it out), in tmux (or its Windows
  console) for the terminal only: it is not on Remote Control, so the apps show no "<repo> · control 1" beside
  the control server's "<repo> · control" (the one app entry for starting control sessions) and its start pushes
  nothing. It opens blank, with no summary turn, so it uses no tokens until you type in it.
- The runner feed: with `[run] remote` on, the board window is a lean Claude session that is also in the apps,
  as "<repo> · runner". It posts each line of `since --follow --keep-mark` as it lands, runs status, pause,
  stop, force, slots N and `control --new` when asked, and hands anything else to a new control session
  (`control --new --ask TEXT`), answering with its link. It runs Haiku with only Bash (the runner's command,
  nothing else) and Monitor, its own short system prompt, and no settings or MCP servers: about $0.001 a
  landing at API prices. With remote off, the board stays the free text feed.
- The runner feed is the one watch for what needs you: it pushes those lines (PushNotification), and control
  sessions start no needs-you watch of their own while it runs (they still do without it: remote off, Windows,
  no tmux). The full `since --follow` feed now carries the "waits for you" asks too. The board, and so the feed,
  opens in any tmux run, not only the background one. The feed loads no auto memory.
- `since --follow --keep-mark` leaves the last-look mark alone; `control --ask TEXT` gives a control session
  its first message.
- The board follows the run. It ends when the run does: after a plain stop once the running tasks are done, a
  force stop, or a crash. The runner feed's process ends, so "<repo> · runner" goes offline in the apps and the
  window closes. The next run opens a new board. While the run is idle, or paused or stopping with nothing
  running or merging, the feed holds its lines: no Haiku turns, no pushes, no tokens. When the run starts
  something (a task added, the run unpaused) it prints what was logged meanwhile and carries on. You can still
  type to it while it holds. The board window now runs `since --board [--feed] --run-pid PID`, and STATE says
  `idle`, `paused` and `stopping`. A board left by an earlier version is replaced when the run starts.
- Known limit of the quiet launch (checked by hand on a phone): Remote Control's own "session ready" push
  ignores `CLAUDE_CLIENT_PRESENCE_FILE`, so each Remote Control slot start (`remote_slots = true`) buzzes the
  phone even with `.runner/quiet-slots` in place, and the runner cannot stop it. The presence file only keeps
  the client's later pushes quiet.
- `remote_slots = true` means slots on Remote Control, and each slot start pushes to the phone. Nothing the
  runner can set stops that push (found in the Claude Code 2.1.329 binary): the server sends "session ready" as
  the session registers, and the presence pulses only start after that. `agentPushNotifEnabled` and
  `inputNeededNotifEnabled` are account settings on the server, which Claude Code only updates when you change
  them in /config, never from `--settings`, and no environment variable turns the push off. Slots keep
  `.runner/quiet-slots`, because Claude Code pulses it just before a needs-input or turn-done push, so those
  pushes should stay quiet. They keep `agentPushNotifEnabled: false`, which blocks a slot's own
  PushNotification tool. They no longer get `inputNeededNotifEnabled`, which did nothing. `remote_slots` stays
  off by default. To stop every push, turn notifications off for the Claude app on the phone (that covers all
  sessions). For the same reason, the control sessions' and the control server's quiet launch most likely
  does not silence their start push either.

## 0.49.0 (2026-11-20)

- Bare `agent-runner` starts the run in the background; `agent-runner attach [sN]` attaches to its pane (or a
  slot's), and `agent-runner --attach` does both: starts the run, or finds the one up in this repo, then attaches.
- `[run] auto_upgrade = true`: a run upgrades agent-runner by itself when the update check sees a newer
  release, once no merge is under way, and restarts on it keeping what the keys set. Never across a major
  version, nor on Windows.
- Control sessions: interactive Claude sessions in the main checkout for steering the run.
  `agent-runner control` opens one (`control --new` another, without taking focus, printing its claude.ai/code
  link). With Remote Control off, the run opens c1 beside it (`[run] control = false`: none); with it on, a
  control server starts them from claude.ai/code and the Claude apps, and the run opens no c1. Control sessions
  and the control server run with `bypassPermissions`, so the web and the phone see no permission prompts.
  Control 1 opens with a short status summary (a headline, then Waiting for your OK / Running / Landed / Stuck,
  concept pages opened inline) and a hints line of slash commands (`/run /since /follow /control /pause /stop
  /slots N`); later ones start blank. Each watches `since --follow --needs-you` and tells you, unasked, when
  the run is held, a task is left for a human, a slot looks stalled, or something waits on your answer.
- `agent-runner since [WHEN] [--follow] [--needs-you]`: what happened since you last looked, or a live feed.
- **Changed: `[run] remote` now means the control sessions and the control server; the slots go on Remote
  Control only with `[run] remote_slots = true`** (in 0.48.0 `remote = true` put the slots there). Remote slot
  sessions are named "<task title> · <repo> s2 · B646".
- Concept tasks (kind K) publish an Artifact page of options and build nothing: `done K7 --artifact URL`
  notes the link and files the build blocked "waiting for your OK on URL"; `plan approve` / `revise` /
  `waiting`. Tasks blocked on a person (CONFIRM / DECIDE / BLOCKED) are listed beside concepts under
  "Waiting for your OK"; `plan confirm` / `change` / `shelve` / `unshelve`, `plan waiting --all`.
- Hints print the command you typed (`agent-runner` from PATH, not the clone's `./run`).
- A run restarts an adopted control server that was started with other flags.
- Fixes: concurrent `plan add` on an in-repo plan never reuse an id; Claude trust creates a missing
  `$CLAUDE_CONFIG_DIR` (and skips trust if it cannot write there).

- `[run] silent` picks how quiet a run's Remote Control sessions are on the phone: `"launch"` (the default, the
  quiet launch below), `true` (no push ever, control sessions included), or `false` (no presence files or push
  settings: Claude Code's usual pushes). Anything else is refused.
- **Changed default: `[run] remote` is now `auto`, so control sessions and the control server go on Remote
  Control by default** (they were local unless you set `remote = true`). Auto turns it on only where it can
  work and otherwise leaves it off with one line in `run.log` saying why: the backend is pi, the agent is
  Copilot CLI, `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` is set, `CLAUDE_CODE_USE_BEDROCK`/`VERTEX`/`FOUNDRY`
  is set, `ANTHROPIC_BASE_URL` is not api.anthropic.com, or Claude Code's one-time "Enable Remote Control?" has
  not been answered yes (the launch asks it at a terminal; a no, or no terminal, starts the run local instead
  of refusing). `remote = true` / `false` still force it; anything else is refused. The slots stay local
  unless `remote_slots = true`. To keep the old behaviour: `remote = false`.
- Quiet launch: a run's Remote Control sessions no longer buzz the phone as they start. Each gets
  `CLAUDE_CLIENT_PRESENCE_FILE` (Claude Code 2.1.181+ sends no mobile push while that file exists). A control
  session's file (`.runner/quiet-c<N>`; the control server's `.runner/quiet-server`) is there only until its
  claude.ai/code link shows, so later pushes (a concept waiting for your OK, a stuck run) still arrive. Slots
  with `remote_slots` keep theirs (`.runner/quiet-slots`) for good, and get `agentPushNotifEnabled` and
  `inputNeededNotifEnabled` off in their settings too. Not yet checked by hand on a phone, and the docs don't
  say whether Remote Control's own "session ready" push honours the presence file.

## 0.48.0 (2026-11-19)

- Every key of the runner's pane is a command too, for a person in another terminal or a remote session:
  `agent-runner pause` / `force` (`--off` to take back), `slots N|+N|-N`, `stop --undo`, and `key <k>` for the
  rest. `pause`, `force` and `stop` say which way they go, so saying one twice does not undo it.
- `agent-runner status`: whether a run is up, what its keys have set, each slot's task, and the end of its log.
- A slot can publish a page or screenshots to claude.ai with the Artifact tool and link it (lean sessions
  now get `Bash,Read,Edit,Write,Artifact`). It needs a claude.ai login; print-mode fix sessions don't have it.
- `[run] remote = true`: every slot starts on Remote Control, named "<repo> · s2 · B646", so it can be watched
  and typed to from claude.ai/code, the desktop app or the phone apps. Enter in the runner's pane opens
  claude.ai/code. Claude Code only; needs a claude.ai login (not an API key).

## 0.47.0 (2026-11-19)

- `agent-runner take "TEXT" --kind K [--files A,B]`: queue a task and take it in one step, no id needed.
  `take --here` (with TEXT or an ID) moves the main checkout's uncommitted edits, new files too, into the new
  worktree, leaving the main checkout clean.
- The line a run puts in the rules file (AGENTS.md/CLAUDE.md) now says: asked to do something now, use
  `take`; never edit the main checkout. A run rewrites the older line in place. The guide says it too.
- Edits in the main checkout that hold a landing: the STOPPED line, and the log line when `land_edited =
  "wip"` moves them aside, say to use `take --here` next time. `plan claims` and `run --dry-run` list the
  `wip/main-checkout-*` branches, so they are not forgotten.
- A subtask of a parent tagged `later` but moved out of Parked is no longer tagged `later` itself.

## 0.46.1 (2026-11-19)

- A session whose `done` succeeded is ended 5 s after its last turn, not `[run] idle` (90 s): the slot's next
  task starts sooner. A session that stops without `done` still gets `[run] idle`, so a person can take it over,
  and `idle` now defaults to 30 s (was 90).

## 0.46.0 (2026-11-19)

- `agent-runner take ID`: one chosen task for a person's own session or a subagent, beside a run or without
  one. It gets a worktree in the runner's home (`take-ID`, on `task/ID`) and the prompt a slot would get; a
  run that is up treats it as running and keeps other tasks off its files. Finish with `done` there, then
  `take ID --merge`: with no run up it is tested and merged at once, otherwise the run merges it within a
  minute. `take ID --drop` gives it back. The guide skill says when to use it.
- A run merges any `task/` branch that finished outside its slots while it is up, not only at its start.
- `plan move P17 top` takes P17's subtasks with it: they no longer stay behind in Parked, where no run starts them.
- A subtask of a subtask (`plan add P17a …` -> P17a1) files after its family like any other subtask, not at the
  top of Next.

## 0.45.1 (2026-11-19)

- A newer agent-runner shows as a green banner in the runner's pane, shaped like the STOPPED one, saying how to
  upgrade (`u` + Enter when the pane reads keys). The run looks every 6 hours, not only at the start, says each
  version once, and `?` keeps listing it.

## 0.45.0 (2026-11-19)

- `u` in the runner's pane upgrades agent-runner (`uv tool upgrade`, `pipx upgrade`, or `git pull --ff-only` in
  a clone); the run restarts on the new version as it does after any upgrade. `run --upgrade` upgrades first,
  then starts on the new version.

## 0.44.0 (2026-11-19)

- `f` in the runner's pane forces past the session and weekly usage caps, as `--force` does, without a
  restart; `f` again puts them back. An upgrade restart keeps it.
- Hitting a usage cap raises the same loud STOPPED alarm as edits holding a merge (banner, bell, tmux message,
  desktop notification), saying how to go on: `f` + Enter, or a restart with `--force`.

## 0.43.0 (2026-11-18)

- More keys in the runner's pane, listed in a ruled-off block when the run starts and on `?` + Enter:
  `s!` stops now (ends the agent sessions, each queued to resume in its slot next run, then exits once the
  merges under way finish), `p` pauses without exiting, `+`/`-` add or take away a slot, and `z`/`x` suspend or
  shut the computer down once the run stops (or goes idle). A line it does not know is echoed back with the list.
- `stop` takes `--force`, `--suspend` and `--shutdown`, the same as `s!`, `z` and `x`.
- A key is acted on and logged the moment it is typed: `stopping` no longer waits up to a loop pass.
- A restart on an upgrade keeps what the keys set: the slot count, a pause, a suspend or shutdown, and a stop.

## 0.42.1 (2026-11-18)

- Agents are told to edit files with their editing tool, not `sed -i`, `perl -i` or a script in a heredoc, and
  to run one plain shell command at a time: a command Claude Code's safety check cannot read stops for a human,
  and in an unattended session it waits, is refused, and the minutes are lost. Also: no `rm -rf` on a variable
  or glob, no `git reset --hard`, `git clean`, `git checkout -- .`, `git stash` or `git push --force`. The same
  text is in the runner's prompt and in the guide skill (a new rule 7, which also keeps sessions out of the
  runner's home and `.runner/`).

## 0.42.0 (2026-11-18)

- One repair session per failure, not per task: a repaired merge rebuilt on commits the shared branch got after
  the repair, which fails the gate again, is a new failure and gets a repair session of its own (logged as such).
  The same failure on the same base still gives up after one.
- `run --dry-run` accounts for every open task: one held by a file clash says which files and who holds them
  (`waiting for files: F171 (web/app/** held by B20)`), and others say the running sibling, the task ahead in an
  ordered section, running, finished and waiting to merge, claimed by another runner, tried this run, or next
  once a slot is free. "Nothing to start" no longer leaves an open task out of every list.
- A branch that does not merge is logged as `not merged, parked as wip/<ID> — why`, with when the task starts
  again by itself (the next run, or this one once its line is edited). "LEFT FOR A HUMAN" is kept for what truly
  is: a crashed merge, or a branch that could not be parked.

## 0.41.0 (2026-11-18)

- Every command a person runs (`plan`, `--version`, `help`, …) keeps the `agent-runner guide` skill installed, not
  only `run`: anyone who has typed agent-runner on a machine has it. Said once on stderr when written.
- A run adds one line to the repo's rules file (`[run] rules`, else AGENTS.md or CLAUDE.md), committed on its own,
  pointing every session at the skill and `agent-runner guide`: the guidance reaches sessions on machines without
  the skill, and ones that would not pick it. Never into a file with uncommitted edits; it never creates a rules
  file; `[run] rules_pointer = false` turns it off.

## 0.40.0 (2026-11-18)

- A repair session that finds a flaky test, not a clash, ends with `FLAKE: <test>`. The runner then runs the gate
  once more on the merge as it is before parking anything, and files the flaky test to be fixed either way. A
  flake used to park a tested branch as `wip/<ID>` for a person.
- A merge held by uncommitted or staged edits in the main checkout is a loud STOPPED: a red banner in the runner's
  pane, the bell, a tmux message and a desktop notification (`notify-send`), raised again every 30 min while it
  holds, and a line when it clears. It was one yellow log line, easy to miss for hours.

## 0.39.0 (2026-11-18)

- Runs claim tasks with the plan in the code repo too, not only with `[plan] repo`: a claim is a ref on the
  code's remote (`refs/agent-runner/claims/<ID>`), and the first push wins. Two runs, on two machines or in
  two clones on one machine and account, never start the same task, and keep off each other's files.
- `agent-runner guide`: how an agent session a person starts in the repo should work with the runner (queue
  work with `plan add` instead of editing TODO.md or doing it on a branch, leave `task/*` and `wip/*` alone,
  how to unstick a task). Each run keeps it installed as a Claude Code skill in `~/.claude/skills/agent-runner`,
  rewritten whenever its text changes; `[run] install_skill = false` turns that off.

## 0.38.1

- `[git] land_edited = "wip"`: a tested merge that uncommitted edits in the main checkout would block no longer
  waits forever. After 3 minutes the edits (new files included) go to a `wip/main-checkout-<time>` branch, pushed
  with the shared branch, plus a stash; the log names the files and how to get them back, and the merge lands.
  The default stays `"wait"`.
## 0.38.0 (2026-11-17)

- A run restarts itself on a new version installed under it (`uv tool upgrade`, `pipx upgrade`, a pull in a
  clone), once no merge is going, and adopts its sessions, merges and gates. Before, the loop kept running
  the old code while the sessions' `done` and Stop hook ran the new one. Not on Windows, and not across a
  major version: that one is logged once for a human to restart.
- The run log names every stale key in `runner.toml` / `runner.local.toml` at the start of a run: a renamed one
  (it still works under its old name, from a table of renames each release adds to), a removed one with what to
  do instead, and an unknown one with the nearest real setting. An upgrade never needs a config edited first.

## 0.37.3 (2026-11-17)

- A task tried and failed in a run goes back in the pool once its line is edited (a `plan note` with what to
  do differently, a corrected line), not only once it is blocked and unblocked. A failed task waited for the
  next run even after it was given the fix: Cydian's I2 sat out a day-long run with its note saying what broke.

## 0.37.2 (2026-11-17)

- A merge turn that finds a merge already gated for other waiting tasks gives its turn up to them, once,
  instead of dropping that merge. After a restart, the gate a run left is adopted inside whichever turn
  comes first; P347's turn threw away R38's batch of 16 tasks, which had just passed a 42-minute gate.

## 0.37.1 (2026-11-17)

- A merge built ahead waits while a gate still runs in merge2. After a restart, a turn could adopt the gate an
  earlier run left there, and the next merge-ahead checked out over it: the gate then built and tested the
  new tree and reported its failures as the adopted merge's, and the retest on the real merge passed, so
  three tests were filed as load flakes that were never flaky.

## 0.37.0 (2026-11-17)

- With `[run] test_since`, a shared branch that gets code commits during a merge's gate no longer means
  building and testing the whole merge again. The new commits are merged into the tested merge, and the
  gate runs on what they change, from that merge. A conflict or a failure there still builds it all
  again. One kit commit to main during a 54-minute batch gate had cost a second 54 minutes.

## 0.36.1 (2026-11-17)

- A finished task waiting to merge holds only the files it changed, not every file its plan line names. One
  line naming `tests/**` kept 38 tasks from starting while merges were behind.

## 0.36.0 (2026-11-17)

- A failing batch's culprit is found by halving the batch: about 5 retests for 16 tasks, not 16.
- Task ids are held in a list in the git dir once handed out (by `plan add`, a renumber, or an unmerged
  branch at `run` start), so two branches no longer take the same id and get renumbered at merge, again
  and again.
- Gentler backpressure: `batch_max` 16, `max_unmerged` 32, one slot held per half batch past it.

## 0.35.0 (2026-11-16)

- A test the base already fails no longer blames a batch's tasks. Before, one inherited failure beside a
  new one put every task of the batch in a merge of its own, and the merges fell 70 tasks behind.
- If most of a batch fails alone, nobody is put aside: it is the base or the machine.
- Critical tasks merge alone and first; a merge built ahead goes next, then the rest in order.
- `[run] batch_max` (10) caps a batch; `[run] max_unmerged` (12) eases slots off while merges fall behind.

## 0.34.1 (2026-11-16)

- `plan add MD39b …` files the subtask MD39b1: a task id ending in a letter is taken as KIND when it is an
  open task's id, as one ending in a digit always was. A letter-ending id that is no open task is still refused.

## 0.34.0 (2026-11-16)

- Run sessions with GitHub Copilot CLI as well as Claude Code and Pi, including session recovery and fix sessions.
- Support local-only runs with `[git] push = false`, while preserving inherited Git configuration.
- Improve Windows terminal sessions, startup diagnostics and UTF-8 Git output.

## 0.33.0 (2026-11-16)

- `run --suspend`: like `--shutdown`, but the computer sleeps instead of powering off. On waking the run
  carries on, and it suspends again only after it has had work and gone idle again.
- README: *How it works* rewritten step by step (what makes a task wait, what happens in a merge), and a
  section on filing tasks from a Claude Code chat, with an example.

## 0.32.1 (2026-11-16)

- The runner's pane is in colour: starts blue, merges and pushes green, blocks and conflicts yellow, failures red,
  exits grey, task ids bold. Only on a terminal (Windows: Windows Terminal), never with `NO_COLOR`; run.log stays
  plain text.

## 0.32.0 (2026-11-16)

Breaking: settings removed. A config that still sets them is not an error; they are ignored.

- Mode p is gone: a run never starts two tasks on the same files (what mode d did), and an "in this order"
  section always runs one task at a time. `[run] mode` is ignored; `run --mode` is still accepted, and ignored,
  so wrapping CLIs that pass it keep working.
- `[run] fix_ahead` is folded into `fix_ahead_max`: `0` fixes conflicts under the lock, as `fix_ahead = false` did.
- Removed `[run] precommit` and `done --skip-check` (chain the check into `[run] test`, or run it in a wrapper
  before `done`), `[plan] brief` (use `brief_extra` and `outline`), `[run] ci_rerun` (a red CI run's failed jobs
  are always run once more first), and `[run] batch_wait` / `batch_min`.
- A remote given as a relative path (`origin = ../origin.git`, a relative `[plan] repo`) is the main checkout's:
  `done` in a slot's worktree pushes to it instead of failing. A push to a remote that cannot be reached says
  so with git's own message, not "has moved and merging it conflicts".
- README rewritten as an overview; the full behaviour and every key moved to docs/REFERENCE.md. The context
  numbers are re-measured over 1,836 slot sessions.

## 0.31.0 (2026-11-16)

- `agent-runner context [--check]`: what every session loads before it starts ([run] rules, CLAUDE.md,
  AGENTS.md and their `@` imports), per file and biggest section first, against `[plan] context_kb` (12 KB).
  `run` logs a warning at start when it's over; `--check` exits 1.
- `plan <name>` prefers a heading named exactly that over one that only contains it (`plan hst` no longer
  stops at `hst-data`), across every file it searches.
- `[plan] lookup` takes globs (`"plan/guide/*.md"`).
- The agents' prompt says reference material they write goes under its own heading in a lookup file, not in
  the rules file every session loads.

## 0.30.3 (2026-11-16)

- A conflict fixed ahead of the merge lock waits while another task, fixed ahead and not merged yet, had a
  conflict in one of the same files. It is then fixed once against that merge, instead of side by side and
  again after the first lands (`waits for X to merge first` in the log).

## 0.30.2 (2026-11-16)

- Windows Pi sessions launch the Node CLI directly instead of npm's `.cmd` shim; Linux/macOS keep
  their configured executable.
- Update notices accept single- and double-quoted version strings. Release automation reads the version
  as Python, rejects invalid versions, and publishes numbered releases with installation commands.
- The README version badge uses GitHub releases and links to installation instructions and release notes.

## 0.30.1 (2026-11-16)

- The agents' prompt tells them to file follow-ups with `--files` (and `--after`), not text alone.

## 0.30.0 (2026-11-16)

Breaking: a new task line format, and the old one is no longer read. Rewrite TODO.md once.

- A task line is `- [ ] **ID** prose | files: a, b | after: X, Y | test: name | journal: dir`, then an optional
  ` — note` and `BLOCKED: …`. Only the fields count; prose is never parsed for files or ids. `→ files`,
  `(after X)`, `| t:` and `| j:` are gone, and so is the rule that a line naming a running task's id waits.
- `plan add --files/--after/--test/--journal` writes the fields; a line with no `files:` and no `test:` gets a
  warning (an error with `[plan] need_files`). Its next free id counts the plan in every worktree of the repo,
  so two sessions adding at once no longer take the same id.
- Mode d keeps a task off the files of running and finished-but-unmerged tasks: their lines' and the ones
  their branches have touched. A path meets its own tail (`src/menu.rs` meets `app/src/menu.rs`).
- An ordered section is one whose heading says *in this order* or *one at a time* (no longer any *Next*).
- `LICENSE*` and `COPYING*` join `*.md` in the default `untested`: a license commit landing mid-gate no longer
  throws the passed gate away.
- Fixes: a merge whose branch kept getting code commits during its gate is no longer landed untested on the
  third try; gate records check the process start time, so a reused pid is not mistaken for a live gate;
  renumbering a doubled id renames its `plan/tasks/<ID>.md` too; the union/renumber scratch files are per
  task (two merges in threads no longer share one); `master.json` is removed only by its own session;
  a remote `task/*` branch an earlier failed push left behind is deleted once main has it; a branch left for a
  human drops its held refs as well as its fixed ones.
- Removed: support for pre-0.14 claims, the pre-0.13 `~/.cache/agent-runner` plan clone and `<repo>-slots/`
  worktrees.

## 0.27.0 (2026-11-15)

- `[run] session_max` (default 90): past that % of the account's 5-hour session usage, no new task starts,
  as `weekly_max` does for the 7-day usage. Before, only the weekly figure was watched, so a run of several
  slots could spend the whole session limit and leave every slot stuck at the limit prompt.

## 0.26.1 (2026-11-14)

- `batch_wait` skips a task whose gate is already running (adopted after a restart, or built ahead): a task
  joining it would start that gate over.

## 0.26.0 (2026-11-14)

- A batch that fails the gate looks for the task that breaks it by itself: each branch is merged alone and
  `retest` runs just the failing tests. Those tasks merge in their own turn; the rest are gated together
  again, instead of every branch going alone. With no branch failing alone, the batch repair runs as before.
- A one-task repair starts as a copy of the session that did the task (Claude only), so it knows the change.
  The repair prompt no longer assumes the branch passed the gate on its own.
- `[run] batch_wait` / `batch_min`: a finished task can wait for others before its gate run while slots
  still work, so one gate run covers more tasks. Off by default.

## 0.25.0 (2026-11-12)

- A gate failure the base fails the same way still merges anyway, and now files a critical task to make the
  test pass again (once, while none is open), so the shared branch is not left failing it unnoticed.
- With `[run] test_since`, a whole `test` that found only failures the base already has counts as the day's
  whole run: they are filed, and the merges after it go back to the selective gate rather than each running
  the whole `test` again to find the same failure. The task says to widen the selection too.

## 0.24.0 (2026-11-12)

- `[run] test_since`: a merge's gate tests only what changed since `{base}`, the commit the merge is on (one
  that passed a gate), and the whole `test` runs again once `[run] full_every_hours` (24) pass without one.
  The log says which ran.
- The prompt tells sessions to run `done` and whole test suites as a background command and wait: a gate
  waiting for a lock outlasted agents' own command time limits, and a cut-off `done` commits nothing.
- README: "Making it fast", what a many-slot setup needs from its gate.

## 0.23.0 (2026-11-11)

- A batch is pushed once, by the last of its tasks to record its landing (`… pushed main -> origin (with …)`),
  not once per task: each push to the shared branch is a CI run. A merge that takes the lock first pushes the
  batch before its own gate.

## 0.22.0 (2026-11-11)

- CI watch: a red run's failed jobs are run once more (`[run] ci_rerun`, on by default) before a task is
  filed, and nothing is judged while a newer run of the workflow is under way. A runner GitHub never handed
  the job and a DNS outage had each filed a task for a branch that was fine.
- A test the memory watch ends is named (thread names, then the binary's `--list`) and gets a `critical`
  task at the next merge, like a flaky one.
- `drop_ahead` removes `merge2`'s gate records with the gates it stops: one left behind read as a gate to wait on.

## 0.21.0 (2026-11-11)

- A memory watch (Linux): a process of the run's (in one of its worktrees, or started from a slot; never an
  agent) resident past `[run] proc_max_gb` ("auto": a quarter of the memory) is killed, alone, and logged;
  under `[run] min_free_mem_gb` (4) available, the run's biggest is. A test looping over a tree in RAM had
  grown to 52 GB in each of three slots' gates, and the machine's OOM handling ended other work for it.

## 0.20.3 (2026-11-10)

- A fix worktree (and `merge2`) is the runner's own: a task starting on files a fix ahead of the lock has
  open was logged as heading into "uncommitted edits outside the runner".

## 0.20.2 (2026-11-10)

- `[run] suspect` flags a block a merge adds, not a blocked line edited some other way (`fill_files` adding its
  `→` list made S283's merge flag S251's old block).

## 0.20.1 (2026-11-10)

- At most `[run] fix_ahead_max` (2) fixes ahead of the lock at once: a run started with many finished,
  conflicting branches would have opened a worktree, a build and an agent session for each of them. The
  rest wait their turn, so there are never more fix worktrees than the cap. Each also waits on
  `[run] before_start` (the room check) as a slot does, is trimmed past `slot_max_gb`, and an idle one is
  cleaned under `min_free_gb`.

## 0.20.0 (2026-11-10)

- A conflict the join cannot do gets its fix session before the merge lock is taken (`[run] fix_ahead`, on by
  default), in a fix worktree of its own (`fix1`, `fix2`, …, kept warm). The other finished tasks merge and
  gate meanwhile; the fixed merge (`refs/agent-runner/fixed/<ID>/<sha>`) then goes in under the lock, clean,
  or with a second, smaller fix ahead if the shared branch touched the same lines again. The third try fixes
  under the lock as before. `fix_timeout` now holds up only that task: one fix session used to hold every merge
  for up to 40 min.
- With `fix_ahead`, a batch rider whose conflict needs a session waits for its own turn instead of taking a
  session inside the batch.

## 0.19.6 (2026-11-09)

- A task line's files are its `→` list when it has one; prose file names count only on a line without one.
  A menu task that said "what race.rs already has" waited on every task touching race.rs.
- Picking: a task that a waiting task depends on (`(after X)`, `BLOCKED: (after X)`) takes that task's place
  in the order, transitively; Stretch and Parked lines pull nothing up. A Next task blocked on Follow-ups
  waited behind every task between them.
- The plan is read from the remote's shared branch when it is strictly ahead (fetched at most once a
  minute): a hand merge pushed from another worktree left the main checkout's plan showing that task open,
  and the next free slot would have started it again.
- With `[plan] need_files`, each merge gives task lines written into TODO.md by hand their prose's files
  (`plan.fill_files`) and logs, once each, the ones naming nothing.

## 0.19.5 (2026-11-09)

- `[plan] need_files`: `plan add` refuses a task line that names no file and no test (no `→` list, no
  `| t:`), and gives one whose prose names repo files a `→` list of them. Mode `d` keeps running tasks apart
  by those files, so a line naming none ran beside anything. A load-flake task names its test (`| t:`).

## 0.19.4 (2026-11-05)

- A critical follow-up goes into the plan's own Critical section when it has one (a heading naming
  "critical"), at its end, rather than to the top of the leading "Next" section, where in an ordered
  section it held up the queued work.

## 0.19.3 (2026-11-05)

- `[run] copies`: git-ignored files copied into a new worktree once, where `links` would share one file
  (a local config the tests read from the checkout's root). The merge-ahead worktree had none and its
  first gate failed on that alone.
- The gate on a merge built ahead says how it ended; a failure is kept for that batch's turn, which goes
  from it (retests, repairs) instead of running the gate again.

## 0.19.2 (2026-11-05)

- An adopted gate that failed is no longer thrown away: its merge is reused as it was gated and the
  failure handling (retests, the repair session) goes from that result, instead of a new batch with the
  tasks that finished meanwhile and a whole gate run again. The log says how an adopted gate ended.
- A gate that ended while no run was up counts as it ended (its exit code is read from disk), and a merge
  built ahead (merge2) survives a restart: its turn reuses it and waits for its gate by tree.
- A failed gate's output is kept a week (`.runner/gates/<key>.failed`); it used to be deleted.
- Two turns waiting on the same gate run read one result; the second used to find nothing and rerun it.
- The riders of a merge an earlier run gated wait from startup, so its turn finds them and reuses it.

## 0.19.1 (2026-11-05)

- A gate that passed under an earlier run is not wasted when tasks finish or plan commits land in
  between: its merge is reused as it was gated (the gate record keeps the batch), the plan commits are
  merged into it, and the tasks that finished meanwhile wait for the next turn. A gate pass is now keyed
  on the files the gate tests (`[run] untested` left out), so a plan commit does not make a passed merge new.

## 0.19.0 (2026-11-05)

- Merge ahead (`[run] merge_ahead`, on by default): tasks that finish while a batch is in its gate are
  merged on top of that merge in a second worktree (merge2) and gated beside it. The next turn reuses that
  merge, and waits for the gate already running on its tree, instead of starting its gate only after the
  last one landed. A failed first batch drops the merge built ahead and stops its gate.
- Gate runs are recorded per tree (`.runner/gates/<key>.json`, not `.runner/gate.json`), so a turn waits
  for a gate already running on its exact merge, and a restart adopts every gate an earlier run left.

## 0.18.0 (2026-11-05)

- A restarted run adopts the merge the last one was in the middle of, the way it adopts the slots'
  sessions. The merge gate now runs in a session of its own that outlives the runner, and a pass is kept
  per tree and gate command (`.runner/gates/`, a week), so the same merge is not tested twice. A fix or
  repair session in the master window records itself (`.runner/master.json`), the next run waits for it,
  and what it committed is kept under `refs/agent-runner/held/<ID>/` and reused when the merge is built
  again. A restart used to throw all of that away and redo it, which cost a whole gate run.
- The startup log no longer says every unmerged branch "finished while no run was up": it is "its merge
  was under way when the last run ended; adopting it" or "finished, not merged yet; merging it now", and
  the adopted one merges first.

## 0.17.0 (2026-11-05)

- `plan add` refuses text that looks like an open task's work (exit 3, nothing written), naming the open
  task: `plan note` it there, or add again with `--force` when it is different work. It used to add the
  task and then warn "may be the same work … drop this one", which agents kept reading as a refusal, so
  duplicates landed (three times in one repository in a week). A task's own split is never refused for
  looking like its parent; the runner's own filings (flaky tests, CI) are unchanged.
- `plan drop ID WHY`: close a task nobody will do, archived with `dropped: WHY` so its id stays used and
  what waits on it reopens. The old warning named a drop that did not exist.
- A note one side added to a task the other side ticked is no longer lost: the tick still wins in TODO.md,
  and after the merge the runner appends the note to the task's line in DONE.md (`plan.carry_notes`).

## 0.16.0 (2026-11-05)

- The task list and its archive merge by section and task instead of by line. `run` makes
  `agent-runner merge-plan` git's merge driver for TODO.md and DONE.md (`.git/config` and
  `.git/info/attributes`, shared by every worktree, never committed; a plan clone gets it on its next
  pull), so every merge of them goes through it: the runner's, a rebase, a person's. Each part merges
  against the base: sections by heading, tasks by id wherever they moved, and a task line's box, text,
  ` — notes` and `BLOCKED:` one by one. A task one side ticked stays gone though the other noted it, a
  moved heading comes out once, two notes on one line are both kept, a task added on each side goes where
  its side put it, and one id handed out on both sides keeps both tasks. Where both changed the same part
  of the merged branch's own task, the branch's words win (`AGENT_RUNNER_TASK`). Prose both sides
  rewrote falls back to git's text merge and its conflict. Replayed over 752 of this repository's
  past task-list merges, 739 come out as they did and the rest differ only in order or keep a move the
  old join undid.
- Removed what cleaned up after the line join: the runner's `dedupe_tasks` and `dedupe_headings` passes
  and `plansync`'s `tidy` (with its commit after a pull). TODO.md and DONE.md are no longer in the
  `[run] joinable` default (now `[]`) and are never line-joined, even when a config still lists them.

## 0.15.1 (2026-11-05)

- A joined task list keeps each heading no more often than either side has it. `--union` keeps both sides
  of a conflict, so a heading one side moved beside a line the other side changed came out twice; tasks
  filed later went under the empty first copy, and an ordered section's own tasks waited behind them.
  The extra copy is dropped and its lines go to the end of the first copy's section.

## 0.15.0 (2026-11-04)

- `runner.local.toml`: one machine's settings (`weekly_max`, `slots`, `model`, any key) laid over
  `runner.toml` key by key, so a person tunes their own run without editing the shared file. `run` creates
  it in the main checkout (all comments, changing nothing) when it is missing and never rewrites it, and
  keeps it out of git through the clone's `.git/info/exclude`. Worktrees read the main checkout's; it may
  wrap its tables in `[agent-runner]` like a wrapped config; a broken one stops the run naming the file.

## 0.14.1 (2026-11-04)

- `[run] ci_watch` defaults to `"auto"`: every workflow in `.github/workflows/` that runs on a push to the
  shared branch is watched, its push runs only (a nightly, release or manual run files nothing), so a red
  main becomes one critical task without any setup. `false` turns it off; a list still names workflows.
- A `gh` that cannot see the repository (not installed, not logged in, the wrong account) is said once in
  the run log instead of being read, every 5 min, as "no runs yet".

## 0.14.0 (2026-11-04)

Runners on several machines share one `[plan] repo` without stepping on each other.

- **Clashing claims settle.** Two runs that claim different tasks with overlapping files (or an ordered
  section, or a family) from plans read seconds apart both push, then both see both claims: the later
  claim gives way and the run picks again.
- **Claims hold touched files.** Each refresh adds the files the task's session has changed (its branch
  past main, and the slot's uncommitted and untracked edits), so a task line that lists too few files, or
  none, still keeps other runs off them.
- **Version in claims.** A claim records the runner's version and when it was claimed; `plan` and
  `plan claims` show it. A live claim from a runner older than 0.14 (which ignores other runs' files) is
  warned of once per run: upgrade every machine.
- **Faster dead-run recovery.** Claims refresh every 15 min (was 1 h) and go stale after 90 min (was 3 h).
  0.13 runners still refresh hourly, which stays inside 90 min.
- **No orphan claims.** A run's refresh drops its own claims on tasks it neither runs, queues nor holds an
  unmerged branch for, and a blocked task's finished branch (a concept round that ended while no run was
  up) is merged instead of sitting, claimed, for good.
- The claim file gains three lines (version, claimed at, files); 0.13 reads the first three as before.

## 0.13.4 (2026-11-04)

- A session whose `done` succeeded and that then sits quiet at its prompt past `[run] stall` is ended by the run
  itself, not just reported as stalled. The Stop hook's detached waiter can be lost, and two finished sessions
  held their slots for 5 and 8 hours.

## 0.13.3 (2026-11-04)

- Two runners on one `[plan] repo` keep off each other's files: another run's live claim counts as running
  here, so a task sharing its files, ordered section or family waits, not just the claimed task itself.
  A stale claim (a crashed run's) still holds only its own task.
- `dir/**` and `dir/*` on a task line are file patterns: they reserve everything under the folder, files
  that exist only on another branch included, and overlap the paths and patterns they match.

## 0.13.2 (2026-11-04)

- `run` no longer crashes starting a task when a worktree's folder was deleted without `git worktree remove`
  (a chat session's scratchpad, say): the edited-elsewhere check skips worktrees git lists as prunable.

## 0.13.1 (2026-11-03)

- `agent-runner home [slots|plan]` prints where this project's runner files are, from `[run] home` and
  `AGENT_RUNNER_HOME`, so a project's scripts (an emulator per slot, say) ask instead of rebuilding the path.

## 0.13.0 (2026-11-03)

- `[run] home` (default `~/runs/{repo}`) holds a project's worktrees (`s1`…, `merge`) and its `[plan] repo`
  clone (`plan/`), so the repos folder keeps only checkouts. `AGENT_RUNNER_HOME` overrides it on one machine.
  Worktrees in the old `<repo>-slots/` and a clone in `~/.cache/agent-runner/` keep being used until they are
  moved (`git worktree move`, a plain `mv` for the clone), with no run going.

## 0.12.0 (2026-11-03)

- `[plan] journal_layout = "id"`: one journal folder per task, `journal/<ID>/notes.md`, a retry in
  `journal/<ID>/<date>-<slug>/notes.md`. The prompt names that place, and the brief finds a `journal/<ID>/`
  folder and pastes its newest entry (a dated one beats an undated one). The default, `dated`, is unchanged.

## 0.11.1 (2026-11-03)

- A worktree over `slot_max_gb` is trimmed, not wiped: its least recently written git-ignored parts (folders
  split up to three levels, nothing under 1/500 of the cap) go until it is at half the cap, so the builds
  recent tasks used stay warm. On one project's slots that dropped old-hash library copies and stale
  cross-platform targets, 67 GB to 25 GB, and kept the live builds. The whole `git clean` stays for a disk
  under `min_free_gb`.

## 0.11.0 (2026-11-03)

- Worktrees no longer fill the disk. A slot or merge worktree over `[run] slot_max_gb` (default 50) is cleaned
  before its next task; under `[run] min_free_gb` (default 10) free, every free worktree is cleaned and no new
  task starts until there is room; slots past the run's count are removed once nothing uses them. The clean
  is `git clean -ffdXq` (every git-ignored file; `links` come back), or `[run] slot_clean`. Set either limit to
  0 for the old behaviour. One project's slots had grown to hundreds of GB of task-specific build folders.

## 0.10.0 (2026-11-03)

- `[plan] outline`: a command that prints one file's outline (`{file}` is the path). The brief shows it
  under each file the task line names, so a session starts with the map of what is where instead of
  paging through files to find its way. Each project supplies its own; unset, briefs are as before.
- `agent-runner cost`: where the workers' tokens go, per kind of tool call (a Bash command by program and
  subcommand or script, other tools by name), weighed by result size times the turns it stays in context.
  Reads Claude and Pi transcripts: by default the last 7 days of this repo's slot and merge sessions.

## 0.9.2 (2026-11-03)

- `[git] master_branch` optionally selects the local branch task worktrees use and tested merges target.
  It overrides remote `HEAD` discovery and fails before a run starts if the branch is missing or not checked out.
- The runner test suite passes on Windows.

## 0.9.1 (2026-11-03)

- `[plan] repo`: `plan` shows who has each claimed task and since when; `plan claims` lists them and
  `plan unclaim <ID>` drops one. A run re-stamps its own claims hourly, and logs once for each other claim
  unrefreshed for 3 h (STALE), so a crashed run on another machine no longer holds its tasks unseen.
- A run no longer starts a task that someone ticked or blocked in the seconds since its pick last read the
  plan: the claim pulls, and the task is checked again before it starts.

## 0.9.0 (2026-11-03)

- A task's long form moves to `plan/tasks/<ID>.md`, so the plan's top level is TODO.md, DONE.md and the
  overviews a person reads. Briefs, `plan <ID>`, ticks and CI-filed tasks use it; a long form still at
  `plan/<ID>.md` keeps working until it is moved (`git mv plan/<ID>.md plan/tasks/`).

## 0.8.0 (2026-11-03)

- `[plan] repo`: the plan in its own git repo, so several people and runners share one queue instead of a
  copy per branch (#3). Reads pull, edits push (a rejected push merges by line and retries), a run claims a
  task (`claims/<ID>`, pushed as it picks; offline it starts nothing) so two users' runs never take the same one, and a slot's `done` is ticked
  only once its merge lands, noting `landed <sha>`. `[plan] dir` may now be outside the repo (`~/…`) on
  its own too. Unset, nothing changes.

## 0.7.3 (2026-11-02)

- `[run] ci_watch`: a run reads the shared branch's GitHub Actions results (`gh run list`, every 5 min, never
  holding up a landing) and files one `critical` task for a red workflow run, with its failed jobs and the
  last lines of `--log-failed` in the task's long form; none again while it is open. openmx's pages.yml had
  been red on every push for two days, and its only sign was an email per push. `[run] ci_kind` (B) is
  the task's prefix.

## 0.7.2 (2026-11-02)

- Claude sessions no longer stop on a startup dialog nobody is there to answer. Lean mode leaves out user
  settings, so a session now passes `skipDangerousModePermissionPrompt` itself, and each slot and merge
  worktree is marked trusted in `~/.claude.json` (or `$CLAUDE_CONFIG_DIR`) before a session starts there.

## 0.7.1 (2026-11-01)

- Claude Code (Opus) is the default and needs no configuration; Pi is the way to other providers. The README
  and SETUP say so, and that Pi on an Anthropic model bills extra usage rather than the plan.
- Pi sessions run the repo's Claude Code PreToolUse hooks (`pi_hooks.ts`: exit 2 or a deny blocks the call,
  an updated command replaces it), so a repo's guards hold in Pi slots and fix sessions.
- `AGENT_RUNNER_BACKEND=claude|pi` picks the backend for one run, the repo's config otherwise kept.

## 0.7.0 (2026-10-30)

- A Pi backend (`[run] backend = "pi"`, or an `agent` executable named `pi`): provider-qualified models
  (GitHub Copilot, enterprise Copilot, Codex and other Pi logins), prompts by file at any size, retained
  sessions for resume and restart adoption, transcript statistics and stall checks. Claude stays the
  default. Setup, enterprise Copilot included: docs/SETUP.md.
- Pi sessions run interactive in their panes, watchable and takeable like Claude's; the bundled
  `pi_idle.ts` extension ends one after `idle` seconds settled at the prompt, not while text sits in the
  editor. Fix sessions use the `master-<repo>` window under tmux, print mode without it.
- Each agent CLI is a backend class (`Claude`, `Pi`) in `runner.py`; adding one is a subclass, see
  docs/AGENTS-EVAL.md. A fix session without tmux gets `slot_env`'s non-slot settings for Claude too.
- Claude: a brief too long for one command-line argument (96 KB on Linux, 24 000 characters on Windows) goes
  in whole as the system prompt (`--append-system-prompt-file <notes>/<sid>.brief`, given again on every
  resume), instead of a pointer the agent had to page through with Read. The file goes when the session ends.
- `docs/AGENTS-EVAL.md`: what a backend must support, candidate terminal agents (Copilot CLI, Codex,
  opencode, Arctic, Crush) by login type, and a test plan; `tests/agent_matrix.py` probes them. First
  live results: Pi and Copilot CLI pass the headless checks; Pi completes `run once` end to end.

## 0.6.34 (2026-10-29)

- The stall warning counts a session's quiet at a prompt from the end of its last tool run, not from its
  last transcript write. A tool's run writes nothing, so a long test run followed by a moment between
  commands was reported as "no transcript activity for 22 min at a prompt": openmx's P38, mid-gate.

## 0.6.33 (2026-10-29)

- `plan add <ID>`, a task split into subtasks, files them after the task and its earlier subtasks, under the
  task's own level tag or none, unless `--pri` or `@` says otherwise. Before, an agent's split was a `normal`
  follow-up like any other, so the rest of a person's task queued behind every follow-up: openmx's S149a-e.
  The prompt says to split this way.

## 0.6.32 (2026-10-29)

- Joining a task list keeps each task in the section the target files it under (the branch's, for the
  branch's own task), and moves a task's indented lines with it. Before, a doubled task stayed where its
  first copy was, so a branch cut before the plan was re-sorted put the old order back on merge: openmx's
  P185 moved 51 follow-ups back into Next.

## 0.6.31 (2026-10-29)

- A task whose text names a common file only in passing (`README.md`, in a spec) no longer lists every
  file of that name: a bare name that more than `BARE_MAX` (5) tracked paths share is prose, unless the
  line's `→` list names it, and that list now ends with its line instead of running on into the
  task's appended `plan/<ID>.md`. One openmx brief went from 597 READMEs and 129 KB to 9 KB.
- A prompt past 96 KiB reaches the agent as a short first turn pointing at `<notes>/<slot>.prompt`, as on
  Windows: Linux takes one argument of 128 KiB at most, and the session died at once ("Argument list too
  long", logged as "exited (no transcript)") every time the task came up.
- `plan brief` no longer crashes on a `j:` field when no journal directory is configured.

## 0.6.30 (2026-10-29)

- A restart never resumes a session that is still running. A slot whose last session's id is on a live
  process's command line (a pane opened before 0.6.20, untagged, so `adopt` cannot see it) is held, with
  a log line saying how to tag the pane, until that process ends; before, the run took its mid-turn
  transcript as cut off and resumed a second agent in the same worktree.

## 0.6.29 (2026-10-29)

- Follow-ups have a level: `plan add PREFIX TEXT --pri critical|normal|low|later`, tagged
  `(follow-up, LEVEL)` on the line. An agent's default is `normal`, which now files in `### Follow-ups`
  after every section a person queued, not at the bottom of the leading section (where it went ahead of
  them); `low` goes behind the normal ones, `critical` to the top, `later` to `### Parked`, which a run
  never starts. A person's task still goes to the top, untagged.
- Id prefixes name a kind of work: `[plan] kinds` (a table, letter -> meaning), shown in the prompt and
  by `plan kinds`; `plan add` refuses a letter it lacks. Without it the generic B/F/T/D/R/C are suggested.
- A test that failed and then passed alone gets a critical follow-up (`[run] flaky_kind`, default T) to
  make it robust when its merge lands; `[run] flaky` finds the same in a passing gate's own reruns.
- The prompt's follow-up paragraph is `{followups}`, for custom templates.

## 0.6.28 (2026-10-28)

- The runner ends what a finished session left running. Ending a session only ended the agent, so its
  tools' processes lived on under init: partyboard collected Gradle daemons and `find /` crawls that
  walked an sftp mount for up to 21 h, about 5 GB and two cores between them. Every process carrying
  `AGENT_RUNNER=1` and the session id of an agent no longer running is now sent SIGTERM (SIGKILL 5 s
  later) when a slot exits and at each temp sweep. POSIX only.

## 0.6.27 (2026-10-28)

- Prompt: every wait gets a time limit, and no whole-disk `find /`. partyboard N91 piled up
  `until grep "<line>" <log>` loops for over an hour after the runs they watched had died, and N97 crawled
  `/` for half an hour looking for one file.

## 0.6.26 (2026-10-28)

- The prompt's process rule is now: wait for and kill only the pids you started, never match processes
  by a command-line pattern. 0.6.25 suggested `tail --pid=...` for waiting; an agent then cleaned up with
  `ps | awk '/tail --pid/'` + `kill`, which matched every session's command line (each holds the whole
  prompt) and ended all three running sessions at once (partyboard N86, N90, N93; their work was kept on
  wip/ branches).

## 0.6.25 (2026-10-28)

- The session prompt tells agents to wait on a pid or `pgrep -x <name>`, never `until ! pgrep -f
  '<pattern>'`: the loop's own command line matches the pattern, so it never ends. Twice in partyboard
  (N35, N87) a session sat for 15-25 minutes on such loops, once before its `done`, where 0.6.22's
  finished mark can't help.

## 0.6.24 (2026-10-28)

- No more empty leftover branches. A slot whose only "change" is something a commit can't hold (a
  submodule edited inside, e.g. patches a build applies to it) showed in `git status`, so every reset
  saved an empty `wip/` or `leftover/` commit and pushed it: partyboard collected 87 of them. The save now
  keeps nothing when the snapshot's tree is HEAD's.

## 0.6.23 (2026-10-27)

- 0.6.22 still let a finished task sit for half an hour: a session with background tasks got the 30 min
  `AGENT_RUNNER_IDLE_BG` grace before the waiter first looked at the finished mark. Once `done` has
  succeeded the stop hook now hands the waiter the normal idle time.

## 0.6.22 (2026-10-27)

- A finished task no longer holds its slot. A successful `done` leaves `slot<N>.finished` in the notes
  folder (slots get `AGENT_RUNNER_SLOT`), and the idle stop then ends the session even when the agent still
  has a child process. Before, a leftover background command (a wait loop whose `pgrep -f` matched itself)
  kept a finished session alive for up to `AGENT_RUNNER_IDLE_MAX` (3 h). A slot clears the mark when it
  starts its next task.

## 0.6.21 (2026-10-27)

- A pane is a runner's only when its `@runner-repo` names that runner's main checkout; 0.6.20's
  fallback for untagged panes (by working directory) is gone. A pane opened before 0.6.20 is no one's:
  let its session end, or tag it (`tmux set-option -p -t <pane> @runner-repo <main checkout>`), before
  restarting a run.

## 0.6.20 (2026-10-27)

- Runners for different repos can share one tmux session. A pane now carries the repo it works for
  (`@runner-repo`, its main checkout), and each repo gets its own windows, `agents-<repo>` and
  `master-<repo>`. A restart adopts, holds and lays out only its own repo's panes; before, a second repo's
  runner adopted the first's `s1` (a task of the same id), held its `s2`/`s3` as "untracked sessions", and
  split its own panes into the first's `agents` window.

## 0.6.19 (2026-10-27)

- A run says when `main` has a newer version than the one running, with the command to upgrade
  (`pipx upgrade agent-runner`, `uv tool upgrade agent-runner`, or `git pull` in a clone). One read of
  `main`'s version, in the background, 5 s at most; silent when offline.

## 0.6.18 (2026-10-27)

- Each merge fetches the remote's shared branch first and, when it has commits the local one lacks, merges
  them into the merge before the gate (joined, or given to a fix session on a conflict). The gate tests
  both and the push goes through, instead of failing on a remote that moved.

## 0.6.17 (2026-10-27)

- No behaviour change: a simpler runner. Fewer git calls per scheduling tick: `pick` reads the tracked
  files once for every task line (`plan.files_on_line` takes them as `tracked=`), and one
  `git for-each-ref --no-merged` finds the finished `task/<ID>` branches for `pick` and `unmerged`, where
  each branch had a `rev-list` or `git log` of its own. The end of a tick picks at most once, not three times.
- The plan's 5 s read cache is gone (`plan.lines` reads the file): a read is cheap now that a tick makes
  few, and nothing has to clear it.
- A transcript's path is kept once found, so a stall check no longer globs `~/.claude/projects/*/` for
  every slot every 10 s.
- `plat.mux_choice` lost its unused `slots` argument; `gitops.shared_name` takes the name to fall back to.

## 0.6.16 (2026-10-27)

- A merge skips the gate only when `task/<ID>` is the tree `done`'s gate passed on, which `done` now records
  as `refs/agent-runner/tested/<ID>`. Before, any merge differing from the branch only in `[run] untested`
  files skipped it, so a fast-forward of a branch committed after `done`, by `done --no-test`, or by a
  session that never ran `done` was pushed untested.
- Rerunning failed tests on the base resets the merge worktree first and checks the checkout: a gate that
  left a tracked file edited made the checkout refuse, the "base" rerun ran on the merge, and a real
  failure read as "already fail without it; merged anyway".
- tmux refusing a pane fails that one start, or that fix or repair session (the merge is left for a human
  as for any failed fix), instead of ending the run or silently killing the merge thread.
- `[run] timeout` (3600 s): the gate, a retest, a `[run.join]` command, `before_start` and the sequential
  run's `on_exit` past it are stopped and count as failed. Pushes and fetches get no stdin, no password or
  ssh prompt (`GIT_TERMINAL_PROMPT=0`, `ssh -oBatchMode=yes` unless an ssh command is configured) and 300 s.
- Anything staged in the main checkout holds a tested merge, as edits to its files do: git refuses to
  merge onto it, and the merge was rebuilt, gated and refused every 10 min.
- A main checkout with another branch out is no longer switched to `main` to land a merge, carrying
  whatever was uncommitted there; the merge stays `task/<ID>` until `main` is out again.
- An earlier `wip/<ID>`, `leftover/<ID>` or `resumed/<ID>` is never overwritten: the new one is `-2`, `-3`, ….
- A `done` whose commit fails puts the plan back as it was, so it can run again (it said "no task <ID>").
- A slot asleep until a usage-limit reset lets go of `task/<ID>`, so another slot can take the task.
- When the remote's shared branch has moved, the runner's push no longer merges it into the main checkout
  and pushes that untested merge; it says so (0.6.18: the next merge takes it in).
- A SIGTERM or SIGHUP ends the run as Ctrl-C does, and either one waits up to a minute for a merge open in
  the main checkout to be committed or aborted first.
- The temp sweep matches only the slots' and the merge worktree's folders, not a sibling repo whose name
  starts the same, and never the main checkout's, where an interactive session has no session id to see.
- On Windows the runner's own command is quoted for Git Bash when a path has `'`, `$`, `` ` `` or `;`.

## 0.6.15 (2026-10-27)

- `plan add` names an open task that looks like the same work, with its id and the start of its text,
  under the new id. Nothing is printed when none does, so an agent's context pays only on a match: the
  new task's rarer words mostly on the other (half of them, weighted by how few tasks use them), or 30%
  of them plus a file that at most three open tasks name. Done tasks are not compared.
- Starting a task, the run logs any checkout outside its slots (the main checkout, a person's or a chat
  session's worktree) with uncommitted edits to the task's files: work there is invisible to the runner,
  and on 2026-10-26 two hand-made fixes sat uncommitted while the runners did the same two tasks.

## 0.6.14 (2026-10-26)

- A session's temp folder (`<tmp>/claude-<uid>/<project>/<session>/`: its scratchpad and background tasks'
  output) is deleted when the session ends for good. A session queued to resume keeps it. Claude Code
  never deletes these, and agents build in their scratchpads: here one tmpfs with a per-user quota reached
  EDQUOT holding 595 finished sessions' folders, 40 GB, 17 GB of it cargo target dirs.
- At startup and every 6 h the run also sweeps this repository's session folders (the main checkout's,
  the slots' and the merge worktree's) that no running process, no queued resume and no write in the last
  day claims: sessions that ended while no run was up, interactive ones, and those from before 0.6.14.
  Not on Windows, which has no /proc to tell a live session from an ended one.

## 0.6.13 (2026-10-24)

- Under tmux, fix and repair sessions are ordinary interactive sessions in a window named "master"
  instead of `claude -p`: you can watch one resolve a merge, or take it over by typing. Its Stop hook ends
  it 90 s after its answer, the runner then reads the merge worktree as before, and `fixer.log` gets the
  session id and its last words. There is no switch back to `-p`; only a run without tmux (Windows, the
  sequential run) still uses it, having no window to put the session in.

## 0.6.12 (2026-10-24)

- A batch that fails the gate gets one repair session for the whole batch before it is split: it sees every
  merge in it (`REPAIR_BATCH`), commits a fix on top, and the gate runs once more for all of them. Splitting
  cost every rider a gate run of its own and, for a clash between riders, a repair session each — in one
  night here every batch of fifteen failed to build together and went one by one.
- A rider whose conflict the line join cannot do gets a fix session inside the batch (`[run] fix_merges`),
  instead of waiting for its own turn and gate run.

## 0.6.11 (2026-10-24)

- A tested merge that cannot land only because of uncommitted edits in the main checkout is no longer
  parked as wip/<ID> after an hour. It waits 10 min holding MERGE, then gives the lock back; its branch
  stays task/<ID> (`pick` leaves it alone) and it is merged again, from a fresh build, as soon as the
  files it changes have no uncommitted edits (checked every minute). A stop leaves the branch for the next
  run's startup merge. Parking threw away finished, tested work for a fresh attempt: in one night an
  interactive session's uncommitted edits sent five finished tasks back to the queue, and serialised a
  dozen more behind an hour's wait each.

## 0.6.10 (2026-10-23)

- A merge that fails the gate gets one repair session before it is parked as wip/<ID>: a one-shot session
  like the fix session's, on the committed merge, with the gate's output (`.runner/merge-gate.log`). It
  commits a fix on top or says why not; the gate runs once more, and a second failure parks the branch as
  before. A clash git merges without a conflict (both sides adding one name, a caller of something the
  other side renamed) used to cost the whole task a fresh attempt. The repair is replayed when the merge is
  built again because the shared branch moved. `[run] repair_merges = false` turns it off.
- `[run] build`: a quick build (not the gate) the fix session runs before it commits, fixing what the two
  sides broke between them in files git merged on its own. Its prompt used to forbid any check, so it
  committed merges that did not compile.

## 0.6.9 (2026-10-23)

- A session cut off by an API error (the network dropped, `EAI_AGAIN`; the API down) is resumed in its own
  slot with `claude --resume` once the API answers, instead of being ended, its edits parked on wip/ and
  the task dropped for the run. At startup, a slot still on `task/<ID>` whose session stopped mid-turn
  while no run was up (a reboot) is resumed the same way. At most 3 resumes per session; a usage limit or
  a refused request is not a cut-off. No session starts or resumes while the API cannot be reached.
- `resume <ID>…` resumes a task's last session by hand once its slot is free, bringing its edits back
  from the wip/<ID> the runner saved.

## 0.6.8 (2026-10-23)

- A tested merge that cannot land yet says why, once, in the log (with a bell): uncommitted edits in the
  main checkout to the files the merge changes (named), or a merge of its own there. It used to wait up to
  60 min in silence, so the run looked hung with a finished task unmerged.
- A test gate that exits 130 without the run's Ctrl-C is a failure after 5 s. The merge thread used to
  wait on it forever.

## 0.6.7 (2026-10-22)

- A task a branch added under an id the target branch gave to another task meanwhile is renumbered (to
  the next id free on both sides) in a commit on top of the branch before each merge, and the lines the
  branch wrote that name it follow; logged as "renumbered P119 -> P122". Before, the join kept one line
  per id and silently dropped the branch's task.
- `plan tick` refuses an id listed twice as two tasks, instead of archiving one and leaving the other.

## 0.6.6 (2026-10-22)

- `plan add` run by an agent (`AGENT_RUNNER=1`) files its task at the bottom of the leading section, so
  follow-ups queue behind the work a person put there instead of jumping ahead of it. A person's `plan
  add` still goes to the top. `@ bottom` asks for the bottom either way.

## 0.6.5 (2026-10-22)

- The idle stop no longer ends a session whose agent is still running a background command: a `done`
  that waited past the 30 min background grace for a test slot was killed with its session, and its
  uncommitted work was lost. It waits for the command, up to `AGENT_RUNNER_IDLE_MAX` (10800 s).
- A session that ends with uncommitted edits has them saved before the slot is reset: on `wip/<ID>` when
  the task has no commits, else `leftover/<ID>`. Both are pushed and logged. `start` refuses to reset a
  slot whose edits could not be saved.

## 0.6.4 (2026-10-21)

- `agent-runner help` rewritten around real examples: running, adding tasks and subtasks, making one wait, finishing.
- `help order` and the README's *What runs when*: the order tasks start in, and the three ways to make one wait
  for another (subtask, `--after`, an ordered section).

## 0.6.3 (2026-10-21)

- `plan add`/`newid` on a task's own id give its next subtask (L3 -> L3a, L3a -> L3a1), which runs after its
  family instead of beside it; they used to give L31, a separate task that started at once.
- The top-level usage shows how to add a todo, and how to add one as a subtask.

## 0.6.2 (2026-10-21)

- The task prompt says commits in other repositories (a dependency or sibling repo the task needed) are pushed
  as usual; only this repo's main stays the runner's to merge. Publishing beyond git still needs the task to say so.

## 0.6.1 (2026-10-21)

- A merge that git rerere resolves entirely by itself is committed and no longer logged as an empty join.
- A merge git refuses to start (e.g. an untracked file in the way) parks the branch instead of being
  taken for a clean merge.

## 0.6.0 (2026-10-21)

- `run 1` and `run once` use a worktree, a pane and a tested merge like any other slot count; only
  `--no-tmux` (or no pane terminal installed) runs sessions in the checkout itself.
- `run once` exits when there is nothing it may start, and after its one task has merged.

## 0.5.0 (2026-10-21)

- Windows: ending a session first sends WM_CLOSE to every window in its process tree and gives those
  processes up to 10 s to exit (an emulator saves and shuts down), then `taskkill /T /F` as before.
- Windows: plan and journal paths handed to git, prompts and briefs use forward slashes, so `git show`
  and the plan-file union find TODO.md/DONE.md; `[run] retest` quotes `{names}` for cmd.exe.

## 0.4.1 (2026-10-20)

- A branch finished while no run was up is merged at startup even when its slot's worktree still has it
  checked out: idle slots are detached before the scan, not after it.

## 0.4.0 (2026-10-20)

- `run --shutdown`: power the computer off once nothing is running or merging and no open task can
  start (after 120 s idle). Blocked tasks don't keep it up.

## 0.3.1 (2026-10-20)

- Ctrl-C ends the run at once with one log line, no traceback and no second Ctrl-C; a gate it cut off
  isn't reported as a test failure.
- Slots start while branches finished before the run are still merging (the startup reopen no longer
  waits on the merge lock).
- The merge's test gate gets the `[run] slot_env` entries that aren't per slot (no `{n}`), e.g. a
  compiler cache, so it builds like the slots do.

## 0.3.0 (2026-10-20)

- Windows: a Windows Terminal tab per slot (`wt`), or a console window per slot when Windows Terminal
  isn't installed, through a slot shim that keeps each session's pid in `.runner/slotN.live`. The run
  lock, process checks, the Stop hook's timer and the end of a session work there too, from the
  standard library only. `[run] links` fall back to junctions and hard links without Developer Mode.
- `[run] mux` / `--mux tmux|wt|console|none` picks the terminal. The default is unchanged: tmux on
  Linux and macOS.
- `cmd_run(argv, prog=…)` and `cmd_stop(argv, prog=…)` take the wrapping CLI's name for `--help`;
  `stop` parses its arguments (`stop --help` no longer stops the run). Stop and idle messages name
  `[run] command`.

## 0.2.0 (2026-10-20)

From opentennis's `tools/parallel.py`, so it can switch over:

- Batch merges (`[run] batch`, on by default): finished branches waiting for the merge lock go in
  together under one gate run. A rider that conflicts beyond a join waits for its own turn, and a batch
  that fails the gate is split up.
- `[run] failures` + `retest`: a failure that passes when rerun alone counts as load. One the base
  already fails the same way merges anyway, and the ledger says so.
- `[run] untested`: globs (with `!`) for files the gate can't see; it used to be markdown only.
- `[run] before_start`: a check that holds new sessions (no display, device gone).
- `[run] not_attempt`: a regex on the last commit subject. Such a session, e.g. a spec phase, doesn't
  use up the task's one attempt.
- `[plan] brief`: the project's own brief command replaces the built-in brief.
- A restarted run adopts the sessions still running in its panes. A slot whose pane runs a session no
  run tracks is held, and a second `run` in the same repository refuses to start.
- The prompt goes through a file, because tmux's ~16 KB command limit broke long briefs.
- "(split into …)" parents wait for every subtask, blocked ones included, and tick themselves once those
  are done. A line that merely says "split into" isn't treated as a parent.

## 0.1.0 (2026-10-20)

The first release: the runner and plan tool out of openmx's and ps2-decomp-kit's `./kit run`, with
nothing game-specific in them.

- `run`, `plan`, `done` and `stop`: N sessions, one worktree and tmux pane per slot. A tested merge into
  the main checkout, then a push. One fix session per conflict, and `wip/<ID>` parking.
- The run stays up when it's idle and picks up a task a human unblocks (`retry_reopened`). From openmx
  9890a23.
- `s` + Enter in the runner's pane stops it gently, through the same STOP file as `run stop`. From
  openmx 0d94657 and ps2-decomp-kit 621e76e.
- A hand edit with `plan tick|block|…` in the main checkout commits at once, so a merge never waits on
  it.
- Packaging: `pyproject.toml` (stdlib only, Python ≥3.11) and an `agent-runner` console script.
  `python -m agent_runner` also works, and `./run` from a clone still works. There's an
  `agent_runner.__version__`, and `agent-runner --version` prints it.
- Config: `AGENT_RUNNER_CONFIG` names a file whose `[agent-runner]` table (or top level) replaces
  `runner.toml`, and the runner hands it on to every slot.
- Hooks for a wrapping project: `[run.join]` per-file joiners, the `[run] suspect` regex (flagged in
  the ledger), `[run] precommit` with `done --skip-check`, and `[run] command`. Also `[run] pass_env`,
  `{slots}` in `slot_env`, placeholders in `prompt_extra`, and `[plan] brief_extra`. `on_exit` now also
  gets the slot env in `run once`.
- Library API: the names in `__all__` of `agent_runner.plan`, `.done` and `.runner`. `plan.PROG` and
  `done.PROG` let a wrapper's messages name its own command.
