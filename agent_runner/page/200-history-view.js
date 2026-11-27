/* F426c: the History view: what has landed, the past releases and the run log, with one search over them. Functions only:
   the first draw (187-snap.js) comes before this file's own lines run, so its state is in S.hist.
   S.hist: key: the words and the plan the server was asked for, at: the ask's number, got: its last answer */
function histState(){return S.hist=S.hist||{key:'',at:0,wait:0,got:null,err:'',old:false}}
function histWant(){return String(S.f.histq||'').trim()}
/* a past release has a row of its own; of a task that landed twice, the newest landing */
function histLanded(snap){
  const past=new Set((snap.past_releases||[]).map(r=>r.id)), seen=new Set();
  return (snap.lately||[]).filter(l=>l.id&&(l.kind==='landed'||l.kind==='part')&&!past.has(l.id)&&!seen.has(l.id)&&seen.add(l.id));
}
function histMatch(words,...texts){const t=texts.join(' ').toLowerCase();return words.every(w=>t.includes(w))}
/* asked again when the words, or what has landed, change; an answer to an older ask is dropped */
function histAsk(){
  const h=histState(), q=histWant(), key=q&&JSON.stringify([q,((S.snap.lately||[])[0]||{}).at]);
  if(key===h.key)return;
  clearTimeout(h.wait);h.key=key;h.at++;h.err='';
  if(q)h.wait=setTimeout(histLoad,200);else h.got=null;
}
async function histLoad(){
  const h=histState(), q=histWant(), at=++h.at;let j;
  try{j=await (await fetch(tq('plan-search?q='+encodeURIComponent(q)))).json()}catch(e){j={ok:false,out:'Could not reach the run page.'}}
  if(at!==h.at)return;
  if(j.ok){h.got=j;h.err=''}else{h.err=plainOut(j,'History could not be searched.');h.old=oldRun(j)}
  render();
}
function histField(){return `<div class="planq"><div class="row"><span class="setq grow"><input class="fld" type="search" data-f="histq" placeholder="Find in history" aria-label="Find in history"><button type="button" class="x" data-histqclear aria-label="Clear search"${S.f.histq?'':' hidden'}>${I.x}</button></span></div></div>`}
function histWhen(at){
  const d=new Date(at);if(!at||isNaN(d))return '';
  const day=d.toDateString()===new Date().toDateString()?'':' on '+d.toLocaleDateString([],{year:'numeric',month:'short',day:'numeric'});
  return `${d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}${day}`;
}
/* a landed task's or past release's row: it opens to when it landed, its text and its options, Chat last */
function histRow(l,list){
  const open=taskIsOpen(list,l.id), t=S.tasks[l.id], when=histWhen(l.at), rel=list==='pastrel', part=l.kind==='part';
  const text=t&&t.text?taskBodyHTML(t,list+':'+l.id,!rel):t&&t.err?(t.old?oldRunHTML(t.err):`<div class="small v-bad">${esc(t.err)}</div>`):'<div class="small">Loading…</div>';
  const b=(act,word)=>`<button class="btn${act==='changed'?' pri':''}" data-hist="${act}" data-id="${esc(l.id)}">${word}</button>`;
  const small=[part?'part landed':'',l.at?agoWords(l.at):''].filter(Boolean).join(' · ');
  return `<div class="srow" data-k="${esc(list+':'+l.id)}"><button class="fold" data-task="${esc(l.id)}" data-list="${list}" aria-expanded="${open}">${taskChip(l.id)}<span class="grow"><b class="ell">${esc(l.title||l.id)}</b><span class="small">${esc(small)}</span></span><span class="chev">${I.chev}</span></button>${open?foldIn(list+':'+l.id,`${when?`<div class="small">${rel?'Released':part?'Part landed':'Landed'} at ${esc(when)}.</div>`:''}${text}<div class="btns">${b('changed','What changed')}${b('report','Report a problem')}${b('chat','Chat')}</div>`):''}</div>`;
}
function histSec(name,rows,empty,k){return rows.length||empty?`<div class="sec">${name}<span class="ln"></span></div>${rows.length?card(rows.join(''),'',`data-k="${k}"`):emptyCard(empty)}`:''}
function histLog(lines){return lines.map(l=>{const k=logKind(l);return `<div class="ev" data-k="log:${esc(l)}"><span class="ic ${k}">${I[LOGLINE_ICON[k]]}</span><div class="txt">${esc(l)}</div></div>`}).join('')}
function historyHTML(){
  histAsk();
  const q=histWant(), land=histLanded(S.snap), past=S.snap.past_releases||[], log=(S.snap.log||[]).slice().reverse();
  const rows=(xs,list)=>xs.map(x=>histRow(x,list));
  if(q)return `${histField()}<div class="col">${histFound(q,land,past,log)}</div>`;
  return `${histField()}<div class="col">${histSec('Landed',rows(land,'landed'),'Nothing has landed yet.','landed')}
    ${releasesOn(S.snap)?histSec('Releases',rows(past,'pastrel'),'Nothing has been released yet.','pastrel'):''}
    <div class="sec">Run log<span class="ln"></span></div><div class="chips" style="justify-content:flex-start"><button class="chip" data-quick="since">${I.clock}Since my last look</button><button class="chip" data-quick="yesterday">${I.clock}Since yesterday</button></div>
    ${log.length?histLog(log):emptyCard('Nothing in the run log yet.')}</div>`;
}
/* the page's own rows at once, and the server's for what landed before them */
function histFound(q,land,past,log){
  const h=histState(), words=q.toLowerCase().split(/\s+/), same=h.got&&h.got.q===q, done=same?h.got.done.filter(x=>x.state==='done'):[], hit=new Set(done.map(x=>x.id));
  const match=l=>hit.has(l.id)||histMatch(words,l.id,l.title||''), known=new Set([...land,...past].map(l=>l.id));
  const old=done.filter(x=>!known.has(x.id)), isRel=x=>x.release&&releasesOn(S.snap);
  const ls=[...land.filter(match),...old.filter(x=>x.at&&!isRel(x))], rs=[...past.filter(match),...old.filter(isRel)], ds=old.filter(x=>!x.at), gs=log.filter(l=>histMatch(words,l));
  const err=h.err?card(`${h.old?oldRunHTML(h.err):`<div class="small v-bad">${esc(h.err)}</div>`}<div class="btns"><button class="btn" data-histload>Try again</button></div>`):'';
  const more=same&&h.got.more||0;
  return err+histSec('Landed',ls.map(x=>histRow(x,'landed')),'','landed')+histSec('Done',ds.map(x=>histRow(x,'donelist')),'','donelist')+(more?`<div class="small">${more} more done ${more===1?'task':'tasks'}. Add a word to find fewer.</div>`:'')
    +histSec('Releases',rs.map(x=>histRow(x,'pastrel')),'','pastrel')+(gs.length?`<div class="sec">Run log<span class="ln"></span></div>${histLog(gs)}`:'')
    +(ls.length||ds.length||rs.length||gs.length||err?'':emptyCard(same?'Nothing matches.':'Loading…'));
}
/* the field in use stays the same element, as in Plan */
function histDraw(el,h){
  if(el._h!==h&&el._gone)for(const g of el._gone)g.remove();
  return fieldHTML(el,h,'histq');
}
function histOf(id){
  const g=histState().got;
  return [...(S.snap.lately||[]),...(S.snap.past_releases||[]),...(g?g.done:[])].find(x=>x.id===id)||null;
}
/* What changed asks a new chat at once; Report a problem and Chat open a new chat's view, which starts with your words */
function histAct(act,id){
  const l=histOf(id);if(!l)return;
  const title=l.title||id;
  if(act==='changed'){S.ctx=null;const ask=histChangedAsk(id,title,histDid(l));return newChat('new_control',{ask},`What changed in ${id}`,ask)}
  S.ctx={kind:act==='report'?'report':'plan',id,title,...(act==='report'?{did:histDid(l)}:{}),label:act==='report'?`Problem with ${id} ${title}`:`${id} ${title}`};
  open(ctxKey(S.ctx));const ta=document.querySelector('[data-in]');if(ta)kbFocus(ta);  // in the tap itself, as about() does
}
function histDid(l){return l.kind==='part'?'has landed in part':l.at?'has landed':'is done'}
function histChangedAsk(id,title,did){return `What changed in ${id} (${title}), which ${did}? Read its commits and tell me in a few plain lines what is different now. Change nothing.`}
document.addEventListener('click',e=>{
  const q=s=>e.target.closest(s);let x;
  if(x=q('[data-hist]')){histAct(x.dataset.hist,x.dataset.id);return}
  if(q('[data-histqclear]')){setqClear('histq');return}
  if(q('[data-histload]')){histState().err='';histLoad();render(true)}
});
document.addEventListener('input',e=>{if(e.target.matches('[data-f="histq"]'))render(true)});
