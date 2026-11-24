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
  has an `aria-label` and a `title`.
- **Card** (`.card`, `card()`): one thing. `.tap` opens something; `.need` waits on the person. Title, one line of
  second text, then `.btns`.
- **Needs you item** (`.asktap`, `needTap()`): one button, not a card of buttons. What is wanted and where in everyday
  words (`.asklab`), the title on one line, at most two lines of what to do (`.askdo`), then Press for details, the
  steps count, the id and the age. A DECIDE's heading is its question, whole (`needHead()`, `.q`), with its task's title
  small on one line under it and at most two lines of its background in place of what to do. Its answer buttons sit
  below it. A DECIDE's options are its answer buttons, the recommended first, marked "(recommended)" and `.pri`. A pick
  sheet's start with "Go with the recommended picks" (`.pri`), then, for one question, its answers the same way.
- **Needs you sheet** (`SHEETS.need`, `needSheet()`): the whole ask in order: title (a DECIDE's question, its task's
  title small under it), label, age, id; where and when, or a DECIDE's background as paragraphs; What to do (a DECIDE's
  only when its ask file has steps); What you should see; notes; pictures (`.shot`, full size inside the sheet, Back or
  Esc goes back); the
  task text folded. An item with inputs draws its steps with Open (a step's link) and the command as code, with
  "Run on <machine>" and Copy; then What you should see; then What to enter, one field per input (its label above it;
  a secret is a password field, and over plain http words stand in its place and say why), a refusal in `--bad` under
  its field; then one Done (`.pri`), all in the body. A confirm question takes Done's place (Yes, send it / No). There
  are no plain answers on its card or sheet and no reply box: Later, Chat and Drop stand at the foot (`.askfoot.end`),
  not sticky, so they never cover a field.
- **Row** (`.row`, `.crow`, `.prow`, `.srow`, its folding head `.fold`): one line when folded, with an ellipsis. A row that holds more folds
  open on tap in place (`aria-expanded`), and its chevron turns. A setting's row (`.srow`) shows its name, its description and its control; it opens to show the code name and More… (a sheet with the other home and Reset).
- **Chat order** (`chatSort()`, `chatPlaces()`, `sideRows()`): pinned chats on top in their own order, then the rest newest to oldest by `at`; a chat with no `at` yet, or still starting, sits first under the pins. No row moves while it is dragged or pressed (`pressHeld()`, 15 s at most), nor while a chat's name is edited: what is new goes last in that row's list, and pins can't be dragged then.
- **Section** (`.sec`): a small muted heading and a line. Sections keep the TUI's order.
- **Sheet** (`#sheet`, `openSheet(name)`): more choices about what is on screen. It slides up from the bottom, groups
  its items (`.it`) under `.sec`, closes on the scrim, Esc, a swipe down, or a pick. One sheet, never a sheet over a
  sheet. Its markup comes from `SHEETS[name]()`. A button whose label ends in … opens one or folds open. A Needs you item's
  sheet is a centred dialog (`.dlg`) from 760px wide, not a sheet from the bottom. A sheet is visible from the first frame so it can take focus when it opens (its visibility is only animated on closing; no ring around the sheet itself), and closing gives focus back to what opened it while that is still drawn (a Needs you card, also when it was drawn again since).
- **Sidebar level** (`.slevel`, `.prow`, `sideShow()`): the sidebar's level is the view. The first row is All projects
  (`allRow()`, with a count of what needs you in other projects, hidden when Home lists one project); the level it
  opens is the project list (`allSide()`), and a project's own list turns it back. A `.prow` is one project: its state
  dot, its name, and a `.n` only for what needs you in that project. Badge rules apply as below.
- **+ button** (`.btn.plus`, `plusBtn()`): one per view, top right, its word kept on a phone (Project, Task, Concept,
  Slot, New talk, Device). `+ Chat` stands only beside Chats. None in Settings or in a chat. + Task is disabled for 1 s after the file picker closes (`holdPlus()`), so a double press in it cannot land there.
- **Project card** (`.pcard`, `projectCard()`): one project on the Overview or in a list: its state dot and name, its
  tasks by title, what landed today. One main button (`mainBtn()`: Start run or Open); the rest is in the
  … sheet (`dotsBtn()`), never beside it.
- **Release card** (New release, `release_wait`, `release_now`): one line of what is open, then its buttons; the question takes their place; a press with a release open asks in place, Yes then No, and a Drop on a release that has not started asks its own question first. With Manage releases off (`releasesOn()`) it goes, and its heading with it; an open release is a task in the Queue.
- **Walkthrough** (`.walk`, `walkDraw()`, `walkStep()`): one card at a time (`.walkcard`), only on the example project's
  page (`walkNow()` says when), never in a chat or Talk. Its row of its own under the view covers nothing, and goes while
  the keyboard is open. A 2px `--accent` ring (`[data-walkat]`) is on the real thing it points at. Back, Next and Skip
  (Done on the last) stand in it; Show me when the page is on another view. A press goes to the step's view with the
  thing on screen, and glides within one view; a redraw or a reload never moves the page for it. Home's offer of the
  example project is `exampleOffer()`. Its words are in `WALK_STEPS` (`page/084-walk.logic.js`, read by `walk.py`), the one list the page
  (`084-walk.logic.js`) and the terminal UI share: each step has the page's words and the keys' words, and each view shows
  only its own. The TUI draws it as a 'Walkthrough' box above the bottom line, keys as buttons, with ◂ after the pointed
  panel's name; on a small screen only the focused panel shows with it.
- **Badge** (`.n`): a count of what waits on the person, never of anything else. **Dot** (`.bdot`): something
  waits, no count. **Pill** (`.pill`): a state in a word or two. Same words on every page: Running, Paused,
  Stopping, Caps forced, Not up.
- **Confirm**: asked in place (`sureHTML`), naming what is cut off, Yes then No. No browser dialog, ever. In the TUI
  the key is pressed twice.
- **Setting or form control**: a label, the control that fits the type (`.sw` switch, `.fld` select, number or text, or a `.step` stepper for a number changed a step at a time), then help in `.small`. A typed value is edited in the open row; a switch or select on a row saves at once; a closed row shows no code name. A setting of two controls (`.setparts`) has them on a line of their own under its description, each with its label. Each group's heading says its home (this device or everyone). A field that must survive a refresh has `data-f="key"`. A new setting needs its words in `agent_runner/setting_words.py` (`tests/test_settings.py` checks).

## States

Every list and view has all four, drawn the same way:

- **Empty:** one calm sentence saying so (`emptyCard()`), and the way to add one when there is a way. Never a blank.
- **Loading:** `Loading…` in `.small`, only where nothing is there yet. Old content stays while new loads.
- **Working:** `.livedot` beside the words; a button that is sending is `.busy` and stays where it is.
- **Failed:** what did not happen and why, in `--bad`, with Retry or the way out. Nothing the person wrote is lost.

## Instant feedback

Every action the person takes goes through `outbox()`: the page draws the result at once as a stand-in, keeps the
action until the run answers, and sends it again after a lost connection. A card that was answered folds away at
once; its stand-in shows in the same place. A failure brings Retry, Edit or Discard. A message to a chat still starting stays pending, and the Outbox says it waits for the chat to start. `act()` is only for what has
nothing to draw (an interrupt, an order kept) and for Talk, which draws the person's words itself.

Home's own actions (start, pause, slots, stop) go through `homeAct()`, an outbox of their own shared by every page of
that Home, so one started before a switch to another project is still followed there. Home runs each one once, and a
failure brings Retry there too.

A secret never goes through `outbox()`, which the browser keeps: a device's change goes straight to the run
(`toolPost()`; its secret's field is emptied when sent), and an input goes straight to the run too (`giveSend()`), a text or link as well. A refusal or a
question keeps what was typed, the secret too, while the sheet is open; a secret is forgotten when the sheet closes
(`giveForget()`), a text or link is kept. Once sent, all its fields and words go. No value goes in the markup, and a
saved secret is shown only as `set, changed <date>`.

## Words

- Plain words, a verb first on a button, sentence case, no exclamation marks, no dash between clauses.
- The glossary's term, and the same one everywhere: Needs you, slot, task, landed, concept, chat.
- A task is named by its title. Its id may follow, small.
- Say what happens, in the person's terms: "Stop (running tasks finish)".
- Numbers with their unit: `6 min`, `2 of 3 slots`, `week 62%`.

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
| `--dur-fast` | 150ms | a press, a chevron, a fade out |
| `--dur` | 200ms | a card, row or message coming in, a cross-fade, a view's fade |
| `--dur-slow` | 250ms | what leaves collapsing, the scrim, the project list's slide (`.sghost`) |
| `--dur-bars` | 400ms | a session's bars going and coming back (`.slim`), and nothing else |
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
- **Views.** A chat opens: its view slides in from the right over the one that was there, and back slides it out,
  wherever it was pressed (a row, a card, Back, Esc). `viewGo()` runs this as a View Transition where the browser has
  them; the chat row's title in the sidebar is carried to the top bar's title and back while that row is on screen.
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
  moves to its field and Rename to its row, and the slash menu's arrow keys. A redraw midway continues it. A pointer,
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
  (`.slim`) in one motion on `--dur-bars` and `--ease`, all CSS transitions, so a reversal goes on from where it is: the top bar and a notice's row slide off the top edge and fade, the chips fade, and the message box shrinks into the slim message box (`.slimbox`) and grows back, its bottom edge still (`.slimskin`, `.slimground`, `.slimfoot`, `.dockclip`); the dock's words ride down onto the slim row's place. Its inner fade (the slim box's buttons) and delay are shares of `--dur-bars` by `calc()` (.6 and .4), so top and bottom stay in step when the token changes. No line moves when they go or come back (`feedShare()` takes
  part of an upward scroll only while they are away). A chevron turns. The message box, Talk's words and the sheet glide
  (transform only) to their place when the keyboard opens or closes (`kbGlide()`). The session's frame glides in step with the message box (`feedGlide()`), on `--dur-slow` and `--ease`, from where it is on screen now; under `calm()` it is placed at once. A box growing or shrinking by lines glides too (`growGlide()`, the frame with it by `feedGrow()`; over a session the whole `.dock` glides, on the same duration and ease, not `--spring-soft`). The one exception to first load: the
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
- **Talk is pinned to its newest words** when you open it, when you send (it glides there if you had scrolled up; see Scroll jumps), and while a reply comes in, unless you scrolled up. It has no jump button. The page does not scroll a session at all: the frame keeps its own scroll, and a refresh never redraws it (see The session). Scrolling up in a session scrolls it, and its bars fade away over the text; the slim message box stays (see The session).
- Going to a view starts at its top; coming back to one you left returns to where you were.
- **A page never reloads by itself.** A new version shows the `.news` notice (`newsDraw()`) with one `.acc` button (Refresh) beside Later. Refresh keeps all typed words (`keepTyped()`) except secrets: a device form and a typed secret (`givesec:` keys) are not kept, so Refresh waits while one is open (`refreshHold()`). A new kind of field must be kept there or hold Refresh.
- **The off page turns into the app.** An off project's page (see Off page in GLOSSARY.md) becomes its run's app once the
  run is up, at the same address (`turnIntoApp()`), but not while a sheet is open on it.
- A reload opens what was open, drawn in the first frame, and never acts by itself: no mic, no sound, no focus on a box.
- A refresh also keeps focus, the caret (`keepFields()`), a text selection, what is folded open, and a code block's
  sideways scroll. In a Needs you sheet the field in use stays the same element (`sheetHTML()` patches around it), because a new one under the phone's keyboard loses its autocorrect; never put a typed value in markup: `keepFields()` puts it back.
- A notice (`.notice`) floats over the top of the view and never pushes it down, except in a chat: there it has its own
  row under the header, so it covers no text, and `noticeRoom()` keeps the text in place. Elsewhere it floats as
  before. In Talk the top bar may be away while scrolled up, and the notice's row moves up with it (See-through Talk).

- **The Claude login banner** (`.login`, `loginDraw()`) is the one notice that stays until what it says is fixed, so it
  has its own row under the header in every view and covers nothing; a scrolled-up session (`.slim`) puts it away with
  the other bars. It has one button, Log in again, and no Later, and goes by itself after a new login. Log in again
  opens a sheet (`SHEETS.login`) with numbered steps, `1. Open the sign-in page` and `2. The code the sign-in page
  gives you` with Send code, since a phone cannot press a link or paste in a terminal. The terminal (`claude auth login`
  in ttyd) sits under the steps in `.loginterm`, its frame put there by script, so a redraw never takes it. The other
  notices stand under it, in `.over`. A run's page shows the run's own words; Home, and All
  projects on any page, show Home's.

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
  box go solid. A chat with the real session has a solid header and message box at rest: the frame runs under them, and `.slim` is the only thing that shows it through.

## The session

A chat or slot shows the real Claude Code session through ttyd, in place of a thread the page draws. These rules hold:

- **The bars only go over the text.** The chips and the top bar fade or slide over the session, and the message box shrinks into the slim one (see Motion); their going or coming never moves a line or the frame (`#feedframe`). Scrolling up 8px takes them away once the session itself is scrolled up (`feedBars()`, `.slim`); scrolling down 8px, reaching the session's end, or a tap on the slim message box brings them back (`feedSlim()`, `slimMay()`). A tap on the slim box opens the full box; on touch it does not focus the box, since the keyboard would cover what is being read. The whole top bar fades, its menu button too, so no control lies over the text or takes a tap there; the drawer's edge swipe still opens the menu, and the button stays focusable while faded, so keyboard focus on it shows the bar (`:has(:focus-visible)`). The draft is kept, and the bars do not go while the person types or a menu, question or sheet is open. A line moves only by the scroll: the session gets the scroll first (so it stops following new words), and only while it is scrolled up with the bars away does the frame take part of an upward scroll (`feedShare()`), 1:1 with the finger, to bring lines into the room the box left. Scrolling down gives that back first, so at the end the frame rests with the last lines above the full box. While scrolled up the frame keeps its place relative to the box (`feedPlace()`): a keyboard opening or closing and the box growing by lines move it with the box; a notice, a chip or an attachment that comes or goes, and the bars fading, move nothing. A session that reaches its end by itself (a sent message) rests at once, with no animation; it is the one other move. `feedFoot()` reads "scrolled up" from Claude Code's own pill (`FEED_JUMP`: Jump to bottom, N new messages, Waiting for your answer), so new output while reading does not bring the bars back.
- **One frame.** The session is one iframe (`#feed`), filling the view behind the header and the message box (`#feedframe`, placed by `feedPlace()`, which glides it with the box, see Motion). Its
  address is the run's own (`/t/TOKEN/NAME/`), so https and Runner Home both work.
- **Never redrawn.** A refresh, a snapshot or a state change leaves the frame as it is: it is set once per open, and
  `setHTML()` never touches it. It goes when the chat is left or the page has been hidden for 15 s, so the session gets
  its other viewers' size back. Its size comes from the view's height with the keyboard closed (`feedRoom()`, `FD.full`): a keyboard opening or closing, and the box growing by lines, never resize it, in whole mode too (`dockRest()`: the dock with one line in the box and the keyboard closed). It is always `FOOT_ROWS` (6) rows taller than its room and placed by transform (`feedPlace()`), so bars, a growing box, a keyboard and scrolling never resize it. Going whole (a menu or unsent words: the frame fits its room, "whole") or back, a rotation and a real window change still resize it. On a touch device whose browser shrinks the page itself, the same holds while a field is in focus and for `KB_MS` after.
- **At rest.** The last line above Claude's own prompt stands just above the box and the chips, keyboard open or closed; a short session too. Whole, the last line with words stands there.
- **Its bottom lines are past the edge.** The lines under Claude's prompt (the update notice, the status line, the mode, background shells and agents) lie past the frame's edge, so each has its control on the page: a chip row above the message box (`.schips`, a `.chip` per thing to say, none when there is nothing) with Working (its sheet has Stop), the mode (Shift+Tab pressed one at a time and checked; the status line is in that sheet as text), N shells (what runs, its output tail, Stop through `/tasks`), N agents (Open through `/tasks`) and Update (the command, run on the run's machine; only known update commands; Restart chat for an idle c2 and up). A chip shows only when there is something to say. Its sheets are `sesswork`, `sessmode`, `sessshells`, `sessagents` and `sessupdate`. `feedFoot()` finds the prompt on screen. When it cannot (a menu, a question, an unknown look) or the prompt holds unsent words, nothing is hidden: the frame fits its room, and on touch the key row stands in place of the chips.
- **Typing goes to the box while the prompt is hidden.** A character, Shift+Enter or a paste in the frame goes to the message box when `feedHand()` says the prompt is hidden: `feedTyped()` does it, asked by session_frame.HEAD on keydown and paste (B190). Other keys (plain Enter, Esc, arrows, Ctrl combinations), input-method composing, a digit while a survey (1: 2: 3:) stands above the prompt, and every key during a menu or question stay the session's. Shift+Enter with unsent words in the prompt is a newline to the session.
- **Hidden lines have their controls.** Whatever the frame hides at its bottom must have its control on the page, or the frame must not hide it.
- **While Claude works.** The message box's send arrow (`.send`, always its own size) is Force send (`.send.force`, drawn bolder with a second arrowhead) while the box has words or an attachment; otherwise it is the plain Send. It changes in place (`sendDraw()`, `sendForces()`), so focus and caret stay. Stop sits beside it (`.act.halt`). Force send interrupts with Escape, waits until Claude Code's own status is at rest, and sends once: queued messages go in as a turn first, and an unanswered prompt put back in the input stays above the new one; it is not sent if the session never rests. Stop sends one Ctrl+C, not again for 3 s, and never to an idle session. The status is read from `/live/NAME`.
- **Box and session never both hold focus.** A mouse press in the session gives it the keyboard; ttyd's focus on connect
  never does. A tap on the box takes the focus back. So does typing in the session while its prompt is hidden (see above).
- **Touch layer.** On a touch device a layer over the frame takes the touch: a drag scrolls the session (a wheel steps
  it, and it glides), a tap clicks in it without opening the keyboard, and a long press or the key row's Text opens a
  sheet with the screen's text to select and copy. A horizontal swipe still opens the drawer.
- **Key row.** A keyboard button in the message box folds out the key row (`FEED_KEYS` in the page's scripts, and Text):
  Esc, Tab, ↑, Enter, Ctrl-C, Text, ←, ↓, →. Touch only.
- **Text size.** 12px on touch, 13px otherwise, in ttyd's DOM renderer (its canvas is wrong at 2x).
- **Ground and look.** `--feed` is dark unless the person's agent `theme` starts with light (`session_look`). A session the run starts (control sessions and slots) takes the run's own Claude Code theme, `agent-runner` (`session_theme.py`), named only in the settings the run gives its sessions: its colours are 256-colour slots that each browser fills from the page's light or dark, live (`arLook`), so the ground is the page's `--bg`. Code in a diff has its own colours per look too (`CODE` in session_theme.py; plain code is the page's text colour), each 4.5:1 on the diff rows, only for the base in use; a slot the theme's own colours use keeps that colour. Line height 1.3, padding 12px 14px, box lines in the `ar-box` font (they join), minimum contrast 4.5, spinner tips off, reduced motion on. A person's own terminals keep theirs, and a chat open before this keeps its old ground until it restarts.
- **States are cards.** Starting (says so, with the waiting message), loading, ended (the claude.ai/code link, and Resume
  where there is one), a slot with no session (Resume when its task was cut off), no terminal (a headless stream slot,
  a slot with no socket, or Windows before 1809) and no ttyd (how to install it). Each is a `.card` with a title, one
  line of second text and its `.btns`. The state is checked every 3 s.
- **New chat opens at once.** A press that starts a chat about something (Chat on a plan task, concept or setting, Add a task, New concept) opens the
  empty new chat view over the view pressed in, with its box focused. Nothing is sent or started until the first message.

## Touch, keys and access

- A finger's target is at least `--tap`. Hover only adds: whatever it reveals, touch shows or puts in a row's sheet. A chat row's
  three dots open its buttons in the row itself (`.rowacts`): Rename, Pin, and Delete where the dots were, so two taps on
  that spot delete, with Undo. One row is open at a time, and a tap elsewhere only closes it. A
  small button that must be 44px with any pointer gets its target from an `::after` over it (Home's Talk chip), so it
  still looks like the ones beside it.
- Text boxes are 16px or more, so a phone does not zoom.
- Every multi-line message box decides Enter with `boxEnter()` and puts `enterHint()` on its textarea, so a phone's Return makes a new line.
- Touch listeners that watch a gesture are passive, except a `touchmove` that must keep the page still: the drawer
  swipe and a row drag (only a pinned chat's row drags), and the `touchend` that makes a tap's focus on a text box (`kbTapEnd()`, iOS only). Those call
  `preventDefault()` only once the gesture has started, so a scroll stays smooth; the `touchend` calls it only for such a tap.
- A touch is one thing until the finger lifts. One that scrolled never becomes a swipe, and a drawer swipe never scrolls.
  Decide under 10px: iOS cannot cancel a scroll that has begun.
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
- The document never scrolls (`html` and `body` are locked). Only `.body`, `.side`, `.sheet` and small lists scroll.
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
- `.app` keeps full height until the visual viewport changes, and gets it back at once on blur.
- For 900ms (`KB_MS`) after a field is entered or left, `kbFit()` runs each frame on iOS, as events come late and in any
  order, and follows Safari's pan so the header stays on screen.
- The viewport meta has `interactive-widget=resizes-content` for browsers that have it.
- The session and the message box never both hold focus (see The session).

## Sound

- Run speech plays only in the one audio element (`AU.el`), only after the person's tap has allowed it, never while the mic listens.
  The mic's own press counts as that tap: silence is played only after the press has stopped the recognizer (Hold's release, Tap's second tap).
  The press that starts the mic only loads the elements (`load()`, no playback), after `rec.start()`.
  When the browser blocks it, the talk line says what to tap.
- One button stops the reading: the speaker (and the reply's own play button). The mic is never a stop for it; a press on the mic
  cuts a reading and listens in that press.
- Every reading must be watched with `soundWatch()`, since iOS can skip a sound's end event.
- The browser's voice (`speechSynthesis`) is not called before `rec.start()` in a press (B132); run speech clips may be stopped before it.

## Before you finish

1. Phone (390px) and desktop (1280px), light and dark, looked at.
2. Empty, loading, working, failed: each seen.
3. Reduced motion on: everything still works.
4. Scroll half way down, wait for a refresh: nothing moved.
5. A chat or slot with a real session: phone (390px) and desktop, both themes, and a refresh leaves its frame as it was. Scrolling up takes the chips and top bar away over the text and shrinks the box to the slim message box, and scrolling down brings them back; no line moves when they go or come back.
6. A changed motion is watched as a recording or frame strip at 390px, not only stills.
7. `python3 tests/test_web_<area>.py` for each area the change touched (all of `tests/test_web_*.py` for a shared one).
