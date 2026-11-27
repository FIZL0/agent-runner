/* F476: the Work page (concept K25, option A): Status, Plan and History as one timeline, in the Plan view's place.
   The run bar and usage on top, then Now (what the slots work on, what merges, open pull requests), Up next (the Queue
   without the tasks Now shows), Landed (and past releases), and at the bottom Parked and the Run log, each folded.
   One search: Plan's (open, parked and done tasks). The rows are the ones each old page drew, so they open as before */
function workNowIds(){
  const ids=new Set(mergeRows(S.snap).map(m=>m.id));
  for(const s of slots())if(s.task)ids.add(s.task);
  return ids;
}
/* the Queue's rows a Now row already shows are left out of Up next */
const workUpNext=(qs,now)=>qs.filter(q=>q.release||q.placeholder||!now.has(q.id));
/* F487 (concept K26, option A): every section folds; these start open, Parked and Run log closed */
const WORK_OPEN={now:1,prs:1,upnext:1,landed:1,pastrel:1};
const workIsOpen=k=>{const o=(S.workOpen||{})[k];return o===undefined?!!WORK_OPEN[k]:!!o};
/* a folded section: its head is a fold, as a row's (S.workOpen[k]) */
function workFold(k,name,n,h){
  const open=workIsOpen(k);
  return `<div class="sec" id="work-${esc(k)}"><button class="fold secfold" data-workfold="${esc(k)}" aria-expanded="${open}">${esc(name)}${n?` · ${n}`:''}<span class="chev">${I.chev}</span></button><span class="ln"></span></div>${!open?'':WORK_OPEN[k]?h:foldIn('work:'+k,h)}`;  // the sections open by default draw their rows in place, not in a fold's box: going to the pick mode, a box would leave as a picture over it
}
function workHTML(qs,pk,sh,shOb){
  histAsk();
  const use=S.snap.usage||[], ms=mergeRows(S.snap), ws=slots().filter(s=>s.state!=='merging'&&s.task), now=workNowIds();
  const up=workUpNext(qs,now), land=histLanded(S.snap), past=S.snap.past_releases||[], log=(S.snap.log||[]).slice().reverse();
  const nowRows=ws.map(slotRow).join('')+ms.map(mergeRow).join('');
  const meters=use.length?card(use.map(u=>meterHTML({name:u.name,pct:u.pct,said:u.pct+'%'})).join(''),'','data-k="usage"'):'';
  const parked=pk.length||sh.length||shOb?pk.map(q=>parkedCard(q)).join('')+shOb+sh.map(q=>shelvedCard(q)).join(''):'';
  const prs=S.snap.prs||[], rel=releasesOn(S.snap)&&past.length;
  const secs=[['now','Now',0,nowRows?card(nowRows,'','data-k="working"'):emptyCard('No agent is working.')],
    prs.length&&['prs','Pull requests',prs.length,card(prs.map(prRow).join(''),'','data-k="prs"')],
    ['upnext','Up next',up.length,up.length?up.map(queueCard).join(''):emptyCard('The queue is empty.'),newReleaseCard(),obCards(x=>obActs(x,'queue')||(x.grip||x.waitset)&&x.state==='failed')],
    ['landed','Landed',land.length,land.length?card(land.map(x=>histRow(x,'landed')).join(''),'','data-k="landed"'):emptyCard('Nothing has landed yet.')],
    rel&&['pastrel','Releases',past.length,card(past.map(x=>histRow(x,'pastrel')).join(''),'','data-k="pastrel"')],
    parked&&['parked','Parked',pk.length+sh.length,parked],
    ['log','Run log',0,log.length?histLog(log):emptyCard('Nothing in the run log yet.')]].filter(Boolean);
  const jump=`<div class="workjump" role="navigation" aria-label="Sections">${secs.map(([k,name])=>`<button class="chip" data-workjump="${k}">${esc(name)}</button>`).join('')}</div>`;
  return `${ttydLine()}${controlsCard()}${meters}
    <div class="worksecs">${jump}${secs.map(([k,name,n,h,before,after])=>`${before||''}${workFold(k,name,n,h)}${after||''}`).join('')}</div>`;
}
document.addEventListener('click',e=>{
  const x=e.target.closest('[data-workfold]');if(!x)return;
  const k=x.dataset.workfold;S.workOpen=S.workOpen||{};S.workOpen[k]=!workIsOpen(k);render(true);
});
/* F487: a jump button opens its section and scrolls its head under the jump bar */
document.addEventListener('click',e=>{
  const x=e.target.closest('[data-workjump]');if(!x)return;
  const k=x.dataset.workjump;S.workOpen=S.workOpen||{};
  if(!workIsOpen(k)){S.workOpen[k]=true;render(true)}
  const el=document.getElementById('work-'+k), box=el&&el.closest('.body');if(!box)return;
  const bar=box.querySelector('.workjump'), q=box.querySelector('.planq');
  scrollGlide(box,b=>{const h=document.getElementById('work-'+k);return h?h.getBoundingClientRect().top-b.getBoundingClientRect().top+b.scrollTop-(q?q.offsetHeight:0)-(bar?bar.offsetHeight:0)-8:b.scrollTop});
});
