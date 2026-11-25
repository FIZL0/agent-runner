"""F420: PR mode's open pull requests (see `pr`): how many may be open before new tasks wait, and each with its link and
state as status, the run page, the terminal UI and Needs you show it.

It asks GitHub nothing: `pr._look_at` keeps what each look saw (`seen`) in the pull request's record.
"""
from __future__ import annotations

import datetime as dt

from agent_runner import plan as P, pr
from agent_runner import state as S

LABEL = 'PR'  # the Needs you label


def seen(got: dict) -> dict:
    """What `gh pr view` says of an open pull request, as its record keeps it for `state_of`."""
    from agent_runner import pr_feedback
    return {'review': str(got.get('reviewDecision') or ''), 'conflict': got.get('mergeable') == 'CONFLICTING',
            'ci_red': any(c['state'] in pr_feedback.RED for c in pr_feedback.checks(got).values())}


def open_prs(c=None) -> list[dict]:
    """The records of the pull requests that are open on GitHub, oldest first; [] when PR mode is off."""
    c = c or S.C
    return [x for x in pr.read(c) if x['number'] and x['state'] in ('', 'OPEN')] if c and c.pr else []


def full(c=None) -> int:
    """How many pull requests are open when no new task may start for them ([git] pr_max, 0: no limit), else 0."""
    c = c or S.C
    most = c.pr_max if c and c.pr else 0
    n = len(open_prs(c)) if most else 0
    return n if most and n >= most else 0


def started() -> frozenset[str]:
    """The tasks that are not new: one with an open pull request, or whose session goes on with the work it has."""
    refs = S.git('for-each-ref', '--format=%(refname)', 'refs/heads/asked/', 'refs/heads/waiting/').stdout.split()
    return frozenset(t for x in open_prs() for t in x['ids']) | {r.rsplit('/', 1)[1] for r in refs}


def state_of(x: dict) -> str:
    """An open pull request's state in words: 'CI red, changes asked', else 'waits for review'."""
    asked = x.get('review') == 'CHANGES_REQUESTED' or bool((x.get('round') or {}).get('items'))
    said = [w for w, on in (('CI red', x.get('ci_red')), ('changes asked', asked),
                            ('conflicts with main', x.get('conflict'))) if on]
    return ', '.join(said) or ('approved, waits to be merged' if x.get('review') == 'APPROVED' else 'waits for review')


def rows(c=None, titles: dict[str, str] | None = None) -> list[dict]:
    """Each open pull request: {'id' (its Needs you item), 'number', 'url', 'ids' (its tasks), 'title', 'state', 'at'};
    [] when they do not read."""
    c = c or S.C
    try:
        xs = open_prs(c)
        if xs and titles is None:
            titles = P.titles(c.done, c.todo, width=200)
        return [{'id': f'pr-{x["number"]}', 'number': x['number'], 'url': x['url'], 'ids': list(x['ids']),
                 'title': (titles or {}).get(x['key']) or (titles or {}).get(x['ids'][0]) or x['key'],
                 'state': state_of(x), 'at': x.get('at') or 0} for x in xs]
    except (OSError, SystemExit, ValueError, KeyError, AttributeError):
        return []


def asks(c=None) -> list[tuple]:
    """The open pull requests as Needs you items, in `plan.asks`'s shape with the stamp eighth."""
    return [(LABEL, r['id'], '', f'Pull request #{r["number"]}: {r["state"]}', r['url'], r['title'], False,
             dt.datetime.fromtimestamp(r['at']).strftime('%Y-%m-%d %H:%M') if r['at'] else '') for r in rows(c)]


def limit_line(c=None) -> str:
    """Why no new task starts, as status says it; '' when one may."""
    try:
        n = full(c)
    except (OSError, ValueError, KeyError, AttributeError):
        return ''
    return f'{n} pull request{"s are" if n != 1 else " is"} open: no new task starts until you merge or close one' if n else ''


def lines(c=None) -> list[str]:
    """The run page's and the terminal UI's status lines: the limit, then '#3 F1: waits for review · <link>'."""
    return [x for x in (limit_line(c),) if x] + \
        [f'#{r["number"]} {", ".join(r["ids"])}: {r["state"]} · {r["url"]}' for r in rows(c)]


def text(titles: dict[str, str] | None = None) -> list[str]:
    """`status`'s lines: a row each, its link on a line of its own."""
    got = rows(titles=titles)
    out = [x for x in (limit_line(),) if x] + (['pull requests:'] if got else [])
    for r in got:
        out += [f'  #{r["number"]} {", ".join(r["ids"])} {r["title"]} · {r["state"]}', f'    {r["url"]}']
    return out


def mark(queue: list[dict], prs: list[dict], up: bool) -> list[dict]:
    """The queue's rows with what its pull requests keep waiting, in the words of state 'tool': a task with an open one
    waits for that, one `after` it for its merge, and with a run up a new one for the limit."""
    of = {t: r for r in prs for t in r['ids']}
    limit = up and limit_line()
    on = started() if limit else ()
    for q in queue:
        if q.get('release') or q.get('under_way') or q.get('state') not in ('ready', 'critical', 'after'):
            continue
        if r := of.get(q['id']):
            q.update(state='tool', tool_wait=f'pull request #{r["number"]}: {r["state"]}', pr_wait=True)
        elif held := [of[t] for t in q.get('after') or [] if t in of]:
            nums = ', '.join(f'#{n}' for n in dict.fromkeys(r['number'] for r in held))
            q.update(state='after', after_title=f'{q["after_title"]} (pull request {nums} is not merged)')
        elif limit and q['state'] != 'after' and q['id'] not in on:
            q.update(state='tool', tool_wait='waits for an open pull request to be merged', pr_wait=True)
    return queue
