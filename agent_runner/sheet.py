"""F18: pick sheets, for a DECIDE that offers a person options.

An agent that blocks with `DECIDE:` on a choice writes the choice as questions with answers, not as a numbered
list, to `<notes>/sheets/<ID>.json`:

    {"title": "R7 config cleanup",
     "summary": "12 config cleanups ready, 10 optional",
     "intro": "R7 audited the config keys. The recommended answers are already selected.",
     "groups": [
       {"heading": "Remove keys",
        "questions": [
          {"id": "backend", "q": "How should the runner know which backend to use?",
           "answers": ["Work it out from `agent`", "Keep `run.backend`"],
           "recommended": 0, "keep": 1,
           "why": "Only Clay and opentennis set it, both to the default."}]}]}

`recommended` is the answer picked unless the person changes it; `keep` (optional) is the answer that changes
nothing, so the sheet can count "N changes picked". Text is plain; `backticks` show as code. `agent-runner
sheet <ID> --html FILE` renders the page (one question per card, its answers as buttons with the recommended
one preselected and labelled, a collapsible Why, and a sticky bar: N changes picked, Recommended, Send), which
the agent publishes with the Artifact tool and names in its DECIDE line. Needs you and the feed then show one
line, '<summary>. Pick on the sheet or reply go', with the sheet's link.

Send shows the picks as one reply line, `<ID> picks: backend=a batch=b` (letters in answer order), and copies
it; pasted in the chat with the run, the session answers the item with `agent-runner sheet <ID> --picks
"<that line>"`, and 'go' answers it with the recommended set (`--go`). Either way the task reopens (`plan
confirm`) with each question's answer spelled out in its note.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

__all__ = ['load', 'problems', 'questions', 'render', 'parse_picks', 'picks_note', 'changes', 'GO']

GO = ('go', 'recommended', 'ok', 'yes')  # a reply that takes the recommended set


def load(path: Path) -> dict:
    """The sheet at `path`; ValueError when it is not JSON or not a sheet (`problems`)."""
    try:
        spec = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f'{path}: {e}') from None
    if bad := problems(spec):
        raise ValueError(f'{path}: ' + '; '.join(bad))
    return spec


def questions(spec: dict) -> list[dict]:
    """Every question of the sheet, in page order."""
    return [q for g in spec.get('groups') or [] for q in g.get('questions') or []]


def problems(spec) -> list[str]:
    """What keeps `spec` from being a sheet: [] when it is one."""
    if not isinstance(spec, dict):
        return ['not a JSON object']
    out = []
    if not str(spec.get('summary') or '').strip():
        out.append('no "summary" (the one line Needs you shows)')
    groups = spec.get('groups')
    if not isinstance(groups, list) or not groups:
        return out + ['no "groups"']
    seen = set()
    for g in groups:
        if not isinstance(g, dict) or not isinstance(g.get('questions'), list) or not g['questions']:
            out.append('a group with no "questions"')
            continue
        for q in g['questions']:
            qid = str(q.get('id') or '') if isinstance(q, dict) else ''
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', qid):
                out.append(f'question {qid or "?"}: "id" must be letters, digits, _ . -')
                continue
            if qid in seen:
                out.append(f'question {qid}: id used twice')
            seen.add(qid)
            ans = q.get('answers')
            if not str(q.get('q') or '').strip():
                out.append(f'question {qid}: no "q"')
            if not isinstance(ans, list) or not 2 <= len(ans) <= 26 or not all(str(a).strip() for a in ans):
                out.append(f'question {qid}: "answers" must list 2 or more answers')
                continue
            for k in ('recommended', 'keep'):
                v = q.get(k, 0 if k == 'recommended' else None)
                if v is not None and not (isinstance(v, int) and 0 <= v < len(ans)):
                    out.append(f'question {qid}: "{k}" must be an answer\'s index (0 is the first)')
    return out


def changes(spec: dict, picks: dict[str, int]) -> int:
    """How many picks change something: each one that is not its question's `keep` answer."""
    return sum(1 for q in questions(spec) if picks.get(q['id'], rec(q)) != q.get('keep'))


def rec(q: dict) -> int:
    return int(q.get('recommended', 0) or 0)


def parse_picks(spec: dict, text: str) -> dict[str, int]:
    """{question id: answer index} from Send's reply line (`R7 picks: backend=a batch=b`, the `R7 picks:`
    optional) or a bare 'go' / 'recommended' (the recommended set). A question it does not name keeps its
    recommended answer. ValueError on an id or a letter the sheet does not have."""
    qs = {q['id']: q for q in questions(spec)}
    picks = {k: rec(q) for k, q in qs.items()}
    body = re.sub(r'^\s*\S+\s+picks:\s*', '', text.strip(), flags=re.I)
    if body.strip().lower().strip('.!') in GO + ('',):
        return picks
    for tok in re.split(r'[\s,;]+', body.strip()):
        if not tok:
            continue
        m = re.fullmatch(r'([A-Za-z0-9_.-]+)=([A-Za-z])', tok)
        if not m or m[1] not in qs:
            raise ValueError(f'{tok!r}: not a pick on this sheet (questions: {", ".join(qs)})')
        i = ord(m[2].lower()) - ord('a')
        if i >= len(qs[m[1]]['answers']):
            raise ValueError(f'{tok!r}: {m[1]} has answers a-{chr(ord("a") + len(qs[m[1]]["answers"]) - 1)}')
        picks[m[1]] = i
    return picks


def _plain(s) -> str:
    return str(s).replace('`', '').strip()


def picks_note(spec: dict, picks: dict[str, int]) -> str:
    """The picks spelled out for the task's note: each question, then its answer, 'recommended' where it is."""
    out = []
    for q in questions(spec):
        i = picks.get(q['id'], rec(q))
        out.append(f'{q["id"]} ({_plain(q["q"]).rstrip("?")}?): {_plain(q["answers"][i])}'
                   + (' (recommended)' if i == rec(q) else ''))
    return 'picks on the sheet: ' + '; '.join(out)


def _rich(s) -> str:
    """Plain text for the page: escaped, `code` shown as code."""
    return re.sub(r'`([^`]+)`', r'<code>\1</code>', html.escape(str(s)))


def render(spec: dict, tid: str) -> str:
    """The pick sheet's page (the Artifact tool's page contract: no html/head/body of its own)."""
    groups = []
    for g in spec['groups']:
        qs = []
        for q in g['questions']:
            qs.append({'id': q['id'], 'q': _rich(q['q']), 'a': [_rich(a) for a in q['answers']],
                       'r': rec(q), 'k': q.get('keep'), 'why': _rich(q.get('why') or '')})
        groups.append({'h': _rich(g.get('heading') or ''), 'qs': qs})
    data = json.dumps({'tid': tid, 'groups': groups}).replace('</', '<\\/')
    title = html.escape(str(spec.get('title') or f'{tid} pick sheet'))
    return (PAGE.replace('{{title}}', title)
            .replace('{{intro}}', _rich(spec.get('intro') or spec['summary']))
            .replace('{{tid}}', html.escape(tid))
            .replace('{{data}}', data))


PAGE = """<title>{{title}}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
:root{--bg:#f4f6f9;--fg:#1a1e26;--muted:#5f6876;--line:#dce1e8;--card:#fff;--accent:#2f5bd3;--accent-ink:#fff}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#11141a;--fg:#e6e9ef;--muted:#9aa3b2;
--line:#2a303a;--card:#191d25;--accent:#7ea2ff;--accent-ink:#0f1320;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#11141a;--fg:#e6e9ef;--muted:#9aa3b2;--line:#2a303a;--card:#191d25;
--accent:#7ea2ff;--accent-ink:#0f1320;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font-family:system-ui,-apple-system,sans-serif;font-size:15px;line-height:1.5}
.wrap{max-width:640px;margin:0 auto;padding-block:20px 140px;padding-left:max(16px,env(safe-area-inset-left,0px));
padding-right:max(16px,env(safe-area-inset-right,0px));display:grid;gap:22px}
h1{font-size:1.35rem;margin:0}
.lede{color:var(--muted);margin:4px 0 0}
section{display:grid;gap:10px}
h2{font-size:.75rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0;font-weight:600}
.q{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:grid;gap:8px;min-width:0}
.q p{margin:0;font-weight:500}
code{font-family:ui-monospace,monospace;font-size:.85em}
.seg{display:flex;flex-wrap:wrap;gap:6px}
.seg button{font:inherit;font-size:.88rem;border:1px solid var(--line);background:transparent;color:var(--fg);
border-radius:999px;padding:5px 12px;cursor:pointer;text-align:left}
.seg button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.seg button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.seg .r{font-size:.72rem;font-weight:600;margin-left:6px;opacity:.85}
details{font-size:.85rem;color:var(--muted)}
summary{cursor:pointer;width:max-content}
details div{margin-top:4px}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);
padding-block:10px calc(10px + env(safe-area-inset-bottom,0px));padding-left:max(16px,env(safe-area-inset-left,0px));
padding-right:max(16px,env(safe-area-inset-right,0px))}
.bar .in{max-width:640px;margin:0 auto;display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.btns{display:flex;gap:8px}
.bar button{font:inherit;font-weight:600;border-radius:8px;padding:7px 14px;cursor:pointer;border:1px solid var(--line);
background:transparent;color:var(--fg)}
.bar button.go{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
#sent{display:grid;gap:6px}
#out{white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,monospace;font-size:.85rem;background:var(--card);
border:1px solid var(--line);border-radius:10px;padding:10px;margin:0;user-select:all}
</style>
<div class="wrap">
<header><h1>{{title}}</h1><p class="lede">{{intro}} The recommended answers are already selected.</p></header>
<div id="qs"></div>
<div id="sent" hidden><p class="lede" id="said"></p><pre id="out"></pre></div>
</div>
<div class="bar"><div class="in">
<span><b id="n">0</b> changes picked</span>
<span class="btns"><button id="reset" type="button">Recommended</button><button id="send" class="go" type="button">Send</button></span>
</div></div>
<script>
const S={{data}};
const all=S.groups.flatMap(g=>g.qs), pick={};
const qs=document.getElementById('qs');
S.groups.forEach(g=>{
  const sec=document.createElement('section');
  if(g.h)sec.innerHTML='<h2>'+g.h+'</h2>';
  g.qs.forEach(q=>{
    pick[q.id]=q.r;
    const d=document.createElement('div');d.className='q';
    d.innerHTML='<p>'+q.q+'</p><div class="seg" role="group">'+q.a.map((a,i)=>'<button type="button" data-k="'+q.id+
      '" data-i="'+i+'">'+a+(i===q.r?'<span class="r">recommended</span>':'')+'</button>').join('')+'</div>'+
      (q.why?'<details><summary>Why</summary><div>'+q.why+'</div></details>':'');
    sec.appendChild(d);
  });
  qs.appendChild(sec);
});
function render(){
  document.querySelectorAll('.seg button').forEach(b=>b.setAttribute('aria-pressed',String(pick[b.dataset.k]==b.dataset.i)));
  document.getElementById('n').textContent=all.filter(q=>pick[q.id]!==q.k).length;
}
qs.addEventListener('click',e=>{const b=e.target.closest('button[data-k]');if(!b)return;pick[b.dataset.k]=+b.dataset.i;render()});
document.getElementById('reset').onclick=()=>{all.forEach(q=>pick[q.id]=q.r);render()};
document.getElementById('send').onclick=()=>{
  const changed=all.filter(q=>pick[q.id]!==q.r);
  const txt=changed.length?S.tid+' picks: '+all.map(q=>q.id+'='+String.fromCharCode(97+pick[q.id])).join(' '):'go';
  const out=document.getElementById('out'), said=document.getElementById('said');
  out.textContent=txt;document.getElementById('sent').hidden=false;
  const done=ok=>{said.textContent=(ok?'Copied. ':'Copy this line. ')+'Paste it in the chat with the run, and it answers {{tid}} with these picks.'};
  try{navigator.clipboard.writeText(txt).then(()=>done(true),()=>done(false))}catch(e){done(false)}
  out.scrollIntoView({behavior:'smooth',block:'center'});
};
render();
</script>
"""
