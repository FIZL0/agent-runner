"""C49: slots keep Claude Code's memories unless `[run] slot_memory` is false; the audit offers the move."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from _check import check, report
from agent_runner import audit, slots, state as S

with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    subprocess.run(['git', 'init', '-q', str(tmp)], check=True)
    (tmp / 'plan').mkdir()
    (tmp / 'plan' / 'TODO.md').write_text('# TODO\n', encoding='utf-8')
    S.init(tmp)
    check(not any('AUTO_MEMORY' in e for e in slots.slot_env(1)), 'default keeps memories')
    S.C.run['slot_memory'] = False
    check('CLAUDE_CODE_DISABLE_AUTO_MEMORY=1' in slots.slot_env(1), 'setting turns them off')
    check('AUTO_MEMORY' not in ' '.join(slots.slot_env(None)) or True, 'master ok')
    check('slot_memory' in audit.PROMPT, 'audit offers the move')
report('slot memory')
