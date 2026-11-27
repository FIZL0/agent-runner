/* F476: the Work page (concept K25, option A): Status, Plan and History as one timeline, in the Plan view's place.
   The run bar and usage on top, then Now (what the slots work on, what merges, open pull requests), Up next (the Queue
   without the tasks Now shows), Landed, and at the bottom Parked, folded.
   One search: Plan's (open, parked and done tasks). The rows are the ones each old page drew, so they open as before */
function workNowIds(){
  const ids=new Set(mergeRows(S.snap).map(m=>m.id));
  for(const s of slots())if(s.task)ids.add(s.task);
  return ids;
}
/* the Queue's rows a Now row already shows are left out of Up next */
const workUpNext=(qs,now)=>qs.filter(q=>q.release||q.placeholder||!now.has(q.id));
/* F487 (concept K26, option A): every section folds; these start open, Parked closed */
const WORK_OPEN={now:1,prs:1,upnext:1,landed:1};
const workIsOpen=k=>{const o=(S.workOpen||{})[k];return o===undefined?!!WORK_OPEN[k]:!!o};
/* a folded section: its head is a fold, as a row's (S.workOpen[k]) */
function workFold(k,name,n,h){
  const open=workIsOpen(k);
  return `<div class="sec" id="work-${esc(k)}"><button class="fold secfold" data-workfold="${esc(k)}" aria-expanded="${open}">${esc(name)}${n?` · ${n}`:''}<span class="chev">${I.chev}</span></button><span class="ln"></span></div>${!open?'':WORK_OPEN[k]?h:foldIn('work:'+k,h)}`;  // the sections open by default draw their rows in place, not in a fold's box: going to the pick mode, a box would leave as a picture over it
}
function workHTML(qs,pk,sh,shOb){
  histAsk();
  const use=S.snap.usage||[], ms=mergeRows(S.snap), ws=slots().filter(s=>s.state!=='merging'&&s.task), now=workNowIds();
  const up=workUpNext(qs,now), land=histLanded(S.snap);
  const nowRows=ws.map(slotRow).join('')+ms.map(mergeRow).join('');
  const meters=use.length?card(use.map(u=>meterHTML({name:u.name,pct:u.pct,said:u.pct+'%'})).join(''),'','data-k="usage"'):'';
  const parked=pk.length||sh.length||shOb?pk.map(q=>parkedCard(q)).join('')+shOb+sh.map(q=>shelvedCard(q)).join(''):'';
  const prs=S.snap.prs||[];  // BUG3: no Releases section: release cards stand in Up next, in queue order
  const secs=[['now','Now',0,nowRows?card(nowRows,'','data-k="working"'):emptyCard('No agent is working.')],
    prs.length&&['prs','Pull requests',prs.length,card(prs.map(prRow).join(''),'','data-k="prs"')],
    ['upnext','Up next',up.length,up.length?up.map(queueCard).join(''):emptyCard('The queue is empty.'),newReleaseCard(),obCards(x=>obActs(x,'queue')||(x.grip||x.waitset)&&x.state==='failed')],
    ['landed','Landed',land.length,land.length?card(land.map(x=>histRow(x,'landed')).join(''),'','data-k="landed"'):emptyCard('Nothing has landed yet.')],
    parked&&['parked','Parked',pk.length+sh.length,parked]].filter(Boolean);
  const jump=`<div class="workjump" role="navigation" aria-label="Sections">${secs.map(([k,name])=>`<button class="chip${S.workJump===k?' on':''}" data-workjump="${k}"${S.workJump===k?' aria-current="true"':''}>${esc(name)}</button>`).join('')}</div>`;
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
  const k=x.dataset.workjump;S.workOpen=S.workOpen||{};S.workJump=k;
  if(!workIsOpen(k))S.workOpen[k]=true;
  render(true);
  const el=document.getElementById('work-'+k), box=el&&el.closest('.body');if(!box)return;
  const bar=box.querySelector('.workjump');
  scrollGlide(box,b=>{const h=document.getElementById('work-'+k);return h?h.getBoundingClientRect().top-b.getBoundingClientRect().top+b.scrollTop-(bar?workBarBottom(b,bar):0)-8:b.scrollTop});  // BUG3: below the bar where it sticks, so the head is not under it
});
/* BUG3: the jump bar's own bottom, in the scroll box's frame: where its sticky top puts it, not a guess */
function workBarBottom(box,bar){
  const t=parseFloat(getComputedStyle(bar).top)||0;
  return t+bar.offsetHeight;
}
/* BUG3: the marked pill follows scroll: the last section whose head has reached the jump bar (a scroll listener, not an
   IntersectionObserver, as each render draws new heads); marked in place, no render */
function workSpy(box){
  const bar=box.querySelector('.workjump');if(!bar)return;
  const top=box.getBoundingClientRect().top+workBarBottom(box,bar)+12;
  const heads=[...box.querySelectorAll('.worksecs > .sec[id^="work-"]')];if(!heads.length)return;
  let k=heads[0].id.slice(5);
  for(const h of heads)if(h.getBoundingClientRect().top<=top)k=h.id.slice(5);
  if(box.scrollTop+box.clientHeight>=box.scrollHeight-2)k=heads[heads.length-1].id.slice(5);  // at the end the last section is marked, even when its head cannot reach the bar
  if(S.workJump===k)return;
  S.workJump=k;
  for(const c of bar.querySelectorAll('[data-workjump]')){const on=c.dataset.workjump===k;c.classList.toggle('on',on);if(on)c.setAttribute('aria-current','true');else c.removeAttribute('aria-current')}
}
document.addEventListener('scroll',e=>{
  const box=e.target&&e.target.closest?e.target.closest('.body'):null;
  if(box&&box.querySelector('.workjump'))workSpy(box);
},true);
