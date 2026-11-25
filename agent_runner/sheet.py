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
the agent names in its DECIDE line. F411: `sheet <ID> --publish` publishes it, with no Artifact tool in the slot
(`publish`: the one-shot of `run publish-page`; where claude.ai is not available, the run page's own copy). Needs you and the feed then show one
line, '<summary>. Pick on the sheet or reply go', with the sheet's link.

Send shows the picks as one reply line, `<ID> picks: backend=a batch=b` (letters in answer order; 'go' when
they are the recommended set), and (F54) writes it to the page's artifact db as the document `picks/<ID>`,
`{"id": "<ID>", "picks": "<that line>", "at": "<ISO time>"}`: the page is published with `CAPABILITIES`
(`{"db": {}}`). The control session reads that document with the ArtifactData tool (`get`, collection `picks`,
doc_id the ID, on the sheet's url) and answers the item with `agent-runner sheet <ID> --picks "<its picks>"`.
Where the page has no db (an older sheet, a write that fails) Send
copies the line instead, to paste in the chat with the run; 'go' answers it with the recommended set (`--go`).
Either way the task reopens (`plan confirm`) with each question's answer spelled out in its note.
"""
from __future__ import annotations

import html
import json
import re
import subprocess as sp
import sys
from pathlib import Path

__all__ = ['load', 'problems', 'questions', 'render', 'parse_picks', 'picks_note', 'changes', 'GO',
           'CAPABILITIES', 'DB_COLLECTION', 'publish', 'local_page', 'local_id']

GO = ('go', 'recommended')  # a reply that takes the recommended set
# F54: the sheet's page keeps the picks Send sent in its artifact db, document `picks/<ID>`. The owner (who
# picks) is expected to write with the default rules, so the declaration names none; where a write is refused
# (a viewer without write access) Send falls back to the line to paste. The runtime shape the page uses,
# `await window.claude.use('db')` then `db.doc('<collection>/<id>').set(data)`, is the one Claude Code's own
# artifact SDK documents for the same store (the artifact-capabilities skill was not available to check).
# R8 (2026-11-20, Claude Code 2.1.329, contract 0.2.96): no `wake` list. Claude Code's validator accepts
# {"db": {"wake": [paths]}}, but a probe page published with {"db": {"wake": ["picks"]}} came back stored as
# {"db": {}}: the artifact service drops it, so a Send can't wake the run that way. Declaring it also takes
# the publish off Claude Code's no-prompt list, and the client says a local watch wakes only for a comment
# sent to Claude. So the person still says "sent" (or the item shows again) before the control session
# reads picks/<ID>.
CAPABILITIES = {'db': {}}
DB_COLLECTION = 'picks'


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
            if not isinstance(ans, list) or not 2 <= len(ans) <= 3 or not all(str(a).strip() for a in ans):
                out.append(f'question {qid}: "answers" must list 2 or 3 answers')
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


def render(spec: dict, tid: str, pick: str = '', local: bool = False) -> str:
    """The pick sheet's page (the Artifact tool's page contract: no html/head/body of its own). F138: `pick`, the
    run page's /pick link for this sheet with no option (`web.pick_links`), makes Send also show a plain link
    that answers the run with the picks; '' (no https address) keeps today's flow. F411: `local`, the
    run page's own copy: its sandbox opens no new tab, so that link opens in place."""
    groups = []
    for g in spec['groups']:
        qs = []
        for q in g['questions']:
            qs.append({'id': q['id'], 'q': _rich(q['q']), 'a': [_rich(a) for a in q['answers']],
                       'r': rec(q), 'k': q.get('keep'), 'why': _rich(q.get('why') or '')})
        groups.append({'h': _rich(g.get('heading') or ''), 'qs': qs})
    data = json.dumps({'tid': tid, 'groups': groups, 'pick': pick if pick.startswith('https://') else ''}).replace('</', '<\\/')
    title = html.escape(str(spec.get('title') or f'{tid} pick sheet'))
    page = PAGE.replace(' target="_blank" rel="noreferrer"', ' rel="noreferrer"') if local else PAGE
    return (page.replace('{{title}}', title)
            .replace('{{intro}}', _rich(spec.get('intro') or spec['summary']))
            .replace('{{tid}}', html.escape(tid))
            .replace('{{data}}', data))


def local_id(tid: str) -> str:
    """F411: the name the run page keeps `tid`'s sheet under (/concept/<name>), apart from a page the task published."""
    return f'{tid}_sheet'


def local_page(tid: str) -> str:
    """Where the run page shows `tid`'s sheet when it has no claude.ai page."""
    return f'/concept/{local_id(tid)}'


def publish(spec: dict, tid: str, pick: str = '', one_shot=None) -> str:
    """F411: publish `tid`'s sheet to claude.ai with `CAPABILITIES`, as `run publish-page` does (`one_shot`, default
    `page_copy.page_copy_publish`), and return its URL. The URL is kept beside the sheet, so a second publish updates
    the same page; both go with the sheet (`asks.clear_ask`). With no claude.ai here (no agent program, or a feed model
    of another provider) the run page keeps a copy and its `local_page` is returned. '' when the one-shot ran and did
    not publish."""
    from agent_runner import page_copy as PC, state as S
    PC.C = S.C  # not one `state.share` sets
    page, urlf = S.C.notes('sheets', f'{tid}.html'), S.C.notes('sheets', f'{tid}.url')
    old = urlf.read_text(encoding='utf-8').strip() if urlf.is_file() else ''
    old = old if PC.ARTIFACT_URL.fullmatch(old) else ''
    copy = S.C.notes('concepts', f'{local_id(tid)}.html')
    if not PC.feed_on_harness():
        page.write_text(render(spec, tid, pick=pick), encoding='utf-8')
        try:
            got = (one_shot or PC.page_copy_publish)(page, old, icon='options', caps=CAPABILITIES)
        except FileNotFoundError as e:  # no agent on this machine: the run page's copy
            S.log(f'sheet {tid}: no claude.ai page: {e}')
        except (OSError, sp.SubprocessError) as e:
            S.log(f'sheet {tid}: {e}')
            return ''
        else:
            if got:
                urlf.write_text(got + '\n', encoding='utf-8')
                copy.unlink(missing_ok=True)
            return got
    copy.write_text(render(spec, tid, pick=pick, local=True), encoding='utf-8')
    return local_page(tid)


def cmd_publish(spec: dict, tid: str, pick: str, prog: str) -> int:
    """`agent-runner sheet ID --publish`."""
    url = publish(spec, tid, pick)
    if not url:
        print(f'{prog}: the one-shot could not publish the sheet to claude.ai (the run log says why). Run this again, or '
              f'block with the DECIDE line and no link: the person can still reply go.', file=sys.stderr)
        return 1
    print(f'no claude.ai page without Claude Code: the run page shows the sheet, with Open on its Needs you item ({url}); '
          'leave the link out of the DECIDE line' if url == local_page(tid) else f'published: {url}')
    return 0


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
.pick{justify-self:start;background:var(--accent);color:var(--accent-ink);border-radius:8px;padding:8px 14px;
font-weight:600;text-decoration:none}
#out{white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,monospace;font-size:.85rem;background:var(--card);
border:1px solid var(--line);border-radius:10px;padding:10px;margin:0;user-select:all}
</style>
<div class="wrap">
<header><h1>{{title}}</h1><p class="lede">{{intro}} The recommended answers are already selected.</p></header>
<div id="qs"></div>
<div id="sent" hidden><p class="lede" id="said"></p><pre id="out"></pre>
<a id="pick" class="pick" hidden target="_blank" rel="noreferrer">Answer the run with these picks</a></div>
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
async function store(txt){
  // F54: the picks go to this page's artifact db, picks/<ID>, where the run's control session reads them
  try{
    const db=window.claude&&window.claude.use?await window.claude.use('db'):null;
    if(!db)return false;
    await db.doc('picks/'+S.tid).set({id:S.tid,picks:txt,at:new Date().toISOString()});
    return true;
  }catch(e){return false}
}
document.getElementById('send').onclick=async()=>{
  const changed=all.filter(q=>pick[q.id]!==q.r);
  const txt=changed.length?S.tid+' picks: '+all.map(q=>q.id+'='+String.fromCharCode(97+pick[q.id])).join(' '):'go';
  const out=document.getElementById('out'), said=document.getElementById('said'), send=document.getElementById('send');
  out.textContent=txt;document.getElementById('sent').hidden=false;
  if(S.pick){  // F138: a plain link to the run page answers the item with these picks, no AI session
    const a=document.getElementById('pick');a.href=S.pick+'&o='+encodeURIComponent(txt);a.hidden=false;
    said.textContent='Tap the button below: it answers {{tid}} with these picks now.';
    a.scrollIntoView({behavior:'smooth',block:'center'});
    store(txt);  // F54's db copy too, for the control session should the link not reach the run
    return;
  }
  send.disabled=true;said.textContent='Sending…';
  if(await store(txt)){
    send.disabled=false;send.textContent='Send again';
    said.textContent='Sent: saved on this page. Say "sent" in the chat with the run, and it reads them and answers {{tid}} with these picks.';
  }else{
    send.disabled=false;
    const done=ok=>{said.textContent=(ok?'Copied. ':'Copy this line. ')+'Paste it in the chat with the run, and it answers {{tid}} with these picks.'};
    try{navigator.clipboard.writeText(txt).then(()=>done(true),()=>done(false))}catch(e){done(false)}
  }
  out.scrollIntoView({behavior:'smooth',block:'center'});
};
render();
</script>
"""
