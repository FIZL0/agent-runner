# F206a: switching chats on the iPhone 15 (checked)

No product code changed in this check; the three fixes it found (a), (b), (c) are in the branch's code and CHANGELOG (F206a). Chat switching, the title switcher, lock, offline and ended states pass on the device. Cellular itself was not used.

## Setup

- Phone: iPhone 15 Pro, iOS 27.0.1, Safari, dark. Rig: `~/repos/iFizBox/tools/ui-15.sh`, with WebDriverAgent MJPEG (`mjpegServerFramerate` 60, forward port 9100). The stream ran at about 27 frames/s and was looked at frame by frame.
- Page: this branch, served from a scratch repo with four stand-in sessions. A small script drew a Claude-like screen through the real attach socket and ttyd. Reached over Tailscale on Wi-Fi.
- No SIM in the phone (SOS only), so cellular was not used. Apple's link conditioner stood in, set with `ios devicestate enable SlowNetworkCondition …`:
  - 3G average: 0.78 Mbps, about 450 ms measured round trip.
  - Edge average: about 1.7 s.
  - 100% loss, for offline.

## Results

- PASS, two chats seen before: the kept screen stays visible under the closing drawer from its first frame, then the moving line, then the live terminal. No move after the fix.
- PASS, a chat never opened and back: the stand-in shows "Loading…" until its messages come (by design, not a fault).
- PASS, title switcher.
- PASS, locked about 20 s: the kept screen stays while unlocking, and the session is live about 1.5 s later.
- PASS, offline: the network was cut at about 4 s, and Reconnecting… shows on the recording about 9.9 s in. Live again within about 2 s of the link returning. Sample `docs/research/F206a-samples/silent-network.png`.
- PASS, ended: the last screen stays and the Resume card sits over the message box. Sample `docs/research/F206a-samples/ended.jpg`.
- No white frame and no Reconnect box in any recording.

## Found and fixed

- (a) When the session redrew with a row more or less, its text jumped a line for a frame or more. The frame is now placed in the same frame as the redraw.
- (b) A chat never opened: the stand-in messages moved up when the session's chips came. The chips row is now there from the first frame.
- (c) A network that goes silent with the socket still open (a cellular dead zone) looked live for the whole outage. Now after 5 s with no answer and no session output, the moving line and Reconnecting… show over the live screen, and the first answer dials again at once (about 1 s on the phone, was about 13 s). `/live` is asked one at a time and given up after 8 s, so dead requests no longer pile up.

## Not checked

- A real mobile network (only the link conditioner stood in).
- The light theme.

## Rig notes

- ufw blocks the scratch ports on the LAN but not over Tailscale, so use Tailscale.
- A unix socket path must be under 108 bytes, so the scratch repo needs a short path.
- Safari's first load of the page on 3G takes several seconds. Wait for it before reading a result.

Added after the recordings, from the review, and checked by the node tests only: a page frozen 15 s or more whose socket still looks open dials again on return, and a `/live` body cut off half way is no answer.
