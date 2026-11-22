"""B82: the control brief never offers `! <cmd>` (it fails on Remote Control and in the apps) and says what to do
instead: run it yourself, or name the machine's terminal and give the plain or non-interactive command."""
from __future__ import annotations

from _check import FAILED, check, has

from agent_runner import guide

print('the control brief overrides the ! prefix')
text = guide.CONTROL.format(cmd='agent-runner', repo='demo', needs='Needs you', watch='', answer='', log='run.log')
check(guide.NO_BANG in text, 'NO_BANG is in the formatted control brief')
has(text, r'Never offer `! <command>`', 'says never to offer the ! prefix')
has(text, r'Shell\s+commands are only available in local sessions', 'quotes the error the person would see')
has(text, r'Remote Control or the apps', 'names where it fails')
has(text, r'Run the command yourself when it needs no secret', 'runs it itself when it can')
has(text, r'terminal on this machine, named by its hostname', 'names the machine for a command that needs a secret')
has(text, r'plain\s+command, without the `!`', 'gives the plain command')
has(text, r'--password-stdin', 'offers the non-interactive form')

print('C22: the person gets the run page link to watch the run, never an attach line')
has(text, r'`run page:` link status prints,\s+never an `attach` line', 'the brief gives the run page link')
check('attach s' not in text, 'the brief names no attach sN line')

raise SystemExit(1 if FAILED else print('\nall checks passed'))
