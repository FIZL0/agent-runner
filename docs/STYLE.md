# Style rules

How the run app (`agent_runner/web_page.html`, Runner Home's page too) looks, moves and speaks. Every change to it
follows these rules, and a change that needs a new rule writes it here in the same commit. `tests/test_web.py`
(`test_style_f83`) checks the ones a machine can check. The words for things are in [GLOSSARY.md](../GLOSSARY.md);
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

All in `:root` at the top of `web_page.html`. Outside `:root` there is no raw colour, no raw duration, and no
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
| `--dur-fast --dur --dur-slow --ease` | motion, below |

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
  steps count, the id and the age. Its answer buttons sit below it.
- **Needs you sheet** (`SHEETS.need`, `needSheet()`): the whole ask in order: title, label, age, id; where and when;
  What to do; What you should see; notes; pictures (`.shot`, full size inside the sheet, Back or Esc goes back); the
  task text folded. The reply box (`.askfoot`) stays on screen at the foot, with the answer buttons.
- **Row** (`.row`, `.crow`, `.prow`, `.srow`, its folding head `.fold`): one line when folded, with an ellipsis. A row that holds more folds
  open on tap in place (`aria-expanded`), and its chevron turns. A setting's row (`.srow`) shows its name, its description and its control; it opens to show the code name and More… (a sheet with the other home and Reset).
- **Section** (`.sec`): a small muted heading and a line. Sections keep the TUI's order.
- **Sheet** (`#sheet`, `openSheet(name)`): more choices about what is on screen. It slides up from the bottom, groups
  its items (`.it`) under `.sec`, closes on the scrim, Esc, a swipe down, or a pick. One sheet, never a sheet over a
  sheet. Its markup comes from `SHEETS[name]()`. A button whose label ends in … opens one or folds open. A Needs you item's
  sheet is a centred dialog (`.dlg`) from 760px wide, not a sheet from the bottom.
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
once; its stand-in shows in the same place. A failure brings Retry, Edit or Discard. `act()` is only for what has
nothing to draw (an interrupt, an order kept) and for Talk, which draws the person's words itself.

A secret never goes through `outbox()`, which the browser keeps: a device's change goes straight to the run
(`toolPost()`), a secret's field is emptied when it is sent or its sheet closes, and a saved secret is shown only as
`set, changed <date>`.

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
a text selection is under way (15 s at most).

## Motion

Motion shows where a thing came from, where it went, or that it changed. Nothing else moves.

| Token | Value | For |
|---|---|---|
| `--dur-fast` | 150ms | a press, a chevron, a fade out |
| `--dur` | 200ms | a card or message coming in, a cross-fade, a view |
| `--dur-slow` | 250ms | the drawer and the sheet |
| `--ease` | `cubic-bezier(.2,.8,.2,1)` | all of them: ease-out |
| `--pulse` | 1.6s | the one loop: work going on now, or the mic listening |

- **Only `transform` and `opacity`**, with `visibility` to take a closed thing out of reach, and a switch's
  `background-color`. Never height, width, top or margin.
- **What animates:** the drawer and the sheet slide; their scrim fades; the Talk dock's mic and box cross-fade;
  Talk's top bar slides off when you scroll up (`.away`, transform only); a session's chips, box and top bar go the same way as the reader scrolls up (`.slim`), and its frame moves with the finger (`feedPlace()`); a card
  or message that is new fades in and rises 6px; a view fades in when you go to it; a state word that changed fades in; a chevron turns; the message box, Talk's words and the sheet glide (transform
  only) to their place when the keyboard opens or closes (`kbGlide()`).
- **What never animates:** a refresh of what is already there, a list reordering under the reader, text being
  typed, the scroll position, anything on first load.
- **New means new:** give a thing that can come and go `data-k="its key"` (and `data-v="its state"` if it has one).
  `enter()` animates only the keys that were not there before, and nothing before the first snapshot. Your own message
  has `data-t` too, so it comes in once, not again when it is sent and when it lands. Never animate from a class in
  the markup: the markup is drawn again on every refresh.
- **A finger leads.** While it drags, the drawer follows it with no transition; on release it settles.
- **Reduced motion:** under `prefers-reduced-motion:reduce` there is none. One rule at the end of the stylesheet
  zeroes every duration, so nothing needs its own. A script's `el.animate()` is not in that rule: it checks
  `matchMedia` itself.

## Scroll

- **The page never moves on its own.** A refresh keeps the reading position in every view (`keepScroll()`): the first
  `data-k` on screen stays where it was. At the very top, new things show.
- **Talk is pinned to its newest words** when you open it, when you send, and while a reply comes in, unless you scrolled up. It has no jump button. The page does not scroll a session at all: the frame keeps its own scroll, and a refresh never redraws it (see The session). Scrolling up in a session takes the frame's bottom first (its chips, box and top bar go, and the thin strip stays), then the session scrolls.
- Going to a view starts at its top; coming back to one you left returns to where you were.
- **A page never reloads by itself.** A new version shows the `.news` notice (`newsDraw()`) with one `.acc` button (Refresh) beside Later. Refresh keeps all typed words (`keepTyped()`) except secrets: a device form is not kept, so Refresh waits while one is open (`refreshHold()`). A new kind of field must be kept there or hold Refresh.
- A reload opens what was open, drawn in the first frame, and never acts by itself: no mic, no sound, no focus on a box.
- A refresh also keeps focus, the caret (`keepFields()`), a text selection, what is folded open, and a code block's
  sideways scroll.
- A notice (`.notice`) floats over the top of the view and never pushes it down, except in a chat: there it has its own
  row under the header, so it covers no text, and `noticeRoom()` keeps the text in place. Elsewhere it floats as
  before. In Talk the top bar may be away while scrolled up, and the notice's row moves up with it (See-through Talk).

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

- **One frame.** The session is one iframe (`#feed`), filling the view behind the header and the message box (`#feedframe`, placed by `feedPlace()`). Its
  address is the run's own (`/t/TOKEN/NAME/`), so https and Runner Home both work.
- **Never redrawn.** A refresh, a snapshot or a state change leaves the frame as it is: it is set once per open, and
  `setHTML()` never touches it. It goes when the chat is left or the page has been hidden for 15 s, so the session gets
  its other viewers' size back. It is always `FOOT_ROWS` (6) rows taller than its room and placed by transform (`feedSpot()`), so bars, a growing box and scrolling never resize it; only a menu or unsent words (the frame fits its room, "whole") or a window size change does.
- **Its bottom lines are past the edge.** The lines under Claude's prompt (the update notice, the status line, the mode, background shells and agents) lie past the frame's edge, so each has its control on the page: a chip row above the message box (`.schips`, a `.chip` per thing to say, none when there is nothing) with Working (its sheet has Stop), the mode (Shift+Tab pressed one at a time and checked; the status line is in that sheet as text), N shells (what runs, its output tail, Stop through `/tasks`), N agents (Open through `/tasks`) and Update (the command, run on the run's machine; only known update commands; Restart chat for an idle c2 and up). A chip shows only when there is something to say. Its sheets are `sesswork`, `sessmode`, `sessshells`, `sessagents` and `sessupdate`. `feedFoot()` finds the prompt on screen. When it cannot (a menu, a question, an unknown look) or the prompt holds unsent words, nothing is hidden: the frame fits its room, and on touch the key row stands in place of the chips.
- **Typing goes to the box while the prompt is hidden.** A character, Shift+Enter or a paste in the frame goes to the message box when `feedHand()` says the prompt is hidden: `feedTyped()` does it, asked by session_frame.HEAD on keydown and paste (B190). Other keys (plain Enter, Esc, arrows, Ctrl combinations), input-method composing, and every key during a menu or question stay the session's. Shift+Enter with unsent words in the prompt is a newline to the session.
- **Hidden lines have their controls.** Whatever the frame hides at its bottom must have its control on the page, or the frame must not hide it.
- **While Claude works.** The message box has Force send (`.act.force`) and Stop beside it (`.act.halt`). Force send interrupts with Escape, waits until Claude Code's own status is at rest, and sends once: queued messages go in as a turn first, and an unanswered prompt put back in the input stays above the new one; it is not sent if the session never rests. Stop sends one Ctrl+C, not again for 3 s, and never to an idle session. The status is read from `/live/NAME`.
- **Box and session never both hold focus.** A mouse press in the session gives it the keyboard; ttyd's focus on connect
  never does. A tap on the box takes the focus back. So does typing in the session while its prompt is hidden (see above).
- **Touch layer.** On a touch device a layer over the frame takes the touch: a drag scrolls the session (a wheel steps
  it, and it glides), a tap clicks in it without opening the keyboard, and a long press or the key row's Text opens a
  sheet with the screen's text to select and copy. A horizontal swipe still opens the drawer.
- **Key row.** A keyboard button in the message box folds out the key row (`FEED_KEYS` in `web_page.html`, and Text):
  Esc, Tab, ↑, Enter, Ctrl-C, Text, ←, ↓, →. Touch only.
- **Text size.** 12px on touch, 13px otherwise, in ttyd's DOM renderer (its canvas is wrong at 2x).
- **Ground and look.** `--feed` is dark unless the person's agent `theme` starts with light (`session_look`). A session the run starts (control sessions and slots) takes the run's own Claude Code theme, `agent-runner` (`session_theme.py`), named only in the settings the run gives its sessions: its colours are 256-colour slots that each browser fills from the page's light or dark, live (`arLook`), so the ground is the page's `--bg`. Line height 1.3, padding 12px 14px, box lines in the `ar-box` font (they join), minimum contrast 4.5, spinner tips off, reduced motion on. A person's own terminals keep theirs, and a chat open before this keeps its old ground until it restarts.
- **States are cards.** Starting (says so, with the waiting message), loading, ended (the claude.ai/code link, and Resume
  where there is one), a slot with no session (Resume when its task was cut off), no terminal (a headless stream slot,
  a slot with no socket, or Windows before 1809) and no ttyd (how to install it). Each is a `.card` with a title, one
  line of second text and its `.btns`. The state is checked every 3 s.
- **New chat opens at once.** A press that starts a chat about something (Chat on a plan task, concept or setting, Add a task) opens the
  empty new chat view over the view pressed in, with its box focused. Nothing is sent or started until the first message.

## Touch, keys and access

- A finger's target is at least `--tap`. Hover only adds: whatever it reveals, touch shows or puts in a row's sheet. A
  small button that must be 44px with any pointer gets its target from an `::after` over it (Home's Talk chip), so it
  still looks like the ones beside it.
- Text boxes are 16px or more, so a phone does not zoom.
- Every multi-line message box decides Enter with `boxEnter()` and puts `enterHint()` on its textarea, so a phone's Return makes a new line.
- Touch listeners that watch a gesture are passive, except a `touchmove` that must keep the page still: the drawer
  swipe and a row drag, and the `touchend` that makes a tap's focus on a text box (`kbTapEnd()`, iOS only). Those call
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
- `.app` keeps full height until the visual viewport changes, and gets it back at once on blur.
- For 900ms (`KB_MS`) after a field is entered or left, `kbFit()` runs each frame on iOS, as events come late and in any
  order, and follows Safari's pan so the header stays on screen.
- The viewport meta has `interactive-widget=resizes-content` for browsers that have it.
- The session and the message box never both hold focus (see The session).

## Sound

- Run speech plays only in the one audio element (`AU.el`), only after the person's tap has allowed it, never while the mic listens.
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
5. A chat or slot with a real session: phone (390px) and desktop, both themes, and a refresh leaves its frame as it was. Scrolling up hides the chips, box and top bar, the strip stays, and scrolling down brings them back.
6. `python3 tests/test_web.py`.
