"""F510: [run] issues_trust per-author modes."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_runner import issues as I  # noqa: E402


def iss(login, role):
    return {'number': 1, 'author': {'login': login}, 'authorAssociation': role}


def main():
    assert I.trust_of('trust') == 'trust'
    assert I.trust_of('skeptical') == 'skeptical'
    assert I.trust_of('Contributors') == 'contributors'
    assert I.trust_of('members') == 'members'
    assert I.trust_of('bogus') == 'skeptical' and I.trust_of(None) == 'skeptical'
    assert I.issue_trust(iss('x', 'NONE'), I.trust_of('bogus')) == 'skeptical'

    assert I.issue_trust(iss('x', 'NONE'), 'trust') == 'trust'
    assert I.issue_trust(iss('x', 'OWNER'), 'skeptical') == 'skeptical'
    assert I.issue_trust(iss('Me', 'NONE'), 'skeptical', 'me') == 'trust'

    c = I.trust_of('contributors')
    for role in ('OWNER', 'MEMBER', 'COLLABORATOR', 'CONTRIBUTOR'):
        assert I.issue_trust(iss('x', role), c) == 'trust', role
    for role in ('NONE', 'FIRST_TIMER', 'FIRST_TIME_CONTRIBUTOR', ''):
        assert I.issue_trust(iss('x', role), c) == 'skeptical', role

    m = I.trust_of('members')
    for role in ('OWNER', 'MEMBER', 'COLLABORATOR'):
        assert I.issue_trust(iss('x', role), m) == 'trust', role
    assert I.issue_trust(iss('x', 'CONTRIBUTOR'), m) == 'skeptical'

    lg = I.trust_of(['Alice', '@bob'])
    assert lg == frozenset({'alice', 'bob'})
    assert I.issue_trust(iss('alice', 'NONE'), lg) == 'trust'
    assert I.issue_trust(iss('BOB', 'NONE'), lg) == 'trust'
    assert I.issue_trust(iss('eve', 'MEMBER'), lg) == 'skeptical'

    # gh is asked for authorAssociation
    asked = []

    def gh(*a):
        asked.append(a)
        return subprocess.CompletedProcess(a, 0, json.dumps([iss('x', 'MEMBER')]), '')
    got = I.open_issues(gh, [])
    assert 'authorAssociation' in asked[0][-1] and got[0]['authorAssociation'] == 'MEMBER'

    # the answer follows each filing's own trust
    calls = []

    def gh2(*a):
        calls.append(a[:2])
        return subprocess.CompletedProcess(a, 0, '', '')
    book = {'F1': {'number': 1, 'trust': 'trust'}, 'F2': {'number': 2, 'trust': 'skeptical'}}
    lines = ['- [x] **F1** a', '- [x] **F2** b']
    for tid, n, trust, sha, line in I.to_answer(book, lines, lambda t: 'abc'):
        I.answer(gh2, n, tid, trust, sha, line)
    assert calls == [('issue', 'close'), ('issue', 'comment')], calls
    print('ok')


if __name__ == '__main__':
    main()
