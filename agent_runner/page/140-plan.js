/* F212: the search. The server finds (plan_search.py); PQ.key: the words and the plan it was asked for, PQ.got: its last answer */
const PQ={key:'',at:0,wait:0,got:null,err:'',old:false}, PQ_MS=200;
const planWant=()=>String(S.f.planq||'').trim();
const planField=()=>`<div class="planq"><div class="row"><span class="setq grow"><input class="fld" type="search" data-f="planq" placeholder="Find a task" aria-label="Find a task"><button type="button" class="x" data-setqclear data-planqclear aria-label="Clear search"${S.f.planq?'':' hidden'}>${I.x}</button></span></div></div>`;
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
  if(!done&&sh)return ['parked',shelvedCard(sh,'found:parked')];
  if(!done&&q)return q.state==='parked'?['parked',parkedCard(q,'found:parked')]:['open',(q.release?releaseCard:planCard)(q,'found:open')];
  if(!done&&obHidden(S.ob,'shelved').includes(h.id))return null;
  const sec=done?'done':h.state==='open'?'open':'parked';
  return [sec,card(taskRow(h,h.title||h.id,'','found:'+sec),'',`data-k="task:${esc(h.id)}"`)];
}
function planFound(q){
  const g=PQ.got, err=PQ.err?card(`${PQ.old?oldRunHTML(PQ.err):`<div class="small v-bad">${esc(PQ.err)}</div>`}<div class="btns"><button class="btn" data-planqload>Try again</button></div>`):'';
  if(!g||PQ.err&&g.q!==q)return err||emptyCard('Loading…');
  const hits=[...g.open,...g.parked,...g.done].map(planHit).filter(Boolean), of=k=>hits.filter(h=>h[0]===k).map(h=>h[1]).join('');
  const sec=(name,h)=>h?`<div class="sec">${name}<span class="ln"></span></div>${h}`:'';
  const open=of('open'), parked=of('parked'), done=of('done'), sent=obCards(x=>obActs(x,'queue')||(x.grip||x.waitset)&&x.state==='failed'||x.shelved);  // what was pressed is no match
  return err+sent+sec('Open',open)+sec('Parked',parked)+sec('Done',done)+(g.more?`<div class="small">${g.more} more done ${g.more===1?'task':'tasks'}. Add a word to find fewer.</div>`:'')
    +(open||parked||done?'':emptyCard(g.q===q?'No task matches.':'Loading…'));
}
/* the field in use stays the same element, as in Settings (F204a) */
function planDraw(el,h){
  if(el._h!==h&&el._gone)for(const g of el._gone)g.remove();  // leaving() puts them back
  const keep=gripKeep(el), waits=S.planWait?waitKeep(el):keep, drew=fieldHTML(el,h,'planq');keep();waits();return drew;  // F429c
}
/* F195c: New release, then the Queue with the releases as rows at their place; a landed one is past (History) */
function planHTML(){
  planAsk();
  const pk=queueGroups(S.snap.queue)[1], sh=S.snap.shelved||[], shOb=obCards(x=>x.shelved), qs=gripRows(menuRows(waitRows(planRows(S.snap))));
  if(S.planWait)return waitHTML(qs);  // F442
  if(planWant())return `${planField()}<div class="col">${planFound(planWant())}</div>`;
  if(typeof workHTML==='function')return `${planField()}<div class="col">${workHTML(qs,pk,sh,shOb)}</div>`;  // F476: the Work page (a test's page without it draws the Queue alone)
  return `${planField()}<div class="col">${newReleaseCard()}<div class="sec">Queue<span class="ln"></span></div>${qs.length?qs.map(queueCard).join(''):emptyCard('The queue is empty.')}
    ${obCards(x=>obActs(x,'queue')||(x.grip||x.waitset)&&x.state==='failed')}${pk.length||sh.length||shOb?`<div class="sec">Parked<span class="ln"></span></div>${pk.map(q=>parkedCard(q)).join('')}${shOb}${sh.map(q=>shelvedCard(q)).join('')}`:''}</div>`;
}
/* F87: the Concepts view: every concept waiting for a pick, as agent-runner ui's Concepts panel lists them */
function conceptsHTML(){
  const all=S.snap.concepts||[], cs=all.filter(c=>!c.history), past=all.map((c,i)=>[c,i]).filter(([c])=>c.history);  // F516: History rows come last, so the open ones keep their index
  return `<div class="col"><div class="sec">Concepts<span class="ln"></span></div>
    ${obCards(x=>x.concept)}${cs.length?cs.map(conceptCard).join(''):emptyCard(`${NO_CONCEPT}`)}${typeof conceptHistoryHTML==='function'?conceptHistoryHTML(past):''}</div>`;
}
/* F83: where each view was scrolled to (S.at), whether Talk follows its newest words (S.pin) */
/* F463: a concept item's options page, framed in its Needs you card (the run page's own copy, sandboxed, lazy):
   about 60vh, Expand to its full height; Open in claude.ai beside it when it has a page there */
function conceptFrame(n){
  if(!n.frame)return '';
  const full=!!(S.frameFull||{})[n.id], id=esc(n.id);
  const cl=n.url&&/^https?:/.test(n.url)?`<a class="btn" href="${esc(n.url)}" target="_blank" rel="noopener">Open in claude.ai ${I.ext}</a>`:'';
  return `<div class="cframe${full?' full':''}" data-k="cframe:${id}"><iframe src="${esc(tq(n.frame))}" data-keep="cframe:${id}" sandbox="allow-scripts" loading="lazy" referrerpolicy="no-referrer" title="${esc(n.title||n.id)}: its options"></iframe>
    <div class="btns tight"><button class="btn" data-framefull="${id}" aria-expanded="${full}">${full?'Shrink':'Expand'}</button>${cl}</div></div>`}
