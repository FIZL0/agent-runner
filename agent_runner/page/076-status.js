/* F426e: Status: the run (its controls), the agents that work, what merges, and usage. A row of the lists `working` and
   `merging` opens in place (S.taskOpen[list]: the task's id, or an idle slot's name), one per list, to what it says and its
   options, Chat last. S.readTask: the open row whose task text shows ('working:F1') */
function slotRow(s){
  const list='working', key=s.task||s.name, open=taskIsOpen(list,key), k=`slot:${s.name}:${s.task||''}`;
  const head=words=>`<button class="fold" data-task="${esc(key)}" data-list="${list}" aria-expanded="${open}"><span class="who">${esc(s.name)}</span>${words}<span class="chev">${I.chev}</span></button>`;
  if(!s.task)return `<div class="srow" data-k="${esc(k)}">${head('<span class="grow small">Idle</span>')}${open?foldIn(k,idleBody(s)):''}</div>`;
  const w=lastWords(s.name), tc=taskControlsOn(s)?controlsOf('task'):[], id=s.task;
  const body=()=>`${w?`<div class="quote">${esc(w)}</div>`:'<div class="small">It has said nothing yet.</div>'}<div class="btns"><button class="btn" data-thread="${esc(s.name)}">Open session</button>${readBtn(list,id)}${tc.map(c=>`<button class="btn${ctlBusy(c.key,id)?' busy':''}" data-ctl="${esc(c.key)}" data-tid="${esc(id)}">${esc(c.label)}</button>`).join('')}${chatBtn({id})}</div>${tc.filter(c=>S.sure===c.key+':'+id).map(c=>ctlSure(c,id)).join('')}${readText(list,id)}`;
  return `<div class="srow" data-k="${esc(k)}">${head(`${taskChip(id)}<span class="grow"><b class="ell">${esc(s.title||id)}</b><span class="status" data-k="st:${esc(s.name)}" data-v="${esc(s.state)}"><span class="livedot"></span>${slotWord(s)}</span></span>`)}${open?foldIn(k,body()):''}</div>`;
}
/* B852: what a working slot does: its task's gate runs (Testing), waits its turn (Waiting to test), else Working */
function slotWord(s){
  const min=s.minutes!=null?` · ${s.minutes} min`:'';
  return s.gate==='waiting'?'Waiting to test':s.gate==='testing'?'Testing'+min:'Working'+min;
}
/* an idle slot: why, and Remove a slot (the run takes the last one) */
function idleBody(s){
  const c=controlOf('slot_remove'), n=+S.snap.slots||0, last='s'+n;
  return `<div class="small">${esc(idleWhy(S.snap,mergeRows(S.snap).map(m=>m.id)))}</div>${c&&n>1?`${s.name!==last&&sessionOf(last)&&sessionOf(last).task?`<div class="small">Removing one takes ${esc(last)}, which finishes its task first.</div>`:''}<div class="btns"><button class="btn${ctlBusy('slot_remove')?' busy':''}" data-ctl="slot_remove">Remove a slot</button></div>`:''}`;
}
function mergeRow(m){
  const list='merging', open=taskIsOpen(list,m.id), k='merge:'+m.id;
  const go=m.slot?`<button class="btn" data-thread="${esc(m.slot)}">Open session</button>`:m.link?`<a class="btn" href="${esc(m.link)}" target="_blank" rel="noopener">Open session ${I.ext}</a>`:'';
  return `<div class="srow" data-k="${esc(k)}"><button class="fold" data-task="${esc(m.id)}" data-list="${list}" aria-expanded="${open}">${taskChip(m.id)}<span class="grow"><b class="ell">${esc(m.title||m.id)}</b><span class="status"><span class="livedot"></span>Merging</span></span><span class="chev">${I.chev}</span></button>${open?foldIn(k,`<div class="quote" data-k="${esc(k)}:step" data-v="${esc(m.step||'')}">${esc(m.step||'Not merged yet')}</div><div class="btns">${go}${readBtn(list,m.id)}${chatBtn(m)}</div>${readText(list,m.id)}`):''}</div>`;
}
/* F420: PR mode's open pull requests: each row a link to GitHub */
const prRow=r=>`<a class="srow prlink" data-k="pr:${r.number}" href="${esc(r.url)}" target="_blank" rel="noopener"><span class="row">${taskChip(r.ids[0])}<span class="grow"><b class="ell">${esc(r.title)}</b><span class="status" data-k="prs:${r.number}" data-v="${esc(r.state)}">#${r.number} · ${esc(r.state)}</span></span>${I.ext}</span></a>`;
/* Read task: the task's text (openTask() has asked for it), under the row's options */
const readBtn=(list,id)=>`<button class="btn" data-readtask="${esc(list+':'+id)}" aria-expanded="${S.readTask===list+':'+id}">Read task</button>`;
function readText(list,id){
  const t=S.tasks[id], k='read:'+list+':'+id;
  return S.readTask!==list+':'+id?'':foldIn(k,t&&t.text?`<pre class="tasktext" data-k="text:${esc(k)}">${esc(t.text)}</pre>`:t&&t.err?(t.old?oldRunHTML(t.err):`<div class="small v-bad">${esc(t.err)}</div>`):'<div class="small">Loading…</div>');
}
function statusHTML(){
  const use=S.snap.usage||[], ms=mergeRows(S.snap), ws=slots().filter(s=>s.state!=='merging'), sec=(name,h)=>`<div class="sec">${name}<span class="ln"></span></div>${h}`;
  return `<div class="col">${ttydLine()}
    ${sec('Run',controlsCard())}
    ${sec('Working',ws.length?card(ws.map(slotRow).join(''),'','data-k="working"'):emptyCard('No agent is working.'))}
    ${sec('Merging',ms.length?card(ms.map(mergeRow).join(''),'','data-k="merging"'):emptyCard('Nothing is merging.'))}
    ${(S.snap.prs||[]).length?sec('Pull requests',card(S.snap.prs.map(prRow).join(''),'','data-k="prs"')):''}
    ${sec('Usage',use.length?card(use.map(u=>meterHTML({name:u.name,pct:u.pct,said:u.pct+'%'})).join(''),'','data-k="usage"'):emptyCard('No usage read yet.'))}</div>`;
}
document.addEventListener('click',e=>{
  const x=e.target.closest('[data-readtask]');if(!x)return;
  S.readTask=S.readTask===x.dataset.readtask?'':x.dataset.readtask;render(true);
});
