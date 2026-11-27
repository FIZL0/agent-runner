"""B883: the session's page fits its terminal again when the font comes late or its box changes size."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_runner import session_frame  # noqa: E402

page = session_frame.with_head(b'<html><head></head><body></body></html>', 'chat-1', 'dark').decode()
fails = []
for want in ('function refit()', 'requestAnimationFrame(refit)', 'new ResizeObserver(', "getElementById('terminal-container')"):
    if want not in page:
        fails.append(f'missing in head: {want}')
for f in fails:
    print('FAIL', f)
print('ok' if not fails else f'{len(fails)} failed')
sys.exit(1 if fails else 0)
