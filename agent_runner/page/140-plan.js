/* F212: the search. The server finds (plan_search.py); PQ.key: the words and the plan it was asked for, PQ.got: its last answer */
const PQ={key:'',at:0,wait:0,got:null,err:'',old:false}, PQ_MS=200;
const planWant=()=>String(S.f.planq||'').trim();
const planField=()=>`<div class="row"><span class="setq grow"><input class="fld" type="search" data-f="planq" placeholder="Find a task" aria-label="Find a task"><button type="button" class="x" data-setqclear data-planqclear aria-label="Clear search"${S.f.planq?'':' hidden'}>${I.x}</button></span></div>`;
/* asked again when the words, or the tasks in the snapshot, change; an answer to an older ask is dropped */
function planAsk(){
  const q=planWant(), key=q&&JSON.stringify([q,(S.snap.queue||[]).map(x=>[x.id,x.title,x.state==='parked']),(S.snap.shelved||[]).map(x=>x.id)]);
  if(key===PQ.key)return;
  clearTimeout(PQ.wait);PQ.key=key;PQ.at++;PQ.err='';
  if(q)PQ.wait=setTimeout(planLoad,PQ_MS);else PQ.got=null;
}
async function planLoad(){
  const q=planWant(), at=++PQ.at;let j;
  try{j=await (await fetch(tq('plan-search?q='+encodeURIComponent(q)))).json()}catch(e){j={ok:false,out:'Could not reach the run page.'}}
  if(at!==PQ.at)return;
  if(j.ok){PQ.got=j;PQ.err=''}else{PQ.err=plainOut(j,'The plan could not be searched.');PQ.old=oldRun(j)}
  render();
}
/* a hit's card is the snapshot's, with its actions; one the snapshot does not have yet, or a done one, is its fold alone */
function planHit(h){
  const q=(S.snap.queue||[]).find(x=>x.id===h.id), sh=(S.snap.shelved||[]).find(x=>x.id===h.id), done=h.state==='done'||h.state==='dropped';
  if(!done&&sh)return ['parked',shelvedCard(sh)];
  if(!done&&q)return q.state==='parked'?['parked',parkedCard(q)]:['open',q.release?releaseCard(q):planCard(q)];
  if(!done&&obHidden(S.ob,'shelved').includes(h.id))return null;
  return [done?'done':h.state==='open'?'open':'parked',card(taskRow(h,h.title||h.id),'',`data-k="task:${esc(h.id)}"`)];
}
function planFound(q){
  const g=PQ.got, err=PQ.err?card(`${PQ.old?oldRunHTML(PQ.err):`<div class="small v-bad">${esc(PQ.err)}</div>`}<div class="btns"><button class="btn" data-planqload>Try again</button></div>`):'';
  if(!g||PQ.err&&g.q!==q)return err||emptyCard('Loading…');
  const hits=[...g.open,...g.parked,...g.done].map(planHit).filter(Boolean), of=k=>hits.filter(h=>h[0]===k).map(h=>h[1]).join('');
  const sec=(name,h)=>h?`<div class="sec">${name}<span class="ln"></span></div>${h}`:'';
  const open=of('open'), parked=of('parked'), done=of('done'), sent=obCards(x=>obActs(x,'queue')||x.shelved);  // what was pressed is no match
  return err+sent+sec('Open',open)+sec('Parked',parked)+sec('Done',done)+(g.more?`<div class="small">${g.more} more done ${g.more===1?'task':'tasks'}. Add a word to find fewer.</div>`:'')
    +(open||parked||done?'':emptyCard(g.q===q?'No task matches.':'Loading…'));
}
/* the field in use stays the same element, as in Settings (F204a) */
function planDraw(el,h){
  if(el._h!==h&&el._gone)for(const g of el._gone)g.remove();  // leaving() puts them back
  return fieldHTML(el,h,'planq');
}
function planHTML(){
  planAsk();
  const pk=queueGroups(S.snap.queue)[1], sh=S.snap.shelved||[], shOb=obCards(x=>x.shelved), qs=planQueue(S.snap), rs=planReleases(S.snap);
  if(planWant())return `<div class="col">${planField()}${planFound(planWant())}</div>`;
  return `<div class="col">${planField()}${releasesOn(S.snap)?`<div class="sec">Releases<span class="ln"></span></div>${rs.length?`${rs.map(q=>q.placeholder?nextReleaseCard(q):releaseCard(q)).join('')}`:''}`:''}${newReleaseCard()}<div class="sec">Queue<span class="ln"></span></div>${qs.length?qs.map(planCard).join(''):emptyCard('The queue is empty.')}
    ${obCards(x=>obActs(x,'queue'))}${pk.length||sh.length||shOb?`<div class="sec">Parked<span class="ln"></span></div>${pk.map(parkedCard).join('')}${shOb}${sh.map(shelvedCard).join('')}`:''}</div>`;
}
/* F87: the Concepts view: every concept waiting for a pick, as agent-runner ui's Concepts panel lists them */
function conceptsHTML(){
  const cs=S.snap.concepts||[];
  return `<div class="col"><div class="sec">Concepts<span class="ln"></span></div>
    ${obCards(x=>x.concept)}${cs.length?cs.map(conceptCard).join(''):emptyCard(`${NO_CONCEPT}`)}</div>`;
}
/* F83: where each view was scrolled to (S.at), whether Talk follows its newest words (S.pin) */
