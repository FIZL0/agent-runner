# R17: F170's chat controls on the iPhone 15

Checked 2026-11-25 on the iPhone 15 Pro (iOS 27, Safari) through the remote rig (`ui-15.sh`), against the live run page
of this repo (0.71.0, which has F170), reached over the tailnet's https address. The phone could not load the LAN
address (`http://192.168.0.118:8770`): the page hung at 0 %. The tailnet https address loaded at once.

Two sessions were used: slot s1 (a control session, idle behind a gate) for the bars and the keyboard, and this task's
own slot (s4, busy: spinner and tool output redrawing) for the flicker and the box lines.

| Check | Result |
|---|---|
| Hidden bottom lines stay hidden with no flicker while the agent redraws | Pass. 14 screenshots, about 1 s apart, while the session redrew (spinner, tool output, a new line every 2 s): the text above the chips changed between frames, and the region from the chip row down to the message box was pixel-identical in all 14. The update notice, status line and mode line never showed under Claude's prompt; the chips (Working, Bypass, shells, agents) stood in their place. |
| Bars go and come with the finger, no jump | Pass. A drag down (scroll up) took the top bar and chips away and slimmed the box; a drag back brought them back, and the session lay on the same pixels as before the scroll (full-screen compare by eye: same lines at the same heights). |
| Keyboard opens and closes cleanly | Pass. Tapping the box raised it with the chips above the keyboard, nothing clipped, the top bar stayed; Done on the keyboard's bar closed it and the layout went back to the same one as before. |
| Box lines join in Safari | Pass. A printed table (`┌┬┐├┼┤└┴┘│─`) drew joined corners and tees, with no gaps between rows. Only the first rows of the table showed (the tool result folds to 3 lines), so `╭╮╰╯`, `═║╔╗` and the block elements `▀▄█▌▐` were seen only in the command's echo: the blocks drew as solid squares, the double lines joined. |

## Seen on the way, not asked

- Under the slim box (bars away), the half of one session line shows below the box's lower edge for a moment while
  scrolled up (r17g in the run's screenshots: "Brewed for 5s" cut by the box). It is the history showing past the slim
  box, and it was not there once the bars were back. Not filed: it is the session's own text, and the box is
  see-through by design (F171). Look again if it bothers.
- iOS's own password bar ("omarchy-desktop.beetal-ling.ts.net") sits above the keyboard when the box takes focus on a
  session. It is Safari's, not the page's; `autocomplete="off"` does not remove it for a text box Safari takes for a
  login field.

## Not checked

- A redraw that moves the pill (Jump to bottom, N new messages) while scrolled up, and a long scroll with momentum: the
  scroll test was one 600 px drag each way.
- Dark mode only; light was not tried.
- This used the run's own page, so nothing was changed on the phone besides Safari's tabs (the unlock closed them).
