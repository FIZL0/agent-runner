#!/usr/bin/env python3
"""B862: a Claude model with adaptive thinking only is never sent thinking {type: 'disabled'}."""
from __future__ import annotations

import json
import shutil
import sys
import subprocess
from pathlib import Path

from _check import check, eq, report

from agent_runner import runner as R


def _run(js_call: str):
    src = (Path(R.__file__).parent / 'harness.mjs').read_text(encoding='utf-8')
    start = src.index('export function thinkingOff')
    body = src[start:src.index('\n}\n', start) + 3].replace('export ', '')
    out = subprocess.run(['node', '-e', body + f'console.log(JSON.stringify({js_call}));'],
                         capture_output=True, text=True, timeout=30)
    return json.loads(out.stdout)


def test_adaptive_model_sends_no_disabled_thinking():
    sonnet = {'id': 'claude-sonnet-5.5', 'api': 'anthropic-messages', 'reasoning': True,
              'thinkingLevelMap': {'xhigh': 'xhigh', 'max': 'max'}, 'compat': {'forceAdaptiveThinking': True}}
    got = _run(f'thinkingOff({json.dumps(sonnet)})')
    eq(got['thinkingLevelMap'].get('off', 'missing'), None, 'off is unsupported, so Pi sends no thinking field')
    eq(got['thinkingLevelMap']['max'], 'max', 'the other levels stay')


def test_claude5_without_compat_flag_b864():
    sonnet = {'id': 'claude-sonnet-5.5', 'api': 'anthropic-messages', 'reasoning': True, 'compat': {}}
    got = _run(f'thinkingOff({json.dumps(sonnet)})')
    eq(got['thinkingLevelMap'].get('off', 'missing'), None, 'B864: a Claude 5 model sends no disabled thinking')
    old = {'id': 'claude-sonnet-4-5', 'api': 'anthropic-messages', 'reasoning': True, 'compat': {}}
    check(_run(f'thinkingOff({json.dumps(old)})') == old, 'an older Claude model is left as it is')


def test_other_models_unchanged():
    for m in ({'id': 'x', 'api': 'anthropic-messages', 'reasoning': True, 'compat': {}},
              {'id': 'g', 'api': 'openai-completions', 'reasoning': True, 'compat': {'forceAdaptiveThinking': True}},
              {'id': 'p', 'api': 'anthropic-messages', 'reasoning': False}):
        check(_run(f'thinkingOff({json.dumps(m)})') == m, 'a model that takes thinking off is left as it is', m)


def main() -> int:
    if not shutil.which('node'):
        print('skip: no node')
        return 0
    return report([test_adaptive_model_sends_no_disabled_thinking, test_claude5_without_compat_flag_b864, test_other_models_unchanged])


if __name__ == '__main__':
    sys.exit(main())
