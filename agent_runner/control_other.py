"""B785: a control session's question about another project, answered after the session closed. The run filed it as a
task here (`control.file_control_ask`), so a slot carries out the answer, and B103 refuses a slot's plan writes in
another project. The person's answer is the permission for one of them: `plan add`, in a project the question names."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ASKED = re.compile(r'\*\* \([^)]*\) Control session \d+ asked the person: "(.*?)" Carry on from their answer ')
ROUTE = ('When the answer is to queue work in another project the question names, run `plan add` in that project\'s '
         'own checkout: the answer allows that one command there')
NO = re.compile(r'\W*(?:no|not|never|don\W?t|do not|cancel|skip|stop|nothing|none|neither|later|keep|leave|wait|hold|only here|here)\b', re.I)
YES = re.compile(r'\W*(?:yes|yep|yeah|ok|okay|sure|go|do it|do so|please|queue|add|file|both|all)\b', re.I)


def says_yes(said: str, question: str, project: str) -> bool:
    """Whether the answer `said` is a yes to `question` for `project`: a word of yes, or one of the options in the
    question's closing bracket that is not a no. A project only the options name must be in the answer."""
    b = re.search(r'\[([^\[\]]+)\](?:\s+https?://\S+)*\s*$', question)
    options = [o.replace('(recommended)', '').strip() for o in re.split(r'\s+/\s+', b[1])] if b else []
    names = re.compile(rf'(?<![\w-]){re.escape(project)}(?![\w-])')
    if not names.search(question[:b.start()] if b else question) and not (names.search(question) and names.search(said)):
        return False
    return not NO.match(said) and bool(YES.match(said) or any(o and said.lower().startswith(o.lower()) for o in options))


def allowed(line: str, project: str) -> bool:
    """Whether the task text `line` is a control session's question that names `project` (its folder's name, as a
    whole word) and the person's last answer to it is a yes (`says_yes`). A change of direction ('do this instead')
    withdraws it."""
    m = ASKED.search(line)
    if not m:
        return False
    from agent_runner.plan import URL
    q = ' '.join(URL.sub('', m[1].split(' — ')[0], count=1).split()).rstrip(' :,;')  # as `plan.asks` reads it
    # with a link of its own in the question, the session's link stays in the noted words
    answers = re.split(rf' — your answer \(DECIDE {re.escape(q)}(?: https?://\S+)?\): ', line[m.end():])
    if len(answers) < 2:
        return False
    said = answers[-1]
    return ' — you said' not in said and says_yes(said.split(' — ')[0], m[1], project)


def may_add(wt: str, mine: Path, here: Path) -> bool:
    """Whether the slot in worktree `wt` of project `mine` may `plan add` in `here`: the task on its branch, as the
    plan of `mine` has it, is `allowed`."""
    from agent_runner import plan as P
    from agent_runner.config import cfg
    r = subprocess.run(['git', 'branch', '--show-current'], cwd=wt, capture_output=True, text=True)
    branch = r.stdout.strip()
    if r.returncode or not branch.startswith('task/'):
        return False
    try:
        return allowed(' '.join(l.strip() for l in P.section(cfg(mine).todo, branch[len('task/'):])), here.name)
    except (SystemExit, OSError):
        return False
