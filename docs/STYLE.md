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
`border-radius` or `font-size` in px (a circle is `50%`).

| Tokens | Use |
|---|---|
| `--bg --side --surface --bubble` | page, sidebar, card, your own words and a pressed row |
| `--fg --muted --faint` | text, second text, placeholder and hint |
| `--line --line2` | a quiet edge, a control's edge |
| `--accent --accent2 --onaccent` | the one thing to press, its pressed shade, text on it |
| `--ok --warn --bad --onbad` | landed or running, needs you or paused, failed or destructive |
| `--scrim --shadow --lift` | behind a sheet, under a floating thing, under the message box |
| `--fs-xs --fs-s --fs-m --fs-b --fs-l --fs-xl` | 11 hint, 12 badge, 13 second text, 15 body, 17 card title, 30 greeting |
| `--r-s --r-m --r-l --r-xl --r-full` | 8 small control, 10 button and row, 16 card and sheet, 20 message box, pill |
| `--s1` to `--s6` | 4, 8, 12, 16, 24, 32: gaps and padding |
| `--tap` | 44px: the least a finger gets |
| `--dur-fast --dur --dur-slow --ease` | motion, below |

A state colour is never the only sign: there is a word or an icon with it. Text on `--bg` and `--surface` uses `--fg`
or `--muted`; `--faint` is for what you can do without.

Type: `--sans` for the app, `--serif` for headings and an ask's words, `--mono` for code and a chat (which looks like
the terminal, in the `[ui] theme`'s colours, inside `.main.term` only).

## Parts

- **Button** (`.btn`): an action in words, a verb first. `.pri` the likely answer, `.acc` the one main action,
  `.bad` the Yes of a destructive confirm. At most one `.pri` or `.acc` in a card. An icon button (`.icon`, `.tool`)
  has an `aria-label` and a `title`.
- **Card** (`.card`, `card()`): one thing. `.tap` opens something; `.need` waits on the person. Title, one line of
  second text, then `.btns`.
- **Row** (`.row`, `.crow`, `.prow`, `.srow`): one line when folded, with an ellipsis. A row that holds more folds
  open on tap in place (`aria-expanded`), and its chevron turns.
- **Section** (`.sec`): a small muted heading and a line. Sections keep the TUI's order.
- **Sheet** (`#sheet`, `openSheet(name)`): more choices about what is on screen. It slides up from the bottom, groups
  its items under `.sec`, closes on the scrim, Esc, a swipe down, or a pick. One sheet, never a sheet over a sheet. Its markup comes from
  `SHEETS[name]()`.
- **Badge** (`.n`): a count of what waits on the person, never of anything else. **Dot** (`.bdot`): something
  waits, no count. **Pill** (`.pill`): a state in a word or two. Same words on every page: Running, Paused,
  Stopping, Caps forced, Not up.
- **Confirm**: asked in place (`sureHTML`), naming what is cut off, Yes then No. No browser dialog, ever. In the TUI
  the key is pressed twice.
- **Setting or form control**: a label, the control that fits the type (switch, select, number, text), then help in
  `.small`. A field that must survive a refresh has `data-f="key"`.

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
nothing to draw (an interrupt, an order kept).

## Words

- Plain words, a verb first on a button, sentence case, no exclamation marks, no dash between clauses.
- The glossary's term, and the same one everywhere: Needs you, slot, task, landed, concept, chat.
- A task is named by its title. Its id may follow, small.
- Say what happens, in the person's terms: "Stop (running tasks finish)".
- Numbers with their unit: `6 min`, `2 of 3 slots`, `week 62%`.

## Motion

Motion shows where a thing came from, where it went, or that it changed. Nothing else moves.

| Token | Value | For |
|---|---|---|
| `--dur-fast` | 150ms | a press, a chevron, a fade out |
| `--dur` | 200ms | a card or message coming in, a cross-fade, a view |
| `--dur-slow` | 250ms | the drawer and the sheet |
| `--ease` | `cubic-bezier(.2,.8,.2,1)` | all of them: ease-out |
| `--pulse` | 1.6s | the one loop: work going on now |

- **Only `transform` and `opacity`** (and a colour on press). Never height, width, top or margin.
- **What animates:** the drawer and the sheet slide; their scrim fades; the Talk dock's mic and box cross-fade; a card
  or message that is new fades in and rises 6px; a view fades in when you go to it; a state word that changed fades in; a chevron turns.
- **What never animates:** a refresh of what is already there, a list reordering under the reader, text being
  typed, the scroll position (a jump to the latest is instant), anything on first load.
- **New means new:** give a thing that can come and go `data-k="its key"` (and `data-v="its state"` if it has one).
  `enter()` animates only the keys that were not there before. Never animate from a class in the markup: the
  markup is drawn again on every refresh.
- **A finger leads.** While it drags, the drawer follows it with no transition; on release it settles.
- **Reduced motion:** under `prefers-reduced-motion:reduce` there is none. One rule at the end of the stylesheet
  zeroes every duration, so nothing needs its own.

## Scroll

- **The page never moves on its own.** A refresh keeps the reading position in every view (`keepScroll()`): the first
  `data-k` on screen stays where it was. At the very top, new things show.
- **A chat is pinned to its newest message** when you open it, when you send, and while a reply comes in, unless you
  scrolled up. Then it stays put and the jump-to-latest button shows.
- Going to a view starts at its top; coming back to one you left returns to where you were.
- A refresh also keeps focus, the caret, a text selection, what is folded open, and a code block's sideways scroll.
- A notice (`.notice`) floats over the top of the view. It never pushes it down.

## Touch, keys and access

- A finger's target is at least `--tap`. Hover only adds: whatever it reveals, touch shows or puts in a row's sheet.
- Text boxes are 16px or more, so a phone does not zoom.
- Touch listeners that watch a gesture are passive. A swipe leaves text boxes, sideways scrollers, a row being
  dragged and mostly vertical moves alone.
- Every control is a `button`, `a` or form field, reachable by Tab, with a visible `:focus-visible` ring. Esc closes the topmost thing only.
- Live words (the talk line, the toast) have `role="status"`.

## Before you finish

1. Phone (390px) and desktop (1280px), light and dark, looked at.
2. Empty, loading, working, failed: each seen.
3. Reduced motion on: everything still works.
4. Scroll half way down, wait for a refresh: nothing moved.
5. `python3 tests/test_web.py`.
