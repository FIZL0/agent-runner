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

print('C40a: the guide and the K brief put no answer buttons on a concept page')
from agent_runner import brief, guide  # noqa: E402
concept = brief.CONCEPT_PROMPT.format(runner='agent-runner', tid='K7')
check('pick-links' not in concept, 'the K brief names no pick-links')
has(concept, r'no answer buttons', 'the K brief says no answer buttons')
import inspect  # noqa: E402
check('pick-links' not in inspect.getsource(guide), 'the guide names no pick-links')

print('F200a: the brief and the queue guide say own modules, and parts in different files')
import tempfile  # noqa: E402
from _check import git  # noqa: E402
from agent_runner import runner as R  # noqa: E402
from pathlib import Path  # noqa: E402
has(guide.OWN_FILES, r'module and a test file of its own', 'a new area gets its own module and test file')
has(guide.SPLIT_FILES, r'parts that name different files', 'parts name different files')
queue = guide.control_topic('queue')
for name, where in (('the guide', guide.GUIDE), ('guide queue', queue)):
    check(guide.OWN_FILES in where and guide.SPLIT_FILES in where, f'{name} carries both rules')
check(guide.SPLIT_FILES in brief.SPLIT_PROMPT.format(runner='agent-runner', tid='F1', why='x'),
      'a session told to split its task gets the rule')
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp).resolve()
    git(root, "init", "-q")
    (root / 'plan').mkdir()
    (root / 'plan/TODO.md').write_text('# Goal\n\n## Now\n- [ ] **F1** x | files: a.py\n- [ ] **K1** y | files: b.py\n',
                                       encoding='utf-8')
    (root / 'plan/DONE.md').write_text('# Done\n', encoding='utf-8')
    (root / 'own.md').write_text('Do {tid}.\n{brief}\n', encoding='utf-8')
    for conf, what in (('', 'the built-in prompt'), ('prompt = "own.md"\n', 'a project\'s own prompt')):
        (root / 'runner.toml').write_text(f'[run]\n{conf}', encoding='utf-8')
        R.init(root)
        for slots in (1, 2):
            p = brief.prompt_for('F1', 1, slots, root, 'main')
            check(guide.OWN_FILES in p and guide.SPLIT_FILES in p, f'{what} carries both rules with {slots} slot(s)')
        check(guide.OWN_FILES not in brief.prompt_for('K1', 1, 1, root, 'main'), 'a concept, which builds nothing, does not')
print('F440: the headline names how the tasks left divide')
topics = guide.control_topic('summary') + guide.control_topic('output')
has(topics, r'23 tasks left: 6 can start now, 12 wait on another task, 5 need you', 'the summary headline')
has(topics, r'tasks left: …` line \(how many can start\s+now, wait on another task, need you', 'the how-much-is-left answer')

print('F192d: the brief names the option-tasks store')
has(text, r'`\.runner/option-tasks/`', 'names where option tasks go')
has(text, r'\{"question": <the question>, "options"', 'its shape, braces kept by format')

raise SystemExit(1 if FAILED else print('\nall checks passed'))
