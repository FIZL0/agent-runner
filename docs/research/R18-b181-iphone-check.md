# R18: B181's Return on the iPhone 15 (checked)

No product code changed; this is research only. Return makes a new line in the home, chat and Talk boxes. Two parts fail (the concept box does not grow, the slash menu does not pick), and one part needs a person.

## Setup

- Phone: iPhone 15 Pro, iOS 27.0.1, Safari, dark. Rig: `~/repos/iFizBox/tools/ui-15.sh` (taps the soft keyboard's Return key through go-ios/WDA).
- Page: Runner Home at `https://omarchy-desktop…ts.net:8771`, serving 0.62.0. The served page has B181's `boxEnter` and `growKin`, so the check is valid.
- Nothing was sent or queued. Drafts were cleared and the phone lock was released.

## Results

- PASS Home box ("How can I help with the run?"): Return makes a new line, the box grows to 3 lines, nothing is sent. The Return key shows the return arrow (`enterkeyhint=enter`). Sample `docs/research/R18-samples/home-lines.png`.
- PASS chat box (Chat 23, a real session): new line, box grows, not sent. Sample `chat-lines.png`.
- PASS Talk typing box: new line, box grows, not sent. Sample `talk-lines.png`.
- PASS in part, concept box (Concepts, + button): Return makes a new line and queues nothing, but the box does not grow. After q, four Returns and z, it stayed 3 rows (about 87 pt) and the text scrolled inside it. Expected about 126 px of content up to the 160 px cap from `growKin`. Sample `klines2.png`. Filed as B187.
- FAIL slash menu: "/" typed in the Talk typing box opens the menu with /run highlighted (`slash.png`). Return does not pick /run: the menu closes and the box gets a new line (`slash-picked.png`). B181 says Return still picks on touch. Filed as B188. Suspected cause, not confirmed: iOS sends the soft keyboard's keydown as composing (keyCode 229), so the handler in `agent_runner/web_page.html` (the data-in keydown, `slashOpen` / `slashTake`) misses the Enter. B188 note: `slash.png` shows the keyboard auto-shifted, so Return likely carried shiftKey, which the keydown handler excluded from picking before closing the menu (matches what was seen); 229 was not ruled out; B188 handles both. The phone was passcode-locked on 2026-11-24, so neither the event nor the fix was seen on the device.
- NOT CHECKED, needs a person (a CONFIRM): Ctrl/Cmd+Enter sends from a hardware keyboard on a touch device, and the Send button sends. The rig cannot send Ctrl/Cmd modifiers, no hardware keyboard is on the phone, and Send was not tapped so no real message went out.

## Rig notes

- The phone relocks between commands, so run `wake` before each step.
- `ui-15.sh type` with a newline does not press Return (the shell strips it). Tap the Return key at 1024,2275 instead.
