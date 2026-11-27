# Style rules

How the run app (`agent_runner/web_page.html` and its parts in `agent_runner/page/`, CSS and script files named by area, in the order they are joined by the server into one page (an area has several where its code sits among another's: moving it would change the cascade or the order scripts run); Runner Home's page too) looks, moves and speaks. Every change to it
follows these rules, and a change that needs a new rule writes it here in the same commit. The page's tests are one file per area,
`tests/test_web_<area>.py`, matching the parts (helpers shared by them are in `tests/_web.py`, which the gate does not
run as a suite); `test_style_f83` in `tests/test_web_shared.py` checks the ones a machine can check. The words for things are in [GLOSSARY.md](../GLOSSARY.md);
what the app does is in [REFERENCE.md](REFERENCE.md#the-run-app).

The terminal UI has its own colours (`theme.py`), but shares the words, the order of things, and the one list of run
controls (`ui_model.RUN_CONTROLS`).

## Ground rules

- **Calm.** The run is the subject. One accent, one action that stands out per card, no decoration that says nothing.
- **Phone first.** Draw it at 390px wide, then give it room. Nothing scrolls sideways but code. The layout switches on
  the app's own width (`@container (min-width:760px)`), never on the device's.
- **Both themes.** Every colour is a token with a light and a dark value. Look at both before you finish.
- **Say it once.** A fact, a control or a list lives in the snapshot (`ui_model.py`) and every view draws it from there.
- **Reuse.** Use a class or helper below before you write one. Two places that need the same thing share it.

## Tokens

All in `:root` at the top of the page's styles (`page/010-shared.css`). Outside `:root` there is no raw colour, no raw duration, and no
`border-radius` or `font-size` in px (a circle is `50%`; a `font:` shorthand for reading text, code or a text box may
name its own size).

| Tokens | Use |
|---|---|
| `--bg --side --surface --bubble` | page, sidebar, card, your own words and a pressed row |
| `--fg --muted --faint` | text, second text, placeholder and hint |
| `--line --line2` | a quiet edge, a control's edge |
| `--accent --accent2 --onaccent` | the one thing to press, its pressed shade, text on it |
| `--ok --warn --bad --onbad` | landed or running, needs you or paused, failed or destructive |
| `--kred --kblue --kpurple --kteal --kgreen --kgold --kindigo --kgray` | a task kind's colour in its chip (Kind chip), light and dark; never a state |
| `--scrim --shadow --lift` | behind a sheet, under a floating thing, under the message box |
| `--feed` | the ground behind a session: dark; the page's `--bg` for a session with the run's theme; white when the person's agent theme is light (see The session) |
| `--fs-xs --fs-s --fs-m --fs-n --fs-b --fs-l --fs-xl` | 11 hint, 12 badge, 13 second text, 14 button, 15 body, 17 card title, 30 greeting |
| `--r-xs --r-s --r-m --r-l --r-xl --r-full` | 4 a bar, 8 small control, 10 button and row, 16 card and sheet, 20 message box, pill |
| `--s1` to `--s6` | 4, 8, 12, 16, 24, 32: gaps and padding |
| `--tap` | 44px: the least a finger gets (40 in the message box's own row) |
| `--dur-fast --dur --dur-slow --dur-bars --dur-spring --ease --spring --spring-soft` | motion, below |

A state colour is never the only sign: there is a word or an icon with it. Text on `--bg` and `--surface` uses `--fg`
or `--muted`; `--faint` is for what you can do without.

Type: `--sans` for the app, `--serif` for headings and an ask's words, `--mono` for code, Talk's words and
a chat's message box (inside `.main.term`). A session draws its own text with ttyd (see The session).

## Parts

- **Button** (`.btn`): an action in words, a verb first. `.pri` the likely answer, `.acc` the one main action,
  `.bad` the Yes of a destructive confirm. At most one `.pri` or `.acc` in a card. An icon button (`.icon`, `.tool`)
  has an `aria-label` and a `title`; with no letter or digit its name shows as a Hint (below).
- **Hint** (`.hint`, `iconWords()`, `hintSpot()`, page/188-shared.js): every control with only an icon or a sign (no
  letter or digit in it) shows its `aria-label`, else its `title`, in one bubble, over it or under it, while a mouse
  hovers it (after 400 ms; the native title tooltip is held back meanwhile) or a finger or pen holds it (500 ms; it
  stays 1.2 s after the release). A hold that showed it presses nothing; moving over 9px cancels it; a tap is as
  before. The mic in "Hold to talk" keeps its own hold and shows none. It is automatic: a new icon-only control needs
  only an `aria-label` (tests/test_web_shared.py checks).
- **Kind chip** (`.kind`, `kindChip()`, `taskChip()`): a task's id as a chip with its kind's word in the kind's colour
  (`--kred` and the rest; a project's own kind is gray). It stands on the run page in Plan rows (before the title),
  Status's Working and Merging rows, the Needs you card and sheet (on the label's line), History rows and Concept cards. A
  release (V) is the one filled chip. The colour says the kind only, never the state: running, landed and stuck keep
  their own dot and words. A tool or pitch item has no task, so its plain id stays. In the terminal UI a queue row's
  id and word are in the kind's colour instead (a release filled); a panel under 36 columns wide has no word.
- **Setting question** (`.card.setask`, `askHTML()`; C55b): an unset setting listed in `SETTING_ASKS` shows above Settings' rows as its name, its words and one button per answer (On, Off). A press saves through the usual Save and the card goes. It is not a Needs you item and holds nothing.
- **Card** (`.card`, `card()`): one thing. `.tap` opens something; `.need` waits on the person. Title, one line of
  second text, then `.btns`.
- **Needs you item** (`.asktap`, `needTap()`): one button, not a card of buttons. What is wanted and where in everyday
  words (`.asklab`), with its task's kind chip on that line (Kind chip), what is asked (`needHead()`, `.q`: a DECIDE's
  question, any other item's summary), its task's title small under it (`needTitle()`, left out when it says the
  same; an item with an explanation (`detail.text`) has its session and project there instead), a DECIDE's background
  (`.askdo`), then an explanation's first sentence (`explainFirst()`, `.askdo`), then Press for details, the steps count and the age. Nothing of it is cut: no ellipsis and no line clamp, on the card or in
  the sheet; an explanation shows only its first sentence here, the rest in the sheet. Its answer buttons sit below it. A DECIDE's options are its answer buttons, the recommended first, marked "(recommended)" and `.pri`. A pick
  sheet's start with "Go with the recommended picks" (`.pri`), then, for one question, its answers the same way. A
  device's or tool's Use or Open NAME in Tools (`needDevices()`) is a plain button, not `.pri`.
- **Needs you sheet** (`SHEETS.need`, `needSheet()`): the whole ask in order: what is asked, its task's
  title small under it as on the card, label (with its kind chip, as on the card), age; the explanation first in the body (`.explain`, `needExplain()`: text over EXPLAIN_LONG, 600 characters, is cut at a block, else at a sentence, the rest in a fold, "The rest of the explanation"); Why (a BLOCKED item's, left out when the heading says it); where and when, or a DECIDE's background as paragraphs; What to do (a DECIDE's
  only when its ask file has steps); What you should see; notes; videos (`.shotvideo`, `needVideos()`, played in place above the pictures; a redraw leaves a playing one alone, `videoHTML()`, closing the sheet pauses it, and a swipe that starts on one is the video's); pictures (`.shot`, full size inside the sheet, Back or
  Esc goes back); the
  task text folded, left out of an item with an explanation (Full task). An item with inputs draws its steps with Open (a step's link) and the command as code, with
  "Run on <machine>" and Copy; then What you should see; then What to enter, one field per input (its label above it;
  a secret is a password field, and over plain http words stand in its place and say why), a refusal in `--bad` under
  its field; then one Done (`.pri`), all in the body. A confirm question takes Done's place (Yes, send it / No). There
  are no plain answers on its card or sheet and no reply box: Later, Chat and Drop stand at the foot (`.askfoot.end`),
  not sticky, so they never cover a field.
- **Concept frame** (`.cframe`, `conceptFrame()`): a concept item's Needs you card shows its options page under the
  summary, framed from the run page's own copy (`/concept/<K id>`, sandboxed, lazy): the card's width, 60vh, `--r-m`,
  a `--line` edge. Expand (Shrink once open) gives it the screen's height; Open in claude.ai stands beside it when there is a page there.
- **Chat's question under Needs you** (`chatNeedCard()`, `data-k="chatneed:…"`, B832): a `need` card above the filed items: the question in bold (3 lines at most, `ell2`), the chat's name · age small under it, Chat (`data-thread`) at the right; the option buttons in one `.btns` row, the recommended first, `.pri` and "(recommended)"; then one line of an answer field and Send. An option turns the buttons into Sending "the option" with Undo for `QUESTION_HOLD`, as the question card.
- **Question card** (`.qcard`, `questionCard()`, `questionHTML()`): in a chat whose last answer asks a question with options (/live's `ask`), it stands in the dock over the chips, and the message box stays under it. The question in `.q`, then one full-width button of `--tap` height per option, the recommended first, marked "(recommended)" and `.pri`; a tall card scrolls inside itself. A tap turns the card into one row, Sending "the option" with Undo (`.qheld`): nothing is sent for 5 s (`QUESTION_HOLD`), and Undo brings the card back. Then the answer goes through `outbox()` as the person's message, queued while the session works and never forced. A card whose ask is filed under Needs you (it has `need`, F192a3) sends it as `question_answer` in place of the person's message, which settles that item as its answer button does; the chat is told by the runner's settled line, not typed the option too. A press within 500 ms of the swap does nothing (`QUESTION_AGAIN`), so a double tap neither undoes nor picks. A typed message takes the card away at once. A question that goes, or is answered in words, during the hold takes the held answer along, unsent, with a toast; leaving the chat does not cancel the hold, a reload does. An answer given under Needs you (also while it is still sending) takes away the card and the mark (/live's `answered`), also over a reload; a held option is then not sent. The card is gone once answered, and back if its message is discarded in the outbox, or, for a Needs you answer, once /live still says it. Motion: the card fades in and rises 14px on `--dur`, and the frame glides with the dock (`feedGlide()`), except when the chat was just opened; `questionMove()` does both. A − (`data-qmin`, "Minimize question", `--tap` by `--tap`) stands at the card's top right beside the question; a tap makes the card one line (`.qmin`): the question cut with an ellipsis (`--fs-m`, `--muted`) and a ^ (`data-qshow`, "Show question", `--tap`) that opens it again. It is kept over a redraw and a reload per browser and project, by chat and question id (`QN.min`, 096-dismiss.js, the latest 100; other tabs follow). It sends, queues and answers nothing, so the question is still filed under Needs you; a later question comes open. The held row is always whole, and neither it nor the Marked question has a −: the mark's ✕ is Back to the question. Pressed with a key, focus goes to the other of the two buttons. The `QUESTION_AGAIN` rule (500 ms) covers both, and after either press no option, − or ^ takes a press for 500 ms, so a double tap does not press what came under the finger. In a tall card the − scrolls with the question. A redraw of the dock keeps the card's scroll place, per chat and question (`QPLACE`, 097-question-place.js). With the keyboard up the card is at most 40% of the app's height, the mark 25% (140px at most). Motion as the card (`questionMove()`). A question dismissed before (the ✕ of F192b, now gone; `QN.gone`, only read) stays gone. While the card is open, the key row is hidden (see Key row). While the reader is scrolled up (in the history more than `QUESTION_EDGE` 24px from its end, the frame pulled that far, or the terminal itself scrolled: `FD.jump`, or Claude Code's Jump to bottom pill on a screen too low to find its prompt, `questionPill()`), the open card shrinks to its minimized line, the Decide pill (`QN.auto`, `questionScroll()`, F511); a line minimized by hand stays as it is. Back at the bottom (within 1px, for `QUESTION_BACK` 150 ms, so the edge does not flicker) the pill stays, and grows into the card on a tap or after `QUESTION_GROW` (2 s) still with no touch (a touch, press or wheel starts the wait again); it grows upward from where the pill stands, so nothing under the finger moves. A held answer (Sending, Undo) always stays, and so does the mark; the bars stay while it is held (`slimMay()`). The jump button floats over what is still visible (`questionRoom()`).
- **Chat about this** (`.qchat`, `.qabout`, `questionChat()`, `questionMarkHTML()`, `questionGo()`): the card's last button, full width and quiet (`--muted`, no edge), so it is not taken for an option. A tap puts the mark in the card's place: one row, "Chat about this, not your answer", the whole question (a long one scrolls inside the mark), and a ✕ of `--tap` size, "Back to the question", which brings the card back and keeps the typed words; the message box gets the focus in the tap itself (phone keyboard). The mark belongs to its chat and lasts over a reload, as the draft does. The words go through `outbox()` as an ordinary message led by `About your question “…” (not my answer): `, never as the answer; a slash command goes as it is and the mark stays. After the send the card is back at once, and stays, over a reload and on every device: the question stays /live's ask (`chat_question.ask` reads past the messages about it and the replies to them) until it is answered (an option, or a message typed without the mark, here, in the terminal or on another device), or another question is asked. The page keeps no copy of it. Queued words that /live cannot read (a message with an image, any on the harness loop) hide it until they go in. A failed message taken back into the box has its mark again (`obEditBack`). A question answered elsewhere while marked does not come back. Motion: as the card (`questionMove()`). A second press within `QUESTION_AGAIN` does nothing.
- **Row** (`.row`, `.crow`, `.prow`, `.srow`, its folding head `.fold`): one line when folded, with an ellipsis. A row that holds more folds
  open on tap in place (`aria-expanded`), and its chevron turns. A setting's row (`.srow`) shows its name, its description and its control; it opens to show the code name, More… (a sheet with the other home and Reset) and "Ask a chat to change it", on every row. The Settings page's first control is "Ask about my settings" (F449): like New concept it opens a new chat at once, but with its first message already in the box to edit; nothing is sent before Send. No group is read only (F448b): a row that cannot change now shows its value and the reason (`.setlock`, `--muted`) in place of its control; a risky row's warning (`.setwarn`, `--warn`) shows once it is changed or open; a list or table is a `textarea.setlong` as wide as the row. A changed row says "Not saved yet" until the bar saves it. In Plan and Status one row of a list is open at a time (`S.taskOpen[list]`); opening another closes it and the pressed row stays in view (`taskInView()`); a task is open in one list only, so its question is asked once; a release row is in the Queue's list, so opening one closes an open task there and the other way round. Chat is the last button of a task's actions. In Plan a task or release row's head `.fold` (its kind chip first, then the title) is a real button and the row's one focusable control (Enter opens it), and holds no other control: a tap on its words opens its details in place; buttons, a grip, a menu button or icons stand beside it, never in it, so pressing them opens nothing.
- **Plan search** (`.planq`): sticks to the top of the view, outside `.col` because a sticky grid item stays in its own row; on `--bg`, and nothing else sticks there.
- **Work page** (F476, `workHTML()`, `agent_runner/page/145-work.js`; the `plan` view, NAV label Work): Status, Plan and History in one timeline, top to bottom: the run's card and usage, Now (slot rows, then merge rows, as Status drew them), Pull requests while any is open, New release, Up next (the Queue's rows less those Now shows), Landed, Releases, each section a fold (`.secfold`, `workFold()`; Parked and Run log closed by default, the rest open; F487). Under the search a sticky row of jump buttons (`.workjump`, one small pill per section: 32px tall, `--fs-s`, transparent with a `--line` border, `--muted` words; the last pressed `.on` in `--accent` border and words, `aria-current`; scrolls sideways) opens its section and glides its head under the bar (`scrollGlide()`). A task shows in one section only. `status`, `history` and the older view names open it. In the Wait for… pick mode the row picked stays where it stood (`workKeepRow()`).
- **History search** (`.planq`, Find in history): the same sticky field as Plan search, its rows `.srow` with `.fold` heads in one card each for Landed and Releases; one row open per list, and a Landed or Releases row lists its options in this order: What changed (`.pri`), Report a problem, Chat last.
- **Concepts History** (F516, `conceptHistoryHTML()`, `.chist`, `.card.past`): past concepts whose page is still kept sit last in Concepts, in a fold titled History (closed at first), newest first; their rows are grayed and have View and Chat only, and they count nowhere a waiting concept counts.
- **Finished write-up** (F509, `taskBodyHTML()`): a landed task's row, folded open, shows what its agent said it did when it finished first (`.tasktext`), and the task's original text under a closed `<details class="asked">` fold titled Asked. A task with no write-up, and any open task, shows its text as before.
- **Settings bar** (`.setbar`, `setBarDraw()`): a row of its own under the Settings view, like the walkthrough, covering nothing. It says "N changes not saved" or "N changes saved", and when the draft holds both files' changes, how many each ("2 changes not saved: 1 project, 1 this device"), with Undo and one `.acc` (Save), and a close x after a save. No toast goes over it on a clean save, and it stays above the keyboard.
- **Settings tabs** (`.settabs`, `setTab()`, F462): two `.btn`s at the top of Settings, Project (runner.toml, everyone) and This device (runner.local.toml), `aria-pressed`, the one in view `.pri`; This device's label counts its own values ("This device · 2"). Every row's control edits the file of the tab in view, with no other home under More…. On Project a row this device overrides carries a marker (`.setover`, "This device: 5", `--warn`), a button that opens This device at that row; on This device a row with its own value says what the project has and has Reset, and a row without says it is the project's (`.setsame`, `--muted`). Changed counts per tab: the values that file sets. Project file stays under Project only. One draft serves both tabs, and the restart card shows under both.
- **Login row and sheet** (`loginNote()`, `.setlogin`, `SHEETS.login`): a provider's row says its state in words, not only colour (logged in and where, "Login under way", or what is needed), with the words on the left and one 44px button on the right (Log in, Log in again, Show the login). The one login sheet serves claude and every provider. A typed secret is a password field, sent only to the terminal and emptied at once; the terminal hides once the login is done.
- **Chat order** (`chatSort()`, `chatPlaces()`, `sideRows()`): pinned chats on top in their own order, then the rest newest to oldest by `at`; a chat with no `at` yet, or still starting, sits first under the pins. No row moves while it is dragged or pressed (`pressHeld()`, 15 s at most), nor while a chat's name is edited: what is new goes last in that row's list, and pins can't be dragged then.
- **Section** (`.sec`): a small muted heading and a line. Sections keep the TUI's order.
- **Sheet** (`#sheet`, `openSheet(name)`): more choices about what is on screen. It slides up from the bottom, groups
  its items (`.it`) under `.sec`, closes on the scrim, Esc, a swipe down, or a pick. One sheet, never a sheet over a
  sheet. Its markup comes from `SHEETS[name]()`. A button whose label ends in … opens one or folds open. A Needs you item's
  sheet is a centred dialog (`.dlg`) from 760px wide, not a sheet from the bottom. A sheet is visible from the first frame so it can take focus when it opens (its visibility is only animated on closing; no ring around the sheet itself), and closing gives focus back to what opened it while that is still drawn (a Needs you card, also when it was drawn again since).
- **Title switcher** (`SHEETS.chats`, `chatsSheet()`): a chat's title in the top bar, with a down chevron, opens the chats in
  the sidebar's order, each with its last line (`chatLast()`), a `.bdot` when it needs your reply, and a check on the open one.
  Rename this chat is at its foot. A tap on the title only opens the switcher; it does not rename.
- **Sent response row** (`responseRow()`, `responses()`, `quietRows()`, `.crow.response`, `.newlabel`, `responseHTML()`): a sent response (F425a) in the Chats list's Quiet group, and in the switcher with its second line "You: <answer>" (`.swc.response`). It has no row buttons (no pin, rename or delete). The dim "new" label (`.newlabel`, until the response is opened once per browser) is not a Dot or a Badge. Opening it never focuses the message box on touch.
- **All projects' Needs you row** (`askRow()`): what is asked is cut at 3 lines, as the question may be 2000 characters; Open has it whole. A stopped project's own page, with no Open, has it whole too.
- **Sidebar level** (`.slevel`, `.prow`, `sideShow()`): the sidebar's level is the view. The first row is All projects
  (`allRow()`, with a count of what needs you in other projects, hidden when Home lists one project); the level it
  opens is the project list (`allSide()`), and a project's own list turns it back. A `.prow` is one project: its state
  dot, its name, and a `.n` only for what needs you in that project. Badge rules apply as below.
- **+ button** (`.btn.plus`, `plusBtn()`): one per view, top right, its word kept on a phone (Project, Task, Concept,
  New talk, Device; Chat in an open chat and in a slot's session, where it starts a new chat at once). Elsewhere `+ Chat` stands
  only beside Chats in the sidebar. None in Settings or History, or in a new or starting chat. When the bar is tight the title shortens
  first (its switcher keeps 32px), then the run pill; the + never shrinks. + Task and this + Chat are disabled for 1 s after the file picker
  closes (`holdPlus()`), so a double press in the picker cannot land there; they come back by themselves, also while a redraw waits.
- **Project card** (`.pcard`, `projectCard()`): one project on the Overview or in a list: its state dot and name, its
  tasks by title, what landed today. One main button (`mainBtn()`: Start run or Open); the rest is in the
  … sheet (`dotsBtn()`), never beside it.
- **Device Vitals page** (`devHTML()`, `devSec()`, `.devcard`, `sparkHTML()`, `page/052-device.js`): a page under Devices; its top bar has Back to Devices after the menu and the machine's name as title, so the name is said once. A verdict card comes first (`devVerdict()`: the verdict, and "This one" under it when this is the open device), then one card per section under `.sec` (Headroom, Machine, Runner footprint, Sessions). Headroom says its own words only when they differ from the verdict. `.meter` for a share (no bar where none is read), `.lrow` for a name and its value. A meter's value is short; its details and sparkline (`.spark`, 28px, `--muted`, aria-hidden) stand under it as one part (`devPart()`, `.devpart`). A `.devcard`'s meters share its columns (subgrid), so bars start and end together; the Devices list's cards (`deviceCard()`) do the same. The Devices list has no `.sec` heading, its top bar's title says Devices. More/Less is a plain button (aria-expanded) above what it opens, in one button row with Clean. A device not answering shows its name, why in `--bad`, and Retry, with no sections; Home itself out of reach is an error card with Retry, and what was read stays. The open one stands in the history entry (`devHere()`), so Back and a reload keep it. Actions: + slot (`devSlots()`, plain buttons) sits in Headroom; Clean (`devCleanParts()`, its button beside More/Less, a `.devtick` label of --tap height with a native checkbox) in Runner footprint is a tick list that is its own confirm: Remove ticked is `.bad`, then Cancel. The list and ticks are frozen in `DV.pick`, so a refresh never changes them; the answer stands in the section (`devSaid()`), with a toast once the page has left that device. Home's own page at `#device-ID` opens it (`devLink()`).
- **Release card** (New release, `release_wait`, `release_now`): one line of what is open, then its buttons; the question takes their place; a press with a release open asks in place, Yes then No, and a Drop on a release that has not started asks its own question first. With Manage releases off (`releasesOn()`) it goes; an open release is a task in the Queue. New release is its own card above the Queue (`newReleaseCard()`). In the Queue each open release is a row at its place (`queueCard()`, `releaseRow()`); opened, the tasks it waits for sit indented under a rule (`.waits`), and Drop stands in the opened row with its own question. A shut release row on the run page never names its tasks: one short phrase (`Waits for everything above`, `Waits for 3 tasks`, `next`). The auto release's count is a dimmed dashed card (`.card.relph`) before the task it stands before, with no Releases heading.
- **Split row** (`planWords()`, `split_parts`, `split_ask`): a split task's row in the Plan queue reads `Split: 2 of 4 parts landed` in place of Ready or what it waits for; blocked, held, parked and running keep their own words. A Drop on it, parked too, asks with the open parts that stay named; the terminal UI has the same words, and its question names the parts by id alone to fit its one line.
- **Under-way row** (`planWords()`, `taskRow()`, `.waychat`, `ui_model_queue.under_way_rows`): the words `Taken by the chat <name>`, `Taken by a chat that has ended`, `Taken by hand`, `Merging` or `Waits to resume` in place of what it waits for; a running row (`s2 is on it`), a blocked one, a release's row, and a row that waits for the run to start with no run up keep their own words. Only a live chat's words are a button of their own (`.waychat`, `--tap` tall, underlined, chevron), under the head and never inside the `.fold`; all other wordings are plain text in the head.
- **Row menu** (`.qmenu`, `.qacts`, `rowMenu()`, `menuRows()`, `removedCard()`): three dots beside the head of each Plan queue row (a task, a release, the Next release row), never in the head `.fold`, so the dots and their icons open nothing. None on a running, merging or taken row, a parked row, a search hit, or a task listed inside an opened release. Pressed, the icons slide in from the right in the dots' place (translateX 24px and a fade on `--spring-soft`, as a chat row's; out again as a copy, `rowMenuOut()`; instant under `calm()`), and the chevron hides: hold (pause, or play while held), Wait for… (absent for a release, the Next release row, and a row that waits on the person or a check; it leaves the menu for the pick mode), to the top, remove. One row at a time; a press elsewhere closes it and also does its own thing (unlike a chat row's buttons, where a tap elsewhere only closes), and Esc closes it. Hold keeps the icons; the other two close them. No confirm question: Remove puts a removed card (Removed, Undo) in the row's place for 20 s (`PM_UNDO`), and Undo puts the row back where it stood. A double tap neither removes (a remove within 500 ms of opening is ignored, `PM_AGAIN`) nor undoes. Presses go through `outbox()`; the row itself is the stand-in, drawn at once and until the snapshot has it, and a failure takes it back and shows its card with Retry below the Queue. While the press is still sending, the dots (or the open icons) pulse as saving (`.saving`, `rowPress()`, `--pulse`); a success has no toast, as the row shows it, and a failure has one. A blocked row has remove too (Undo puts it back blocked, as it was), and a row that waits on the person has no hold. Every icon is `--tap` size with an aria-label (a Hint). Dimming on the Next release row is on its words, not its buttons.
- **Row grip** (`.grip`, `rowGrip()`, `gripRows()`, `gripMove()`, `gripDraw()`; `agent_runner/page/074-plan-grip.js`): six dots, 16px wide, in the card's left padding beside the head and never in the `.fold`, so a press on it opens nothing. On each Plan queue row (a task, a release, the Next release row) the server's `grip` says so (`ui_model_queue.grip_on`): every row but a started release (running, merging, taken, waiting to resume), a parked, removed (or one whose Remove was just undone, until the plan has it) or search row. A mouse drag past 4px lifts the row (a shadow, `.gripped`), and the other rows make room by transform on `--dur` and `--ease`; the row stays within the Queue, and the list scrolls when the mouse is within 56px of the view's edge. A redraw midway goes on from there. Esc, a window blur or a release outside the window puts the row back, and the click that ends a drag opens nothing. Arrow up or down with the grip focused moves the row one place, past the Next release row (it has no place of the plan), and the row stays in view; focus stays on the grip over a redraw. Subtasks go with their task. A move sends the `move` action through `outbox()`, after the row above or before the one below when it is first; a drop that changes nothing sends nothing. The row is drawn at once until the snapshot has it, and a failure takes it back and shows its card with Retry below the Queue. The Next release row moves once by that name: then it is a release, so a moved one has no grip until the snapshot has the release. With no fine pointer at all (`any-pointer`) the grip takes no presses (`pointer-events: none`), so it is no finger target.
- **Row lift** (`liftRow()`, `liftUp()`, `liftMove()`, `liftEnd()`; `agent_runner/page/076-plan-lift.js`): on touch, a finger held still for 350 ms on a Plan queue row that has a grip lifts it, and the finger then moves it as a mouse moves the grip: the same move, look and edge scroll. Moving 8px or more before the hold ends, any scroll, or a second finger means it never lifts in that touch. It does not start in the opened row's details (a hold there selects words) nor on another control (a hold shows its Hint), but does on the grip. Once lifted the touch is the row's until every finger lifts: no scroll, drawer swipe, pull or Hint. A second finger or a touchcancel puts the row back. Letting go presses nothing, so it opens no details, even if the row did not move; a drop in place sends nothing. The row's head selects no text on touch.
- **Parts list** (`.partsbar`, `.partsdone`, `.partdone`, `.card.part`, `partRows()`, `partsBar()`, `partCard()`; `agent_runner/page/079-plan-parts.js`): a split task is one card in the Plan queue, at the place of its first open part. Under its row a full-width bar with a chevron, "Parts, in the order they run"; under that its landed parts, ticked and dim, under a rule. Its open, parked and shelved parts follow as cards of their own, indented one step per level (its depth) with a rule on the left, each with its usual row, menu, buttons and grip; a part split again nests one step more. Open by default; shut is kept only until the page loads again, and the shut bar says "4 parts · F440b s1 is on it". Find a task opens a group that holds a match.
- **Wait for…** (`.waitset`, `.waitoff`, `.waittick`, `#waitbar.setbar`, `waitHTML()`, `waitCard()`, `waitNot()`, `waitRows()`, `waitBarDraw()`; `agent_runner/page/078-plan-wait.js`): rows become buttons with role=checkbox and a tick box, with no grip, menu or details. The row being set keeps its place with an accent edge and gets the focus; dimmed rows are aria-disabled with the reason in place of their state words; the Next release row is dimmed, with no pick. The bar is a .setbar row under the Plan view only, "What should B456 wait for?" with Cancel and Done (.acc). Esc cancels (search words, a sheet, the drawer or outbox come first). Focus stays on the ticked row over a redraw and returns to the dots at the end. Done with nothing changed sends nothing; otherwise the `set_waits` action goes through outbox(), the row itself is the stand-in until the snapshot has it, and a refusal takes it back and shows its card with Retry below the Queue. A task that starts or leaves the queue midway ends the mode with a toast.
- **Run card** (`controlsCard()`, `.btns.tight`, `CTL_ICON`): order top to bottom: state line, notices, the run's controls (slots change there). No slot rows on it: they are in Status's Working section. Each run control has an icon beside its word, never an icon alone: 15px, decorative (`aria-hidden`). A new control on the card gets an entry in `CTL_ICON`.
- **Agent row** (`slotRow()`, `mergeRow()`, `idleBody()`, `readText()`, `S.taskOpen.working` and `S.taskOpen.merging`): in Status, a row per slot under Working and per task under Merging, one open row per list, opened in place. A Working row's status says "Testing · N min" while its task's `done` gate runs, "Waiting to test" while that gate waits its turn (`shared_tools.gate_wait`), else "Working · N min" (`merge_rows.gate_phase()`; a dead gate never counts); the slot stays under Working. A Working row's options in this order: last words (`.quote`), Open session, Read task, Cancel (asks in the row), Drop, Chat last. A Merging row's: its step (the run log's last words on it since it left its slot; with none, one thing the run knows, `merge_rows.stage()`: "Testing the merge" when a gate runs on it, "Waiting to merge" when another task's merge is in its gate or being fixed, else "Not merged yet"), Open session (its slot's session, else its claude.ai link; none when neither), Read task, Chat. An idle slot's body says why nothing starts (`idleWhy()`: paused, stopping, an empty queue, or the counts of queued tasks by what they wait for), a note names the slot that goes when another works, then Remove a slot (the `slot_remove` control). Read task opens the task's text in the row under its options (`S.readTask`).
- **Pull request row** (`prRow()`, `.prlink`): Status's Pull requests section, after Merging, only while any is open; a `.srow` that is itself one link (opens GitHub in a new tab; at least `--tap` tall), not a fold: the first task's kind chip, title in one line with ellipsis, under it "#31 · CI red", the ext icon at the right. And in Needs you, a `PR` item's only button is Open; its sheet has no foot.
- **Device card** (`toolCard()`, `toolPage()`): a web page's state in a word with its colour on the address line, a
  failed one's last output lines in `.tasktext`, Start or Use is the `.pri` with Stop beside it; Test connection, Edit… and Remove in a
  row of their own below. The same web page part stands on a runner.toml tool's card when it has a `page`. The tool's own buttons (`pressHTML()`, `pressSaid()`, `.toolbtns`) are plain buttons in a row of their own after the web page part, on a device's and a runner.toml tool's card; never `.pri`. Labels wrap in the button, never cut or sideways. A question (its confirm, or "LABEL is held by HOLDER." with "Use it anyway") stands in the buttons' place: Yes is `.bad`, then No. Yes within `QUESTION_AGAIN` (500 ms) of the question does nothing, as a double tap. Press state is per tool (`S.press`), so one tool's long command holds no other. The answer (words, a failure in `--bad`, last lines in `.tasktext`) is the last thing on the card until that tool's next press. The device sheet's buttons come one group each ("Button N", Remove, then Label, Command, Question), with Add a button below, all saved with Save.
- **Walkthrough** (`.walk`, `walkDraw()`, `walkStep()`): one card at a time (`.walkcard`), only on the example project's
  page (`walkNow()` says when), never in a chat or Talk. Its row of its own under the view covers nothing, and goes while
  the keyboard is open. A 2px `--accent` ring (`[data-walkat]`) is on the real thing it points at. Back, Next and Skip
  (Done on the last) stand in it; Show me when the page is on another view. A press goes to the step's view with the
  thing on screen, and glides within one view; a redraw or a reload never moves the page for it. Home's offer of the
  example project is `exampleOffer()`. Its words are in `WALK_STEPS` (`page/084-walk.logic.js`, read by `walk.py`), the one list the page
  (`084-walk.logic.js`) and the terminal UI share: each step has the page's words and the keys' words, and each view shows
  only its own. The TUI draws it as a 'Walkthrough' box above the bottom line, keys as buttons, with ◂ after the pointed
  panel's name; on a small screen only the focused panel shows with it.
- **Home** (`homeHTML()`, `homeStart()`, `.talkbig`, `homeChips()`, `.sumrow`, `homeSums()`): the run page's Home, about the person: while no run is up, a Start card at the top (`data-k="start"`: Not running, one `.acc` Start the run, Starting the run… while it starts, or Not started: why with Retry and Discard in its place; it goes once the run is up), and Talk a plain button, so Home has one accent. With a run up, Talk is one full-width `.acc` (`.talkbig`), then the message box with no dictation button, the shortcut chips (`homeChips()`), Needs you, and one card of `.sumrow` rows that open Status and Plan (`homeSums()`).
- **Badge** (`.n`): a count of what waits on the person, never of anything else. **Dot** (`.bdot`): something
  waits, no count. **Pill** (`.pill`): a state in a word or two. Same words on every page: Running, Paused,
  Stopping, Caps forced, Not up.
- **Confirm**: asked in place (`sureHTML`), naming what is cut off, Yes then No. No browser dialog, ever. In the TUI
  the key is pressed twice.
- **Setting or form control**: a label, the control that fits the type (`.sw` switch, `.fld` select, number or text, or a `.step` stepper for a number changed a step at a time), then help in `.small`. A typed value is edited in the open row; a switch, select, stepper or Reset on a row only changes it until the Settings bar's Save (see Settings bar); a closed row shows no code name. A setting of two controls (`.setparts`) has them on a line of their own under its description, each with its label. Where one of the two is a switch that turns the count on, the switch comes first and the count shows only while it is on. A group's heading is its name only; the tab says the file (see Settings tabs). A field that must survive a refresh has `data-f="key"`. A new setting needs its words in `agent_runner/setting_words.py` (`tests/test_settings.py` checks). A setting picked from what is found on the machine (`agentField()`) has its select on a line of its own under the description, with its full path in `.small` under it (what is wrong goes in `--bad`). The kept value is always in the list, marked "(not found)" when it is wrong, and Other path… comes last and brings a field with no Save of its own; a refused path stays in the field.

## States

Every list and view has all four, drawn the same way:

- **Empty:** one calm sentence with its full stop (`emptyCard()`), and the way to add one when there is a way. Never a blank.
  Needs you has the same line in every view that lists it, `Nothing needs you.`, with no icon and no second line.
- **Loading:** `Loading…` in `.small`, only where nothing is there yet. Old content stays while new loads.
- **Working:** `.livedot` beside the words; a button that is sending is `.busy` and stays where it is.
- **Opening:** a press that leaves for another project's page marks it at once (`openProject()`, `.opening`): Opening… with
  a `.livedot` in the words of its row and card, its Open button `.busy`, the project's name in the sidebar (`.slevel`)
  when that is the project's level, and a toast when none of these is on screen. The mark goes when the page comes back,
  its load fails, or after `OPEN_MS`.
- **Starting:** a chat this page started reads `Starting the chat…` until its first reply or 2 minutes (`bornNow()`),
  never Loading or ended while its session comes up (F196).
- **Failed:** what did not happen and why, in `--bad`, with Retry or the way out. Nothing the person wrote is lost.

## Instant feedback

Every action the person takes goes through `outbox()`: the page draws the result at once as a stand-in, keeps the
action until the run answers, and sends it again after a lost connection. A card that was answered folds away at
once; its stand-in shows in the same place. A failure brings Retry, Edit or Discard. A message to a chat still starting stays pending, and the Outbox says it waits for the chat to start. `act()` is only for what has
nothing to draw (an interrupt, an order kept) and for Talk, which draws the person's words itself.

Home's own actions (start, pause, slots, stop) go through `homeAct()`, an outbox of their own shared by every page of
that Home, so one started before a switch to another project is still followed there. Home runs each one once, and a
failure brings Retry there too. A press on a device (`devPost()`) does not go through `outbox()` or `homeAct()`, as a resend could run it twice; its button is `.busy` and a failure leaves it there to press again.

A pressed run control (Pause, Go on, Force, Caps back on, Stop, Take the stop back, the slot ones) shows its result in
the same frame: its button turns into the other one, and the Run card's words, the state pill and Home's chip follow,
with a quiet mark (`Pausing…`). `ctlHold()` lays it over every older snapshot until one agrees or 15 s pass, then
the page shows what the run says with a plain error; a failure puts it back at once, with Retry on its card.

A secret never goes through `outbox()`, which the browser keeps: a device's change goes straight to the run
(`toolPost()`; its secret's field is emptied when sent), a tool button's press does too (`toolPress()`, never through `outbox()`, as a resend could run its command twice), and an input goes straight to the run too (`giveSend()`), a text or link as well. A refusal or a
question keeps what was typed, the secret too, while the sheet is open; a secret is forgotten when the sheet closes
(`giveForget()`), a text or link is kept. Once sent, all its fields and words go. No value goes in the markup, and a
saved secret is shown only as `set, changed <date>`.

## Words

- Plain words, a verb first on a button, sentence case, no exclamation marks, no dash between clauses.
- The glossary's term, and the same one everywhere: Needs you, slot, task, landed, concept, chat.
- A task is named by its title. Its id is the kind chip (Kind chip), not a small id after the title.
- Say what happens, in the person's terms: "Stop (running tasks finish)".
- Numbers with their unit: `6 min`, `2 of 3 slots`, `week 62%`.
- How long ago is `agoWords()` everywhere: `now`, `5 min`, `3 h` (hours until 48 h), `2 d`. A sentence adds `ago` (`checked 5 min ago`), never after `now` (`checked now`).

## Drawing

The page is drawn again from the snapshot, whole parts at a time. `setHTML()` draws a part only when its markup changed,
so markup holds no clock that ticks faster than a minute and no state a gesture is holding: what changes while a finger
is down (the mic, the drawer, the sheet) is set on the node that is there (`talkDraw()`). `render()` waits while a press or
a text selection is under way (15 s at most). The last snapshot seen is drawn first (`snapTake()`), before the run answers, and it holds
no token.

## Motion

Motion shows where a thing came from, where it went, or that it changed. Nothing else moves.

| Token | Value | For |
|---|---|---|
| `--dur-fast` | 150ms | a press, a chevron, a fade out, the jump button's fade (`.pastjump`) |
| `--dur` | 200ms | a card, row or message coming in, a cross-fade, a view's fade |
| `--dur-slow` | 250ms | what leaves collapsing, the scrim, the project list's slide (`.sghost`) |
| `--dur-bars` | 400ms | a session's bars going and coming back (`.slim`), the jump button's rise (`.pastjump`), and nothing else |
| `--dur-spring` | 450ms | the time of either spring |
| `--spring` | `linear()` curve, about 4% overshoot | cards, messages, pills, what glides, a press let go |
| `--spring-soft` | `linear()` curve, no overshoot | the drawer, the sheet and views, whose edge must not show a gap |
| `--ease` | `cubic-bezier(.2,.8,.2,1)` | fades and the rest: ease-out |
| `--pulse` | 1.6s | the one loop: work going on now, or the mic listening |

- **Springs.** Both are CSS `linear()` curves, with a `cubic-bezier` fallback for browsers without `linear()` (`@supports`).
- **Only `transform` (and `translate`), `opacity` and `clip-path`**, with `visibility` to take a closed thing out of reach, and a switch's
  `background-color`. Never height, width, top or margin; the scroll position is the one exception (see Scroll jumps). A transition's duration is a token, or a `calc()` share of one; the one raw duration allowed is `0s`, delayed by a token, to swap a stand-in in or out at the end of a motion. Every `el.animate()` goes through `moAnim()`, which reads the
  tokens and returns nothing when `calm()`; `kbGlide()` and the velocity spring `springRun()` check `calm()` themselves, and `feedGlide()` places the frame at once under it.
  `calm()` is reduced motion or a hidden page.
- **Views.** A chat opened from another view slides in from the right over the one that was there, and back slides it out,
  wherever it was pressed (a row, a card, Back, Esc). `viewGo()` runs this as a View Transition where the browser has
  them. Chat to chat there is no slide and no View Transition: the title, the box, the draft and the screen change at once,
  and the sidebar row's title does not fly to the top bar.
  Without View Transitions, with the keyboard open, or where focus must move in the tap (`about()`, new chat),
  `viewSlide()` slides the new view in. A press during a View Transition ends it and lands on what is there, and
  refreshes wait while it runs, as for a press. The real session's frame slides whole; nothing animates inside the
  terminal. Another view (Home, Plan...) fades in and rises 10px. A concept's page in the Home Screen app
  slides in from the right and back out, out of reach at once (`conceptOpen()`, `conceptClose()`); a new Talk chat's
  view fades in and rises. The outbox popup fades out too (`popOut()`).
- **Sending.** Your message springs out of the message box to its place in Talk and in a starting chat (`sentFrom()`).
  To a real session, a copy of the bubble leaves the box upward and fades (`sendFly()`); the session itself draws it.
- **Talk.** A new reply's blocks fade in one after another. When a reply grows, only the added words fade
  (`freshWords()`). While at work a wave of three dots (`.wave`) stands beside the words. The `--pulse` loops stay in
  step over redraws (`loopsInStep()`).
- **Lists.** `glideSpot()` notes where each keyed thing and section heading is on screen before a redraw, and `glide()`
  moves it from there to its new place after (FLIP, `--spring`). A card or row that left collapses; its copy has no
  `data-`, ids or typed words, takes no pointer events and is `aria-hidden`, so it reads as gone at once. A new one fades
  in and rises 14px (`enter()`, which remembers when a key was born, so a redraw mid-way continues it). No glide when the
  view changed, while typing in a field of that list (unless a fold's press asked, see Folds), or for more than 8 leaving at once (the whole list changed).
- **Counts and states.** A count rolls (`roll()`, class `.roll`): up when it grew, down when it fell. An element
  with `data-roll` and its words in `data-v` does this; any other state word that changed fades in. The state pill rolls and morphs from its old width. The message box grows and shrinks by a glide (`grow()`).
- **Press.** Buttons, chips and rows scale down a little while pressed, and spring back when let go (`--spring`).
- **Scroll jumps.** A scroll that a press causes glides (`scrollGlide()`, on `--dur-spring` and `--spring-soft`): `toEnd(true)`
  when Talk sends or its mic or typing changes while scrolled up, `kbReveal(el,true)` when a refused Done in Needs you
  moves to its field and Rename to its row, and the slash menu's arrow keys, and a session's jump button (`pastDown()`). A redraw midway continues it. A pointer,
  touch or wheel on the box stops it (`scrollStop()`); another view or sheet ends it. Everything else jumps at once:
  first load, a refresh (`keepScroll()`), Talk following a reply (a glide under way is left to reach the end), `kbReveal()`
  while typing, a view's or sheet's own place, a new Talk chat, a notice's row (`noticeRoom()`), and all of it under `calm()`.
- **Folds.** A fold (a button with `aria-expanded`) wraps what it shows in `foldIn(key, html)`, a `.foldin` box with its
  `data-k`. A press on one, or on any button of the sheet, sets `MO.folded`; for the next `--dur-spring` all the motion it
  causes is on `--spring-soft` (`folding()`, `FOLD_MO`), also over a redraw, so words that load in that time go on too,
  and later ones for the fold that is open. `enter()` reveals the box with a clip from its button, `glide()` moves what
  stands after it, `foldEdge()` moves the card's lower edge (`clip-path`; room is kept by padding until it ends), and
  `leave()` closes a copy of it that goes with its button. `sheetMoves()` does the same in the sheet with its edges
  (`shotEdges()`). It works with a field in use too, since a press asked for it. Without a press (a refresh) the Lists
  rule holds. A chat row's buttons (three dots, touch) slide in and out (`rowExpand`, `rowActsOut`), and the session's
  key row slides in and out while the frame follows (`keysToggle`). Instant under `calm()`.
- **Drawer and sheet.** They open and close on `--spring-soft`. A sheet that takes another's place moves its edges from
  there and its words fade in (`sheetOver()`); its scroll is at the top at once. Released by a finger, they go on from where they are
  with the finger's speed (`springRun()`, frames from `springFrames()`). A finger can catch one mid-way, and a flick
  closes a sheet even when it is short.
- **Pictures.** A picture in the Needs you sheet opens out of its thumbnail and goes back into it (`shotGo()`:
  `transform` and `clip-path` on `--spring-soft` and `--dur-spring`; a copy, `.shotfly`, goes back over the sheet), and
  the sheet's edges, title and foot move with it. The words beside it fade in. Back returns to the scroll place left.
  Under `calm()` both are instant.
- **Kept.** The scrim fades. The Talk dock's mic and box cross-fade. Talk's top bar slides off when you scroll up
  (`.away`, transform only). A session's bars go over its text as the reader scrolls up
  (`.slim`) in one motion on `--dur-bars` and `--ease`, all CSS transitions, so a reversal goes on from where it is: the top bar and a notice's row slide off the top edge and fade, the chips fade, and the message box shrinks into the slim message box (`.slimbox`) and grows back, its bottom edge still (`.slimskin`, `.slimground`, `.slimfoot`, `.dockclip`; `.slimground` is the one ground left while scrolled up, see The session); the dock's words ride down onto the slim row's place. Its inner fade (the slim box's buttons) and delay are shares of `--dur-bars` by `calc()` (.6 and .4), so top and bottom stay in step when the token changes. No line moves when they go or come back (`feedShare()` takes
  part of an upward scroll only while they are away). A chevron turns. The message box, Talk's words and the sheet glide
  (transform only) to their place when the keyboard opens or closes (`kbGlide()`). The session's frame glides in step with the message box (`feedGlide()`), on `--dur-slow` and `--ease`, from where it is on screen now; under `calm()` it is placed at once. It also glides when its rest changes (The session, At rest). A box growing or shrinking by lines glides too (`growGlide()`, the frame with it by `feedGrow()`; over a session the whole `.dock` glides, on the same duration and ease, not `--spring-soft`). The one exception to first load: the
  project list slides in from the left over the project's own sidebar and back out (`.sghost`, transform only,
  `--dur-slow`), and so does arriving at another project from the list (`sideShow()`).
- **Interruptible.** A new motion starts from where the thing is on screen now, and nothing waits for a motion to end.
  State and focus are final at once; only the drawing follows, and so does the scroll position a press moves (see Scroll jumps).
- **What never animates:** the thing the person is reading: a refresh keeps the first keyed thing on screen where it was
  (see Scroll; `keepScroll()` measures without transforms under way). Also anything inside the terminal, a scroll no
  press caused, anything on first load, and a redraw of the same thing.
- **New means new:** give a thing that can come and go `data-k="its key"` (and `data-v="its state"` if it has one).
  `enter()` animates only the keys that were not there before, and nothing before the first snapshot. Your own message
  has `data-t` too, so it comes in once, not again when it is sent and when it lands. Never animate from a class in
  the markup: the markup is drawn again on every refresh.
- **A finger leads.** While it drags, the drawer follows it with no transition; on release it goes on with the
  finger's speed (see Drawer and sheet).
- **Reduced motion:** under `prefers-reduced-motion:reduce` there is none. One rule at the end of the stylesheet
  zeroes every duration, so nothing needs its own. `calm()` is true then too, so every script motion returns at once,
  and no View Transition is started.

## Scroll

- **The page never moves on its own.** A refresh keeps the reading position in every view (`keepScroll()`): the first
  `data-k` on screen stays where it was. At the very top, new things show.
- **Talk is pinned to its newest words** when you open it, when you send (it glides there if you had scrolled up; see Scroll jumps), and while a reply comes in, unless you scrolled up. It has no jump button. The page scrolls a session only through its history, a scroller laid over the frame (see History in The session); otherwise the frame keeps its own scroll, and a refresh never redraws it. Scrolling up in a session scrolls it, and its bars fade away over the text; the slim message box stays (see The session).
- **A chat's history shows its scrollbar**: thin, `--line2` thumb on no track, `--faint` on hover; every other scroller hides its bar (F474).
- Going to a view starts at its top; coming back to one you left returns to where you were.
- **A new version loads by itself, only when nothing is lost or cut off** (`selfReload()`, F207): no finger down, scroll, animation, sheet, popup, selection, voice, focused box or message being sent, and nothing `refreshHold()` names. It comes back to the same view, chat and scroll place, with no toast, once per page print. Until then it shows the `.news` notice (`newsDraw()`) with one `.acc` button (Refresh) beside Later; Later stops it reloading by itself. Refresh keeps all typed words (`keepTyped()`) except secrets: a device form and a typed secret (`givesec:` keys) are not kept, so Refresh waits while one is open (`refreshHold()`). A new kind of field must be kept there or hold Refresh.
- **The off page turns into the app.** An off project's page (see Off page in GLOSSARY.md) becomes its run's app once the
  run is up, at the same address (`turnIntoApp()`), but not while a sheet is open on it.
- A reload opens what was open, drawn in the first frame, and never acts by itself: no mic, no sound, no focus on a box; typing mode is kept over a reload only when it takes under a minute. The one exception is Recorded's open mic where the permission is already `granted`, which starts no listen.
- **Talk opens on the mic.** Coming to Talk (from another view, chat or project, or the tab back after a minute away, `TYPE_STAYS`) ends typing mode and drops the box's focus (`talkBack()`); words stay the draft, and a redraw never does this. Where the mic cannot be used the box stays.
- A refresh also keeps focus, the caret (`keepFields()`), a text selection, what is folded open, and a code block's
  sideways scroll. In a Needs you sheet the field in use stays the same element (`sheetHTML()` patches around it), and so do the Settings search and a text field typed in on a Settings row (`settingsDraw()`), because a new one under the phone's keyboard loses its autocorrect; never put a typed value in markup: `keepFields()` puts it back.
- A notice (`.notice`) floats over the top of the view and never pushes it down, except in a chat: there it has its own
  row under the header, so it covers no text, and `noticeRoom()` keeps the text in place. Elsewhere it floats as
  before. In Talk the top bar may be away while scrolled up, and the notice's row moves up with it (See-through Talk).

- **The Claude login banner** (`.login`, `loginDraw()`) is a notice with no Later, kept until what it says is fixed, so it
  has its own row under the header in every view and covers nothing; a scrolled-up session (`.slim`) puts it away with
  the other bars. It has one button, Log in again, and goes by itself after a new login. Log in again
  opens a sheet (`SHEETS.login`) with numbered steps, `1. Open the sign-in page` and `2. The code the sign-in page
  gives you` with Send code, since a phone cannot press a link or paste in a terminal. The terminal (`claude auth login`
  in ttyd) sits under the steps in `.loginterm`, its frame put there by script, so a redraw never takes it. The other
  notices stand under it, in `.over`. A run's page shows the run's own words; Home, and All
  projects on any page, show Home's.
- **The run-off banner** (`.login` class, `#runoff`, `offDraw()`) says The run is not running (busy: Starting the run…)
  with one `.acc` button, Start the run, and no Later. It has its own row under the header, like the login banner, on
  every view but Home and Status, and on those two only while a chat is open (Home's Start card and Status's Run card
  say it otherwise); not on All projects. It shows only from a fresh snapshot.

### See-through Talk

- **The chat fills the view.** In Talk (`.see` on `.main`, at every width) the chat runs behind the top bar (`.top`),
  the round buttons and the message box (`.dockwrap`). The bar and notices are frosted glass on `--bg`; the side
  buttons, status line and box are frosted on `--surface`; the mic is solid with a `--shadow`. Nothing is drawn behind
  the buttons, so a touch between them reaches the chat.
- **Clear at rest.** `seeRoom()` measures the top bar, a notice's row and the dock, and pads the chat by that much, so
  the newest words sit clear of them.
- **The bar goes away.** Scrolling up 8px slides only the top bar off (`.away`, `barAway()`), and a notice's row moves
  up with it. It comes back on scrolling down 8px, at the end, or when a key puts focus in it. A refresh, new words,
  the keyboard and iOS's bounce never move it.
- **Fixed parts stay.** The speaker, the mic (full size), the keyboard button and the status line never change on
  scroll.
- **Reduced transparency.** Under `prefers-reduced-transparency`, where the browser reports it, the bars, buttons and
  box go solid. A chat with the real session has a solid header and message box at rest: the frame runs under them. Scrolled up, the dock has no ground (see The session), so the text shows around the chips and the box.

## The session

A chat or slot shows the real Claude Code session through ttyd, in place of a thread the page draws. These rules hold:

- **The dock has no ground while scrolled up.** While the history is up (`.feedpast.up`) or the frame is pulled (`.pulled`), the chips and the message box keep their own fill, and text shows between them; a press between them reaches the history. Only `.slimground` stays, from the box's bottom corners down, so no text shows under the foot line (`.slimfoot`). Behind the slim message box (`.slimbox`) there is no ground: text shows around it, and a press beside it is the text's. At rest the dock's own ground is there as before.
- **The bars only go over the text.** The chips and the top bar fade or slide over the session, and the message box shrinks into the slim one (see Motion); their going or coming never moves a line or the frame (`#feedframe`). Scrolling up 8px takes them away once the session itself is scrolled up (`feedBars()`, `.slim`); scrolling down 8px, reaching the session's end, or a tap on the slim message box brings them back (`feedSlim()`, `slimMay()`). One tap on the slim box opens the full box and focuses it in that same tap, on touch too (`kbFocus()`), so the keyboard opens; the draft and the session's size stay. A press on the slim box during a momentum scroll stops the scroll at the touch (the touch layer's glide in `agent_runner/page/090-chats.js`), and the box it opens stays open: only a new scroll takes the bars away again. The tap's touchend makes the click itself (`slimEnd()`), since a browser may give no click for a tap after a fling. The whole top bar fades, its menu button too, so no control lies over the text or takes a tap there; the drawer's edge swipe still opens the menu, and the button stays focusable while faded, so keyboard focus on it shows the bar (`:has(:focus-visible)`). The draft is kept, and the bars do not go while the person types or a menu, question or sheet is open, or an answer is held (`slimMay()`). A line moves only by the scroll or the rest glide (see At rest): the session gets the scroll first (so it stops following new words), and only while it is scrolled up with the bars away does the frame take part of an upward scroll (`feedShare()`), 1:1 with the finger, to bring lines into the room the box left. When the session has nothing older to scroll to (`FD.top`: a short screen, a gap over Claude Code's working lines seen by `feedGap()`, or its first rows unchanged 800 ms after an upward scroll, `feedStillLook()`), the frame takes an upward scroll itself, 1:1, until its first line is clear of the top bar, and gives it back on the way down; while pulled its place is kept relative to the box as when scrolled up, and sending a message rests it (`feedRest()`). Scrolling down gives that back first, so at the end the frame rests with the last lines above the full box. While scrolled up the frame keeps its place relative to the box (`feedPlace()`): a keyboard opening or closing and the box growing by lines move it with the box; a notice, a chip or an attachment that comes or goes, and the bars fading, move nothing. A session that reaches its end by itself (a sent message) rests at once, with no animation; the rest glide (see At rest) is a further move. `feedFoot()` reads "scrolled up" from Claude Code's own pill (`FEED_JUMP`: Jump to bottom, N new messages, Waiting for your answer), so new output while reading does not bring the bars back.
- **One frame.** The session is one iframe (`#feed`), filling the view behind the header and the message box (`#feedframe`, placed by `feedPlace()`, which glides it with the box, see Motion). Its
  address is the run's own (`/t/TOKEN/NAME/`), so https and Runner Home both work. It is made the first time a session is
  opened and then kept loaded out of sight when the chat is left: only its connection changes. ttyd gets a socket that never
  closes (session_frame.HEAD's Line, and `arLine`), so ttyd's own Reconnect words never show.
- **Never redrawn.** A refresh, a snapshot or a state change leaves the frame as it is: it is set once, at the first open,
  and `setHTML()` never touches it. Only the open chat is connected: leaving it, or the page hidden for 15 s, hangs it up, so
  the session gets its other viewers' size back. Its size comes from the view's height with the keyboard closed (`feedRoom()`, `FD.full`): a keyboard opening or closing, and the box growing by lines, never resize it, in whole mode too (`dockRest()`: the dock with one line in the box and the keyboard closed). It is always `FOOT_ROWS` (6) rows taller than its room and placed by transform (`feedPlace()`), so bars, a growing box, a keyboard and scrolling never resize it. Going whole (a menu or unsent words: the frame fits its room, "whole") or back, a rotation and a real window change still resize it. A question card never makes a whole frame lower than `WHOLE_ROWS` (12) rows (`feedWholeHigh()`, B828): Claude Code cuts its lines off at the bottom on a low screen, and with no prompt `feedFoot()` would keep the session whole for good; what does not fit lies under the top bar. On a touch device whose browser shrinks the page itself, the same holds while a field is in focus and for `KB_MS` after.
- **At rest.** A full session: the last line above Claude's own prompt stands just above the box and the chips, keyboard open or closed. A session that is not full (a short screen, or a gap over Claude Code's working lines: `FD.short`, `FD.gap`, `feedGap()` with its work argument) rests with its first line just under the top bar, idle or working, while its words (the working lines apart) fit between the bar and the box; the working line may then lie behind the box (the Working chip shows it). When they no longer fit, or the keyboard leaves too little room, its last words end just above the box. A survey above the prompt (1: 2: 3:) is never hidden like this. When the place changes as the words grow or the gap closes, the frame glides (`feedSee()` with `feedGlide()`; at once under `calm()`), never while the history is read. The history stands on the same pixels with nothing to scroll and no jump button while all fits. Whole, the last line with words still stands on the box.
- **Its bottom lines are past the edge.** The lines under Claude's prompt (the update notice, the status line, the mode, background shells and agents) lie past the frame's edge, so each has its control on the page: a chip row above the message box (`.schips`, a `.chip` per thing to say, none when there is nothing) with Working (its sheet has Stop), the mode (Shift+Tab pressed one at a time and checked; the status line is in that sheet as text), N shells (what runs, its output tail, Stop through `/tasks`), N agents (Open through `/tasks`) and Update (the command, run on the run's machine; only known update commands; Restart chat for an idle c2 and up). A chip shows only when there is something to say. Its sheets are `sesswork`, `sessmode`, `sessshells`, `sessagents` and `sessupdate`. `feedFoot()` finds the prompt on screen. When it cannot (a menu, a question, an unknown look) or the prompt holds unsent words, nothing is hidden: the frame fits its room, and on touch the key row stands in place of the chips, but not with an open question card.
- **Typing goes to the box while the prompt is hidden.** A character, Shift+Enter or a paste in the frame goes to the message box when `feedHand()` says the prompt is hidden: `feedTyped()` does it, asked by session_frame.HEAD on keydown and paste (B190). Other keys (plain Enter, Esc, arrows, Ctrl combinations), input-method composing, a digit while a survey (1: 2: 3:) stands above the prompt, and every key during a menu or question stay the session's. Shift+Enter with unsent words in the prompt is a newline to the session.
- **Hidden lines have their controls.** Whatever the frame hides at its bottom must have its control on the page, or the frame must not hide it.
- **While Claude works.** The message box's send arrow (`.send`, always its own size) is the plain Send with words or an attachment: it sends without force, so Claude Code queues the message. With the box empty, the session working and a sent message still queued (`/live` `queued`), the arrow is Force send (`.send.force`, drawn bolder with a second arrowhead, label Force send). After each send (and each force) the arrow is disabled for about 1 s (`SEND_HOLD`; `aria-disabled`, the gray `.send:disabled` look) while the session works and the box is empty, so a double tap never forces; words typed in that delay can be sent and queue; after a force it stays disabled until the force is answered. With nothing queued or the session idle, the arrow is the plain Send. Only a press on the arrow forces, never Enter in the box. The arrow changes in place (`sendDraw()`), so focus and caret stay. Stop sits beside it (`.act.halt`). A force with words (`chat_to`, no page control) interrupts with Escape, waits until Claude Code's own status is at rest, and sends once: queued messages go in as a turn first, and an unanswered prompt put back in the input stays above the new one; it is not sent if the session never rests. Stop sends one Ctrl+C, not again for 3 s, and never to an idle session. The status is read from `/live/NAME`.
- **While an attachment uploads.** While any attachment of this box is uploading, the send arrow is gray (the `.send:disabled` opacity, plus grayscale), with words or without, and is labelled Uploading… (title, aria-label). It is `aria-disabled`, never `disabled`, so a tap or Enter still says why in a toast. It changes in place (`sendDraw()`, `sendWaits()`) and turns back at once when the last upload finishes, fails or is removed. An uploaded attachment alone counts as something to send (`sendHas()`, `.box.has`), so the arrow is bright; a failed one alone leaves it dim. Stop never changes.
- **Box and session never both hold focus.** A mouse press in the session gives it the keyboard; ttyd's focus on connect
  never does. A tap on the box takes the focus back. So does typing in the session while its prompt is hidden (see above).
- **Copying with a mouse.** A press in the session is held back until it is a drag (over 4px) or a click, and a click is sent to the session on release; a drag selects words and copies them at once, as ttyd always did. With words selected, Ctrl+C or Cmd+C copies them and clears the selection without interrupting, also while the key is held down; with none, it goes to the session as before. A right click is never sent to the session; the browser's menu opens, and its Copy copies the selection. While words are selected a bare mouse move is not sent, as that would drop them.
- **Touch layer.** On a touch device a layer over the frame takes the touch: a drag scrolls the session, or its history
  when that stands in (see History; a wheel steps the session, and it glides), a tap clicks in it without opening the
  keyboard, a long press selects the word under the finger, at the live end too (see History; on `#feedtouch` it opens nothing and sends no click), and the key row's Text opens a sheet with the screen's text to select and copy. A horizontal
  swipe still opens the drawer.
- **History.** A drag (touch) or a wheel up (desktop) over a chat's or slot's session scrolls its history: a native
  scroller (`#feedpast`) laid over the live frame, which the page draws from `GET /history/NAME`. The transcript's lines are
  drawn as Claude Code draws them at the terminal's columns, font, row height and colours (`pastLines()`). At rest it is
  see-through and the live session shows. A touch arms it (`pastArm()`), and its end is a copy of the screen's own rows, so
  every line stays where it is, to the pixel. A scroll away makes it up (`pastUp()`); back at its end the live session
  shows again in the same frame (`pastLive()`). What is not in the transcript yet, a reply being written, is the screen's
  own lines, and the history meets the screen where the same lines stand (`pastJoin()`). While reading, new words are
  added at the end and nothing on screen moves (`pastSee()`, `pastTail()`); older pages are loaded on demand and put in
  only while nothing scrolls (`pastPut()`). Only chunks near the view are in the DOM (`pastDraw()`), and text can be
  selected in it. At the live end a long press selects the word under the finger, the browser's own selection, as it does scrolled up; it stays when the finger lifts and while the history holds the place (`pastPicked()`): with words selected, new words move nothing on screen and the history stays up; with nothing selected the live session shows again (`pastRest()`). A menu or question at the live end, the jump button or a sent message lets go of the selection; a tap still clicks, and while words are selected a tap is the browser's. The jump button (`.pastjump`, see Jump button in GLOSSARY.md) floats over the lines just above the box,
  with its own fill and border and no ground behind or beside it, so text shows on both sides and stays pressable,
  selectable and scrollable; it glides to the live session (`scrollGlide()`, at once under `calm()`). Sending a message also goes
  to the live session, and a fling ends on a press on the slim message box or the button (`pastStop()`). The same button
  shows when the terminal itself is scrolled up and its screen draws no jump pill of its own (Copilot's never does;
  Claude's pill stays its own): a press takes the terminal to its newest output (`feedOwnJump()`, `pastJumpGo()`). Where the history
  cannot stand in (a menu, a question, unsent words in the prompt, a session with no transcript, a session someone else
  scrolled, not connected), a wheel step scrolls the session as before (`feedWheel()`). The keyboard moves the history with
  the box (`pastPlace()`). Page Up, Page Down, Ctrl+Home and Ctrl+End pressed in the session scroll it too (`pastPress()`); another width (a rotation) breaks its lines anew and keeps the place as near as can be (`pastWidth()`).
- **Key row.** A keyboard button in the message box folds out the key row (`FEED_KEYS` in the page's scripts, and Text):
  Esc, Tab, ↑, Enter, Ctrl-C, Text, ←, ↓, →. Touch only. While a question card is open (whole, or its Undo row), the key row is not shown, neither the keyboard button's nor the one in place of the chips. It comes back as it was once the card is answered, gone, minimized or marked (Chat about this). While the card is shrunk to its pill by scrolling up (see Question card), the key row comes back as it was, under the pill; a row opened under the card stays. The keyboard button still opens it under the card, for that question only.
- **Text size.** 12px on touch, 13px otherwise, in ttyd's DOM renderer (its canvas is wrong at 2x). The size is `feedSize()`, shared with the stand-in.
- **Ground and look.** `--feed` is dark unless the person's agent `theme` starts with light (`session_look`). A session the run starts (control sessions and slots) takes the run's own Claude Code theme, `agent-runner` (`session_theme.py`), named only in the settings the run gives its sessions: its colours are 256-colour slots that each browser fills from the page's light or dark, live (`arLook`), so the ground is the page's `--bg`. Code in a diff has its own colours per look too (`CODE` in session_theme.py; plain code is the page's text colour), each 4.5:1 on the diff rows, only for the base in use; a slot the theme's own colours use keeps that colour. Line height 1.3, padding 12px 14px, box lines in the `ar-box` font (they join), minimum contrast 4.5, spinner tips off, reduced motion on. A person's own terminals keep theirs, and a chat open before this keeps its old ground until it restarts.
- **States are cards.** Starting (says so, with the waiting message), loading, ended (the claude.ai/code link, and Resume
  where there is one; over a kept last screen the card sits above the message box, see Last screen), a slot with no session (Resume when its task was cut off), no terminal (a headless stream slot,
  a slot with no socket, or Windows before 1809) and no ttyd (how to install it). Each is a `.card` with a title, one
  line of second text and its `.btns`. The state is checked every 3 s.
- **Last screen.** Each chat's screen is kept as it was last drawn, for the last 12 chats, in the page's memory (`keptPut()`,
  `feedKeep()`; a reload empties it). A switch to a kept chat shows that screen at once, slightly dimmed, under a thin moving
  line (`.feedline`), and `feedBack()` puts it back where it was placed. It stays until the terminal's first whole draw
  (`feedDrawn()`), then the terminal shows its own end. No blank frame and no move. A chat not seen in this page shows its
  latest messages from its feed in that place, laid out by `pastLines()` at the terminal's own size, font, columns, row height, left edge, list hang and paragraph spacing (`.feedstand`, `standHTML()`, `standCells()`), so nothing rewraps when the terminal draws; a list right under a paragraph has no blank line before it, here and in the history. The chips row stands from the first frame, and
  the frame is placed in the same frame its screen is drawn, so a redraw with a row more or less does not move the text.
- **Connection lost.** The text stays. The page dials again by itself after 250 ms, doubling to 15 s. After 5 s a pill
  (`feedSay()`) says Reconnecting…, or Connecting to the session… the first time. A silent network (socket open, no answer
  and no output for 5 s) shows the same moving line and Reconnecting… over the undimmed screen.
- **Ended.** An ended chat keeps its last screen, and its ended card with Resume sits above the message box (`.feedend`,
  `feedEnd()`). After a reload, with nothing kept, the card is in the body as before.
- **New chat opens at once.** A press that starts a chat about something (Chat on a plan task, concept or setting, Add a task, New concept) opens the
  empty new chat view over the view pressed in, with its box focused. Nothing is sent or started until the first message.
- **A chat on the harness loop.** Its terminal has no prompt lines to hide, so the frame is whole. Its chips are only Working and the model (`Codex · gpt-5.6-sol`, from `modelOf()`, sheet `sessmodel`), also on touch, where the key row otherwise stands in place of the chips. It has no mode, shells, agents or update chip. Its box has no slash menu and no / button, and no "/ commands" in the box's keys line.

## Touch, keys and access

- A finger's target is at least `--tap`. Hover only adds: whatever it reveals, touch shows or puts in a row's sheet. A chat row's
  three dots open its buttons in the row itself (`.rowacts`): Rename, Pin, and Delete where the dots were, so two taps on
  that spot delete, with Undo. One row is open at a time, and a tap elsewhere only closes it. The rename row (`.renform`)
  has a Cancel button (✕, at least `--tap` on touch) beside its field: Cancel, Esc or opening another chat (`renameLeave()`)
  keeps the old name and sends nothing, and that same press opens the other chat; Enter saves. A
  small button that must be 44px with any pointer gets its target from an `::after` over it (Home's Talk chip), so it
  still looks like the ones beside it.
- Text boxes are 16px or more, so a phone does not zoom.
- **A hold selects words only.** On touch (`any-pointer:coarse`) nothing can be selected from `html` down: a hold where there are no
  words (the scrim) had iOS select the whole page. What people read and copy opts back in, in the one B814 rule at the end of
  `page/190-shared.css`: add a new reading surface to that list. Name the words' own element, never a whole
  list, card or view. A button is never selectable, also inside those words; a link keeps its own callout, also one drawn as a button.
- Every multi-line message box decides Enter with `boxEnter()` and puts `enterHint()` on its textarea, so a phone's Return makes a new line.
- Touch listeners that watch a gesture are passive, except a `touchmove` that must keep the page still: the drawer
  swipe, a pull to refresh and a row drag (a pinned chat's row, or a lifted Plan queue row), and the `touchend` that makes a tap's focus on a text box (`kbTapEnd()`, iOS only) and the lift's `touchend` (`liftEnd()`). Those call
  `preventDefault()` only once the gesture has started, so a scroll stays smooth; the `touchend` calls it only for such a tap, or once a row has lifted, so no click follows.
- A touch is one thing until the finger lifts. One that scrolled never becomes a swipe, and a drawer swipe never scrolls.
  Decide under 10px: iOS cannot cancel a scroll that has begun.
- **Pull to refresh.** On touch, a finger that starts in the main view or the sidebar with everything under it at its top
  and moves mostly down pulls a small spinner (`.pull`) after it, with resistance (`pullAt()`). Past 70px the spinner is
  ready, and letting go does what Refresh does (`newsRefresh()`); if Refresh is held, or the pull was short or
  cancelled, it springs back, at once under `calm()`. Not over a sheet, popup or concept, nor in a text box, an iframe or a row
  being dragged; a second finger ends it. The document stays locked, so the browser's own pull never fires.
- A swipe leaves text boxes, sideways scrollers, a row being dragged and mostly vertical moves alone.
- Every control is a `button`, `a` or form field, reachable by Tab, with a visible `:focus-visible` ring. Esc closes the topmost thing only.
- Live words (the talk line, the toast) have `role="status"`.
- A link to the app's own pages never opens a new tab on the Home Screen: `appLink()` decides. A concept opens over the
  app (`.cview`, `conceptOpen()`) with Back; other sites keep `target=_blank`. The status bar is the default style,
  coloured by `theme-color`, never `black-translucent`.

### Keyboard

- iOS shrinks only the visual viewport, not `dvh`. While a keyboard is open, `kbFit()` gives `.app` the visual
  viewport's height and offset and the class `.kb`; on close both go back to the stylesheet's.
- While open: no bottom safe-area inset on `.app`, less bottom padding on `.dock` and the sheet, and the header stays
  on screen. Talk stays at its newest words while pinned; one scrolled up stays put.
  In Talk the top bar may be away while scrolled up; the keyboard never brings it back (See-through Talk).
- The session keeps its size: opening or closing the keyboard never resizes it (see The session). The frame moves with the box instead. `feedRoom()` takes the bottom inset off too, as `.app` has none while the keyboard is open.
- The document never scrolls (`html` and `body` are locked). Only `.body`, `.side`, `.sheet`, small lists and a session's history (`#feedpast`) scroll.
  Anything with a text box lives inside `.app` and is sized in % or `cqh`, not vh, while the keyboard is open.
- Never `scrollIntoView` to show a field being typed in: `kbReveal()` scrolls its own scroller. Pinch zoom is left
  alone. Safari's own address pill and arrows bar cannot be removed in a tab.
- Outside `.app` (behind Safari's bar, around the keyboard) shows `html` and `body`'s `--page`, the view's own colour
  (the grey band in B160's recording was the app's `--bg` behind a black chat; Talk's and a chat's is the terminal look's ground); `theme-color` follows it (`pageColor()`). Safari tints its bars from a fixed layer over the page's edge, so
  a change of view puts new `.edge` strips there (under the drawer and the sheet).
- A tap's focus on a text box in iOS is made by `kbFocus()`: `preventScroll`, and the box see-through for two frames, so
  Safari does not pan; the caret goes to the end (a second tap places it). A box a script
  focused without a keyboard is blurred first. Every scripted `focus()` of a box passes `preventScroll:true`, with `kbReveal()` where it must come into view.
- On touch, opening a chat never focuses its box, nor does the chat a first message starts; focus left in a text field is dropped (`open()`), so the keyboard goes and the box sits at the foot. Only a tap on the box, + Task or a card's Chat brings it. A starting chat that gets its name keeps its focus. A desktop pointer focuses the box on open.
- On touch, a swipe that ends with the sidebar drawer newly open, or the menu button opening it, drops the focus of a text field (`drawerBlur()`), so the keyboard goes; the draft stays. A cancelled swipe, or one that springs back closed, keeps it, as does a drawer already open and the rename box (`startRename()` opens the drawer and focuses its field).
- `.app` keeps full height until the visual viewport changes, and gets it back at once on blur. It must not stay shrunk
  with no keyboard: while the keyboard is open, `kbFit()` also runs every `KB_ASK` ms (any browser), as a resize event
  can be missing. On iOS, a focus no press caused, with no keyboard and more than `KB_MS` after the last field was left,
  over a viewport still short, is not a keyboard (`kbEnter()`, `kbGone`) until the viewport's height changes, a press
  focuses a box, or the person types. Also on iOS, going to another app with the keyboard open blurs the box; what was
  typed stays. A viewport that stays short while the box keeps focus in this app, or is focused again within `KB_MS`,
  cannot be told from a keyboard.
- For 900ms (`KB_MS`) after a field is entered or left, `kbFit()` runs each frame on iOS, as events come late and in any
  order, and follows Safari's pan so the header stays on screen.
- The viewport meta has `interactive-widget=resizes-content` for browsers that have it.
- The session and the message box never both hold focus (see The session).

### Lazyrunner

- Lazyrunner (UI settings: Layout) is only a CSS layout (`189-lazy.css`) and a key layer (`189-lazy.js`) over the
  page's own sidebar and views: it draws no view, panel or renderer of its own and hides no sidebar row, so both
  layouts have the same panels (`tests/test_lazy.py`). Its keys press the buttons the page already has.
- It applies from 760px of width; a phone stays Standard. Its keys act only in normal mode: never while a text field,
  a select or a sheet has the keyboard (Esc leaves insert mode as it always did).
- A theme picked in UI settings sets `data-ui` (colours from theme.py's table) and `data-theme` (light or dark) on the
  root; Standard leaves both off and follows the device. UI settings are kept per browser.
- The numbered panels ([1] Home, [3] Plans, [4] Tools, [5] Settings, [7] Concepts) sit at the top of the sidebar, the
  [2] Sessions rows below them; a focused or open row keeps its number readable. [6] Needs you has no sidebar row: its
  key opens Home's Needs you rows.
- Its run keys (`+ - P G S`) are the terminal UI's, read from the run controls list (`ui_model.RUN_CONTROLS` `tui`),
  and the keys sheet lists them from that list; a key whose button is not in view opens the panel that draws it
  (Home's Run card, Plans) and presses it there (`lazyPress`).
- The terminal theme is monospace with square corners.
- The key bar lists every key of the mode it is in (normal or insert), from the same lists as the keys sheet; it wraps
  to more lines rather than cut one off. Moving the highlight onto a chat row shows that chat in the main pane.

## Sound

- Run speech plays only in the one audio element (`AU.el`), only after the person's tap has allowed it, never while the mic listens.
  The mic's own press counts as that tap: silence is played only after the press has stopped the recognizer (Hold's release, Tap's second tap).
  The press that starts the mic only loads the elements (`load()`, no playback), after `rec.start()`.
  When the browser blocks it, the talk line says what to tap.
- One button stops the reading: the speaker (and the reply's own play button). The mic is never a stop for it; a press on the mic
  cuts a reading and listens in that press.
- Leaving Talk stops the reading too: `render()` calls `talkAway()` whenever Talk is not the shown view (`chatShown()`), so a new way out needs nothing of its own.
- Every reading must be watched with `soundWatch()`, since iOS can skip a sound's end event.
- The browser's voice (`speechSynthesis`) is not called before `rec.start()` in a press (B132); run speech clips may be stopped before it.
- Every mic use goes through `MIC`: a Recorder stands in as a recognizer (`micRec()`), so one recognizer or recording runs at a time.
- Recorded keeps one stream. The Open mic starts inside the press that opens Talk, whatever the Permissions API says (not while a reply is read or dictation has the mic); with no press (a reload, Talk shown again) it opens only where the Permissions API already says `granted`; otherwise the first mic press opens it, and it stays open between listens. What was refused at Talk's press is asked again only by a mic press. A press on a running stream listens inside the press, and its clip has no sound from before it (no pre-roll): with no listen on, every piece of sound is dropped at once. Only a mic held again while the last words are made keeps the sound of that hold. It is released at once when the page is hidden, within 0.5 s when Talk is left, a chat or the Mic test opens, or typing mode shows, and opened again when Talk's mic shows. While a reply plays, the Open mic's stream rests whatever the permission is: its track is disabled (no sound is taken) and its AudioContext keeps running, so a press after the reply is heard at once. The audio session is play-and-record while the stream is open, playback while it is closed or rests. When the browser ends the stream's track (track ended) while Talk's mic shows, between listens and with no reply read, it is opened again by itself where the permission is `granted`, at most 3 times (`REC_ENDS`) until a press listens, Talk shows anew or Speech to words is picked again; after that it waits for Talk to show anew or a press. An end during a listen (its words go out) or while a reply is read, and an opening by itself that fails, are not tried by itself again until Talk shows anew; a press still tries.
- The talk line says `Starting the mic…`, `Listening…` or `Getting the words…`, and `Tap to talk, the mic is open, not listening` at rest while the stream is open (the mic button's label says it too). The open-mic dot (`.mic.open`, `--bad`) stands still, with no animation. A setting that cannot work says why under its row and what is used instead. After a pause in a hold, the talk line shows the words with `… Starting the mic…` or `… Listening…` until the mic is on again, and words that may be half a message are never sent by themselves: the line says so, with `Send as it is`. A Hold let go before the mic is on, or within 0.5 s of its first sound where the press found it not open, with no words, says "The mic was still starting…" with the browser note, and `Listening…` is never said while the mic is opening, also when opened afresh.

## Before you finish

1. Phone (390px) and desktop (1280px), light and dark, looked at.
2. Empty, loading, working, failed: each seen.
3. Reduced motion on: everything still works.
4. Scroll half way down, wait for a refresh: nothing moved.
5. A chat or slot with a real session: phone (390px) and desktop, both themes, and a refresh leaves its frame as it was. Scrolling up takes the chips and top bar away over the text and shrinks the box to the slim message box, and scrolling down brings them back; no line moves when they go or come back. A drag or a wheel up opens the history over the screen, and back at its end the live session shows in the same frame, with no line moved. A switch between chats shows the kept last screen at once, with no blank frame and no move.
6. A changed motion is watched as a recording or frame strip at 390px, not only stills.
7. `python3 tests/test_web_<area>.py` for each area the change touched (all of `tests/test_web_*.py` for a shared one).
