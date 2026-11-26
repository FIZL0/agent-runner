"""F437a: Minimize on the question card: one line with Show question, kept over a redraw and a reload.

    python3 tests/test_web_question_minimize.py
"""
from __future__ import annotations

from pathlib import Path

from _check import check, eq, report
from _web import in_tmp

import test_web_question_dismiss as D

# what stands above the box, with the minimized line
LOOK = """const look = () => dock.includes('data-qshow') ? 'min' : kind(), mini = (id = 'u1', d = 1) => tap({qmin: id}, d), show = (id = 'u1', d = 1) => tap({qshow: id}, d);
"""


def run(tmp: Path, steps: str, kept: dict | None = None) -> list | None:
    return D.run(tmp, LOOK + steps, kept)


def test_minimize(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); say(dock); mini('other'); say(look()); mini(); say(dock, sent.length, toasts.length, {...kept});
      await pass(600); render(); live({...ASK, need: 'F9'}); say(look(), sent.length, S.ob.length);
      show('other'); say(look()); show(); say(look(), {...kept});
      await pass(600); mini(); live({...ASK, id: 'u2'}); say(look());
      live(null); say(dock);""")
    if out is None:
        return
    check('data-qmin="u1" aria-label="Minimize question"' in out[0][0] and 'ismiss' not in out[0][0], 'the card has its −, in place of Dismiss', out[0][0])
    eq(out[1], ['card'], 'a tap meant for another question minimizes nothing')
    line = out[2][0]
    check('Which &lt;look>?' in line and 'class="grow ell"' in line and 'data-qshow="u1" aria-label="Show question"' in line, 'a tap makes it one line: the question, escaped, and the ^', line)
    eq([line.count('<button'), 'data-qpick' in line], [1, False], 'with no options')
    eq(out[2][1:], [0, 0, {'ar-qmin:t': '["c1 u1"]'}], 'kept in the browser; nothing is sent')
    eq(out[3], ['min', 0, 0], 'it stays so over a redraw, and once it is filed under Needs you')
    eq(out[4], ['min'], 'a tap meant for another question opens nothing')
    eq(out[5], ['card', {'ar-qmin:t': '[]'}], 'the ^ opens it again')
    eq(out[6], ['card'], 'a new question comes open')
    eq(out[7], [''], 'the line goes with its question')


def test_kept(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); say(look()); S.thread = FD.n = 'c2'; live(ASK); say(look());
      S.thread = FD.n = 'c1'; live(ASK); kept['ar-qmin:t'] = '[]'; tell('ar-qmin:t'); say(look());
      kept['ar-qmin:t'] = '["c1 u1"]'; tell('ar-qmin:t'); say(look());""", {'ar-qmin:t': '["c1 u1"]'})
    if out is None:
        return
    eq(out, [['min'], ['card'], ['card'], ['min']], 'kept over a reload, for its own chat; another tab is followed')
    eq(run(tmp, 'live(ASK); say(look());', {'ar-qmin:t': '{broken'}), [['card']], 'what does not read minimizes nothing')
    eq(run(tmp, "for (let i = 0; i < 120; i++) { live({...ASK, id: 'q' + i}); mini('q' + i); now += 600 } say(JSON.parse(kept['ar-qmin:t']).length);"), [[100]], 'the latest 100 are kept')
    eq(run(tmp, 'live(ASK); say(look());', {'ar-qmin:t': '["c1 u1"]', 'ar-qgone:t': '["c1 u1"]'}), [['']], 'one dismissed before stays gone')


def test_held(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); pick(0); say(look()); mini(); kept['ar-qmin:t'] = '["c1 u1"]'; tell('ar-qmin:t'); say(look(), dock.includes('qmin'));
      await pass(6000); say(sent.map(x => x.args.text));""")
    if out is None:
        return
    eq(out[:2], [['held'], ['held', False]], 'an answer that waits is whole, also when its question is minimized in another tab')
    eq(out[2], [['Full']], 'and goes')


def test_presses(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); mini(); show(); say(look()); now += 600; show(); pick(0); tap({qchat: 'u1'}); say(look(), QN.mark.size);
      now += 600; mini('u1', 0); say(look(), box.on); now += 600; show('u1', 0); say(look(), box.on); now += 600; pick(0); say(look());""")
    if out is None:
        return
    eq(out[0], ['min'], 'a double tap on − does not open it again')
    eq(out[1], ['card', 0], 'nor does one on ^ pick what came under the finger')
    focus = '#dock [data-qshow],#dock [data-qmin]'
    eq(out[2:4], [['min', focus], ['card', focus]], 'pressed with a key, the focus goes to the other button')
    eq(out[4], ['held'], 'shown again, an option is picked as before')


def test_motion() -> None:
    """B854c: hiding and coming back slide and fade, off under reduced motion."""
    page = Path(__file__).resolve().parent.parent / 'agent_runner' / 'page'
    js = (page / '095-question.js').read_text()
    check("transform:'translateY(12px)'" in js and "ease:'--ease',dur:'--dur'" in js, 'the card slides and fades on one token, about 180ms', js)
    check('const a=c&&moAnim(c,QUESTION_MOVE,o);if(!a)return set();' in js, 'it keeps its room until it has faded, so nothing jumps')
    check('if(!el.animate||calm())return null' in (page / '010-shared.js').read_text(), 'moAnim does nothing when calm')
    check('prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}' in (page / '150-shared.css').read_text(), 'no motion under reduced motion')


if __name__ == '__main__':
    test_motion()
    raise SystemExit(report([in_tmp(f) for f in (test_minimize, test_kept, test_held, test_presses)]))
