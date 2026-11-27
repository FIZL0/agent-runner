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
/* a folded section: its head is a fold, as a row's (S.workOpen[k]) */
function workFold(k,name,n,h){
  const open=!!(S.workOpen||{})[k];
  return `<div class="sec"><button class="fold secfold" data-workfold="${esc(k)}" aria-expanded="${open}">${esc(name)}${n?` · ${n}`:''}<span class="chev">${I.chev}</span></button><span class="ln"></span></div>${open?foldIn('work:'+k,h):''}`;
}
function workHTML(qs,pk,sh,shOb){
  histAsk();
  const use=S.snap.usage||[], ms=mergeRows(S.snap), ws=slots().filter(s=>s.state!=='merging'&&s.task), now=workNowIds();
  const sec=(name,h)=>`<div class="sec">${name}<span class="ln"></span></div>${h}`;
  const up=workUpNext(qs,now), land=histLanded(S.snap), past=S.snap.past_releases||[], log=(S.snap.log||[]).slice().reverse();
  const nowRows=ws.map(slotRow).join('')+ms.map(mergeRow).join('');
  const meters=use.length?card(use.map(u=>meterHTML({name:u.name,pct:u.pct,said:u.pct+'%'})).join(''),'','data-k="usage"'):'';
  const parked=pk.length||sh.length||shOb?pk.map(q=>parkedCard(q)).join('')+shOb+sh.map(q=>shelvedCard(q)).join(''):'';
  return `${ttydLine()}${controlsCard()}${meters}
    ${sec('Now',nowRows?card(nowRows,'','data-k="working"'):emptyCard('No agent is working.'))}
    ${(S.snap.prs||[]).length?sec('Pull requests',card(S.snap.prs.map(prRow).join(''),'','data-k="prs"')):''}
    ${newReleaseCard()}${sec('Up next',up.length?up.map(queueCard).join(''):emptyCard('The queue is empty.'))}
    ${obCards(x=>obActs(x,'queue')||(x.grip||x.waitset)&&x.state==='failed')}
    ${histSec('Landed',land.map(x=>histRow(x,'landed')),'Nothing has landed yet.','landed')}
    ${releasesOn(S.snap)&&past.length?histSec('Releases',past.map(x=>histRow(x,'pastrel')),'','pastrel'):''}
    ${parked?workFold('parked','Parked',pk.length+sh.length,parked):''}
    ${workFold('log','Run log',0,log.length?histLog(log):emptyCard('Nothing in the run log yet.'))}`;
}
document.addEventListener('click',e=>{
  const x=e.target.closest('[data-workfold]');if(!x)return;
  S.workOpen=S.workOpen||{};S.workOpen[x.dataset.workfold]=!S.workOpen[x.dataset.workfold];render(true);
});
