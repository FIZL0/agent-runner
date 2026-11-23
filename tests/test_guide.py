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

print('B108: a page never reaches the person as a bare local path')
check(guide.NO_PAGE in guide.control_topic('output'), 'the output page carries the no-Artifact fallback')
check(guide.NO_PAGE in guide.topic('concepts'), 'the concepts page carries it')
skills = guide.control_skills('agent-runner')
check(any(guide.NO_PAGE in s for s in skills.values()), 'the hint skills carry it')
has(guide.NO_PAGE, r'say plainly in one line that you could not\s+publish', 'says so plainly when neither works')
has(guide.NO_PAGE, r'Never answer with a local file path', 'never a bare local path')
has(guide.NO_PAGE, r'Remote Control cannot open one', 'says why')
check('no Artifact tool: send the file with SendUserFile)' not in guide.control_topic('output'),
      'the old SendUserFile-only fallback is gone')

print('B108: runner-started control sessions get the Artifact tool')
import os  # noqa: E402
from agent_runner import control  # noqa: E402
old = os.environ.pop(control.ARTIFACT_ENV, None)
try:
    check(control.control_env().get('CLAUDE_CODE_ARTIFACT') == '1', 'control_env turns the Artifact tool on')
    os.environ[control.ARTIFACT_ENV] = '0'
    check(control.control_env().get('CLAUDE_CODE_ARTIFACT') == '0', 'a value the person set is kept')
finally:
    os.environ.pop(control.ARTIFACT_ENV, None)
    if old is not None:
        os.environ[control.ARTIFACT_ENV] = old

print('F140: a queued concept task puts option buttons on its page')
from agent_runner import brief  # noqa: E402
concept = brief.CONCEPT_PROMPT.format(runner='agent-runner', tid='K7')
has(concept, r'`agent-runner pick-links K7 A,B,C`', 'the K brief runs pick-links with its own id')
has(concept, r'plain `<a href>`\s+button', 'each link goes on its option as a plain button')
has(concept, r'no https address,\s+leave the buttons off', 'no https address: no buttons')

raise SystemExit(1 if FAILED else print('\nall checks passed'))
