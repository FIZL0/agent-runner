/* F442: Wait for…, in a Plan queue task's row menu: the Queue's rows become ticks for what the task waits for, and the bar
   under the view has Done and Cancel. S.planWait: the task being set ('': none), S.waitPicks: the ids ticked.
   WT.did: {id: {ids,at}}, what Done sent, drawn at once and until the snapshot has it; a refused one is taken back */
const WT={did:{}};
S.planWait='';S.waitPicks=[];
/* the rows with what Done sent (S.ob: so a Retry and a reload have it too) */
function waitRows(rows){
  const now=Date.now();
  for(const x of S.ob)if(x.waitset){if(x.state==='failed')delete WT.did[x.waitset];else WT.did[x.waitset]={ids:x.args.ids,at:now}}
  for(const id of Object.keys(WT.did))if(now-WT.did[id].at>=PM_MS)delete WT.did[id];
  return rows.map(q=>q.id&&WT.did[q.id]?waitDrawn(q,WT.did[q.id].ids):q);
}
const waitSame=(a,b)=>a.length===b.length&&a.every(t=>b.includes(t));
/* as ui_model_queue.after_name() */
function waitName(q){
  const s=String(q.title||''), t=s.split(': ')[0].trim()||s;
  return (q.id+' '+(t.length>40?t.slice(0,41).replace(/\s+\S*$/,'')+'…':t)).trim();
}
function waitDrawn(q,ids){
  if(waitSame(ids,waitNow(q)))return q;
  const all=waitKnown(), words=ids.map(t=>waitName(all.find(x=>x.id===t)||{id:t})).join(', ');
  if(q.release){const r=q.release;  // B870: a release says it on its own line
    return {...q,after:ids,release:{...r,waits:ids.map(t=>({id:t,title:(all.find(x=>x.id===t)||{}).title||t})),everything:false,note:'',
      ...(ids.length?{state:'waits'}:{state:'next',words:'next'})}}}
  const free=['ready','after','tool'].includes(q.state);  // the other states come first, as in ui_model_queue.queue_state()
  return {...q,after:ids,after_title:words,...(free?{state:ids.length?'after':'ready'}:{})};
}
/* every open task the snapshot has */
const waitKnown=()=>(S.snap.queue||[]).concat(S.snap.shelved||[]);
/* what row q waits for now, of the tasks still open */
const waitNow=q=>{const open=waitKnown().map(x=>x.id), r=q.release;return (r&&!(q.after||[]).length?(r.waits||[]).map(w=>w.id):q.after||[]).filter(t=>open.includes(t))};  // B870: a release's waits
const waitParts=(q,t)=>gripChild(q.id,t)||((q.split||{}).open||[]).some(p=>p.id===t);
/* what row q, at place i of `rows`, cannot be done before, as plan_wait._edges() */
function waitEdges(q,i,rows){
  const r=q.release||{};
  return (q.after||[]).concat((r.waits||[]).map(w=>w.id),r.everything?rows.slice(0,i).map(x=>x.id):[],rows.filter(x=>waitParts(q,x.id)).map(x=>x.id));
}
/* {id: why the task being set cannot wait for it}; plan_wait.why_not() is the one that refuses */
function waitNot(){
  const id=S.planWait, rows=waitRows(waitKnown()), me=rows.find(q=>q.id===id), no={};if(!me)return no;
  const back=[id], seen=new Set(back);
  while(back.length){const t=back.pop();
    rows.forEach((q,i)=>{if(!seen.has(q.id)&&waitEdges(q,i,rows).includes(t)){seen.add(q.id);back.push(q.id);no[q.id]=`Waits for ${id} itself`}})}
  for(const q of rows)if(waitParts(me,q.id))no[q.id]=`A part of ${id}`;else if(waitParts(q,id))no[q.id]=`${id} is a part of it`;
  no[id]='Being set';
  return no;
}
/* a task's row; `words` says why it is dimmed, in the place of its state */
function waitCard(q,no){
  if(q.removed)return removedCard(q);
  if(q.placeholder)return card(nextReleaseRow(q),'relph waitoff','data-k="rel:next"');
  const id=q.id, on=S.waitPicks.includes(id), me=id===S.planWait, off=!!no[id]&&!on;
  const words=me?'What it waits for is being set':off?no[id]:q.release?relWords(q.release):planWords(q,S.snap.sessions);
  const body=`${taskChip(id)}<span class="grow"><b class="ell">${esc((q.release||{}).title||q.title||id)}</b><span class="small" data-k="state:${esc(id)}" data-v="${esc(q.state||'')}">${esc(words)}</span></span>`;
  return card(me?`<div class="fold waitme" tabindex="-1" aria-current="true" data-waitme="${esc(id)}">${body}</div>`
    :`<button class="fold" role="checkbox" aria-checked="${on}"${off?' aria-disabled="true"':''} data-waitpick="${esc(id)}">${body}<span class="waittick" aria-hidden="true">${on?I.check:''}</span></button>`,
    me?'waitset':off?'waitoff':'',`data-k="task:${esc(id)}"`);
}
/* the Plan view meanwhile: the same places, every row a tick; a search finds the rows to tick */
function waitHTML(qs){
  const no=waitNot(), pk=queueGroups(S.snap.queue)[1].concat(S.snap.shelved||[]), sec=(name,xs)=>xs.length?`<div class="sec">${name}<span class="ln"></span></div>${xs.map(q=>waitCard(q,no)).join('')}`:'';
  if(planWant()){
    const g=PQ.got, ids=g?[...g.open,...g.parked].map(h=>h.id):[], hit=xs=>xs.filter(q=>q.id&&!q.removed&&ids.includes(q.id)), open=hit(qs), parked=hit(pk);
    const none=PQ.err?card(`<div class="small v-bad">${esc(PQ.err)}</div><div class="btns"><button class="btn" data-planqload>Try again</button></div>`):emptyCard(g&&g.q===planWant()?'No open task matches.':'Loading…');
    return `${planField()}<div class="col">${sec('Open',open)}${sec('Parked',parked)}${open.length||parked.length?'':none}</div>`;
  }
  return `${planField()}<div class="col">${S.waitPad?`<div class="waitpad" style="height:${S.waitPad}px"></div>`:''}${newReleaseCard()}${sec('Queue',qs)}${sec('Parked',pk)}</div>`;
}
/* F476: the Work page's sections above the Queue go in the pick mode and come back after: the task's row stays where it stood */
function workKeepRow(id,draw){
  const at=()=>{const r=id&&document.querySelector(`[data-k="task:${id}"]`), b=$('body');if(!r||!b)return null;let y=0;for(let x=r;x&&x!==b&&b.contains(x);x=x.offsetParent)y+=x.offsetTop;return y-b.scrollTop+b.getBoundingClientRect().top};  // where it stands once its glide ends
  const was=at();S.waitPad=0;draw();const b=$('body');let now=at();
  if(was==null||now==null||!b||now===was)return;
  b.scrollTop+=now-was;now=at();
  if(S.planWait&&now<was){S.waitPad=was-now;draw()}  // what scrolling cannot make up, room above the list does
  requestAnimationFrame(()=>{const n=at();if(n==null||Math.abs(n-was)<1)return;  // the bar over the list came after
    const d=n-was, p=S.planWait?Math.max(0,(S.waitPad||0)-d):0, left=d-((S.waitPad||0)-p);
    if(p!==(S.waitPad||0)){S.waitPad=p;draw()}
    if(left)b.scrollTop+=left});
}
function waitStart(id){
  const q=waitRows(S.snap.queue||[]).find(x=>x.id===id);if(!q||!waitMay(q))return;
  S.planMenu='';S.planWait=id;S.waitPicks=waitNow(q);
  workKeepRow(id,()=>render(true));menuFocus(`[data-waitme="${id}"]`);
}
function waitPick(id){
  if(!S.planWait||!waitKnown().some(q=>q.id===id))return;
  if(S.waitPicks.includes(id))S.waitPicks=S.waitPicks.filter(t=>t!==id);
  else if(!waitNot()[id])S.waitPicks=S.waitPicks.concat([id]);
  else return;
  render(true);
}
function waitEnd(){
  const id=S.planWait;S.planWait='';S.waitPicks=[];
  workKeepRow(id,()=>render(true));if(id)menuFocus(`[data-planmenu="${id}"]`);
}
function waitDone(){
  const id=S.planWait, q=waitRows(S.snap.queue||[]).find(x=>x.id===id);if(!q)return;
  const open=waitKnown().map(x=>x.id), ids=S.waitPicks.filter(t=>open.includes(t));  // one that landed meanwhile is waited for no more
  const all=!!(q.release||{}).everything||!ids.length&&/^all:/.test(q.after_title||'');  // B870: a release's all becomes the list ticked  // after: all, with nothing above it to tick: cleared too
  if(all||!waitSame(ids,waitNow(q))){
    S.planWait='';S.waitPicks=[];  // outbox() draws
    for(const x of S.ob.filter(x=>x.waitset===id&&x.state==='failed'))obChange(b=>obDrop(b,x.cid));  // a refused one this replaces
    outbox('set_waits',{tid:id,ids},{waitset:id,say:ids.length?`${id} waits for ${ids.join(', ')}`:`${id} waits for nothing`});
  }
  S.planWait=id;waitEnd();
}
/* the bar, a row under the view; a task that started, landed or left the plan meanwhile is set no more */
function waitBarDraw(){
  const id=S.planWait;
  if(id&&S.snap.queue&&!S.snap.queue.some(q=>q.id===id&&waitMay(q))){
    S.planWait='';S.waitPicks=[];toast(`${id} has started or left the queue: what it waits for is as it was`,true)}
  const el=$('waitbar'), was=el.hidden, h=S.planWait&&!HOME_PAGE&&!S.thread&&S.view==='plan'?`<div class="row"><span class="grow" role="status">What should ${esc(S.planWait)} wait for?</span><div class="btns"><button class="btn" data-waitcancel>Cancel</button><button class="btn acc" data-waitdone>Done</button></div></div>`:'';
  el.hidden=!h;
  if(setHTML(el,h)&&h&&was&&S.live)moAnim(el,[{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'none'}],{ease:'--ease',dur:'--dur'});
}
/* over a redraw: call before, then call what it returns: the row in use keeps the focus */
function waitKeep(el){
  const a=document.activeElement, d=a&&a!==el&&el.contains(a)&&a.dataset||{}, sel=d.waitpick?`[data-waitpick="${d.waitpick}"]`:d.waitme?`[data-waitme="${d.waitme}"]`:'';
  return()=>{if(sel)menuFocus(sel)};
}
document.addEventListener('click',e=>{
  const q=s=>e.target.closest&&e.target.closest(s);let x;
  if(x=q('[data-waitset]'))waitStart(x.dataset.waitset);
  else if(x=q('[data-waitpick]'))waitPick(x.dataset.waitpick);
  else if(q('[data-waitcancel]'))waitEnd();
  else if(q('[data-waitdone]'))waitDone();
});
window.addEventListener('keydown',e=>{
  if(e.key!=='Escape'||!S.planWait||S.view!=='plan'||S.thread||S.sheet||S.drawer||S.obOpen||e.target.value)return;  // what is over it first; a search's words
  e.preventDefault();e.stopImmediatePropagation();waitEnd();
},true);
I.wait=ic('<path d="M6 4h12M6 20h12M7 4c0 4 3 6 5 8 2-2 5-4 5-8M7 20c0-4 3-6 5-8 2 2 5 4 5 8"/>');
