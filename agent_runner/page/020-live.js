/* --- F137: the outbox (obParse and the rest in the logic script) ------------------------------------------ */
/* B161: the tabs of one project share it (Runner Home serves every project from one address). One tab sends an item:
   the one it was taken in (by), which marks itself as there (OB_TAB) while it has items to send; another takes the
   item over only once that mark is gone or OB_DEAD ms old */
const OB_KEY='ar-outbox'+(HKEY?':'+HKEY:''), OB_TAB='ar-outbox-tab:', OB_DEAD=20000;
const newCid=()=>Date.now().toString(36)+Math.random().toString(36).slice(2,10);
S.ob=obParse(store.get(OB_KEY));S.obOpen=false;
const OB={tab:newCid(),kept:true,at:'',busy:false,offline:false,timer:0,beat:0,wait:2000};  // kept: this browser stores it
function obLoad(){if(OB.kept)S.ob=obParse(store.get(OB_KEY))}  // what another tab changed: never an old copy over it
function obChange(fn){obLoad();S.ob=fn(S.ob);const t=S.ob.length?JSON.stringify(S.ob):'';store.set(OB_KEY,t);OB.kept=store.get(OB_KEY)===t;obBeat()}
function obBeat(){const on=S.ob.some(x=>x.by===OB.tab&&x.state==='sending');store.set(OB_TAB+OB.tab,on?String(Date.now()):'');clearTimeout(OB.beat);if(on)OB.beat=setTimeout(obBeat,4000)}
function obLive(){return S.ob.map(x=>x.by).filter(t=>t&&Date.now()-Number(store.get(OB_TAB+t))<OB_DEAD)}
/* take over an item whose tab is gone; false when another tab took it at the same moment */
async function obTake(it){
  if(it.by)store.set(OB_TAB+it.by,'');
  obChange(b=>b.map(x=>x.cid===it.cid?{...x,by:OB.tab}:x));
  await new Promise(r=>setTimeout(r,60));obLoad();
  return S.ob.some(x=>x.cid===it.cid&&x.by===OB.tab&&x.state==='sending');
}
/* B154: the sent messages (sentStep), kept over a reload */
const SENT_KEY='ar-sent'+(HKEY?':'+HKEY:'');
S.sent=sentParse(store.get(SENT_KEY));
const keepSent=()=>{const o={};for(const [n,s] of Object.entries(S.sent))if((s.pending||[]).length)o[n]=s.pending;store.set(SENT_KEY,Object.keys(o).length?JSON.stringify(o):'')};
function addSent(n,text,at,more,len){
  const now=Date.now(), p=(S.sent[n]&&S.sent[n].pending)||[];
  S.sent[n]={...(S.sent[n]||{}),...(more&&more.first?{start:true}:{}),at:now,len:len==null?feedOf(n).length:len,pending:[...p,{id:newCid(),text,at:at||0,since:now,state:'sent',...(more||{})}]};keepSent();
}
/* a new chat's ask, from the action that started it: pending in its thread */
function carrySent(n,j,ask){const text=(j&&j.ask)||ask;if(n&&text)addSent(n,text,j&&j.at,{first:true},0)}
/* a new chat whose ask went, until its reply starts: the starting line */
const starting=n=>!!(S.sent[n]&&S.sent[n].start)&&!S.sent[n].pending.some(p=>p.state==='failed')&&!feedOf(n).some(e=>e.kind==='say'||e.kind==='tool');
const startLine=n=>starting(n)?`<div class="think">${LOGO()}${WAVE}Starting the chat…</div>`:'';
function sentDrop(n,id){const s=S.sent[n], p=s&&s.pending.find(x=>x.id===id);if(p){s.pending=s.pending.filter(x=>x!==p);if(p.first)s.start=false;keepSent()}return p}
/* a message's words as a key: the same bubble while it is sending, sent and in the feed, so it comes in once */
const tkey=t=>String(t||'').replace(/\s+/g,' ').trim().slice(0,120);
function sentBubbles(n,shown){
  let h='';
  for(const p of (S.sent[n]&&S.sent[n].pending)||[]){const b=p.state==='failed', d=`data-n="${esc(n)}"`;
    h+=`<div class="u pending${b?' failed':''}" data-k="s:${esc(p.id)}" data-t="${esc(tkey(shown(p.text)))}">${esc(shown(p.text))}${b?`<div class="small">Not delivered: it is not in ${esc(n)}'s chat</div><div class="btns"><button class="btn pri" data-sentretry="${esc(p.id)}" ${d}>Retry</button><button class="btn" data-sentdrop="${esc(p.id)}" ${d}>Discard</button></div>`:''}</div>`}
  return h;
}
/* take an action: drawn at once by the caller, kept in the outbox, sent behind */
function outbox(name,args,more){
  const it={cid:newCid(),name,args:args||{},by:OB.tab,state:'sending',err:'',at:Date.now(),say:name,...(more||{})};
  const ck=String(it.ctl||''), w=ck.endsWith(':')&&ctlWant(ck.slice(0,-1),S.snap,(it.args||{}).n);  // B851a: a run control shows its result now
  if(w){const ks=Object.keys(w);S.held=(S.held||[]).filter(p=>!Object.keys(p.want).some(k=>ks.includes(k))).concat([{key:ck.slice(0,-1),cid:it.cid,n:(it.args||{}).n,at:it.at,want:w,say:it.say}]);S.heldErr='';setTimeout(()=>render(true),CTL_HOLD+50)}  // a later press on the same thing takes the place of the earlier
  obChange(b=>obAdd(b,it,OB.at));render(true);drain();return it;
}
async function drain(){
  if(OB.busy)return;OB.busy=true;clearTimeout(OB.timer);
  try{
    for(let it;obLoad(),(it=obNext(S.ob,OB.tab,obLive()));){
      if(it.by!==OB.tab&&!await obTake(it))continue;
      let j;OB.at=it.cid;
      try{const r=await fetch(tq('act'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:it.name,args:it.args,cid:it.cid,hold:true})});
        if(r.status>=500)throw new Error(`HTTP ${r.status}`);
        j=await r.json()}
      catch(e){OB.offline=true;OB.timer=setTimeout(drain,OB.wait);OB.wait=Math.min(OB.wait*2,30000);obDraw();return}
      OB.offline=false;OB.wait=2000;obLoad();
      if(!S.ob.some(x=>x.cid===it.cid))continue;  // discarded while it went
      if(j&&j.hold){obChange(b=>obHold(b,it.cid,j,Date.now()));if(S.ob.some(x=>x.cid===it.cid&&x.state==='failed'))obDone(it,j);render(true);continue}  // B158
      obChange(b=>obSettle(b,it.cid,j,S.snap.boot));
      obDone(it,j);render(true);
    }
    if(S.ob.some(x=>x.state==='sending'&&x.heldAt&&(!x.by||x.by===OB.tab)))OB.timer=setTimeout(drain,HOLD_STEP+100);  // B158
    else if(S.ob.some(x=>x.state==='sending'&&x.heldAt)||obNext(S.ob))OB.timer=setTimeout(drain,OB_DEAD);  // B161: another tab's: looked at again, should it go away
  }finally{OB.busy=false;OB.at=''}
  obDraw();
}
/* what the page does once the run answered an item */
function obDone(it,j){
  const now=Date.now(), snapNow=()=>fetch(tq('snapshot')).then(s=>s.json()).then(takeSnap).catch(()=>{});
  const later=it.set&&S.ob.some(x=>x.cid!==it.cid&&x.set&&x.set.id===it.set.id&&x.name===it.name&&x.state==='sending');  // F174: the field holds a newer value that goes next
  if(it.ctl==='start:'&&j&&j.ok){S.startOk=now;snapNow()}  // F402c: starting until a snapshot says that it is up
  if(it.setbar&&!oldRun(j)){settingsDone(it,j);return}  // F202b
  if(it.set&&!later&&!(j&&j.ok))delete S.f[`set:${it.name==='setting_project'?'project':'device'}:${it.set.id}`];  // the field shows what is kept again
  if(j&&j.seen&&j.confirm&&it.ctl){  // F186: a release the last snapshot did not show is open: asked where New release stands
    obChange(b=>obDrop(b,it.cid));for(const c of controlsOf('release'))Object.assign(c,{confirm:j.confirm,seen:j.seen});
    S.sure=it.ctl.split(':')[0];toast(j.confirm,true);snapNow();return}
  if(!j||!j.ok){toast(oldRun(j)?OLD_RUN:`Not sent: ${it.say}`,true);S.obOpen=true;if(it.need||it.concept||it.shelved)snapNow();return}
  if(it.name==='response_chat')S.responseGone=[...(S.responseGone||[]),it.args.rid];  // F425b
  if(it.newchat&&!j.name&&S.waitNew)S.waitNew.sent={j,ask:it.ask};  // B154: takeSnap finds its name
  if(it.newchat&&j.name){S.came=(S.came||[]).filter(x=>x.name!==j.name&&now-x.at<60000).concat([{name:j.name,was:'@'+it.cid,start:it.at,say:it.say,state:'sending',at:now}]);carrySent(j.name,j,it.ask);boxMove('@'+it.cid,j.name);if(S.waitNew&&S.waitNew.ph==='@'+it.cid)S.waitNew=null;if(S.thread==='@'+it.cid)open(j.name,true)}
  else if(it.name==='chat_to')addSent(it.args.to,it.args.text,j.at,{});  // B154
  else if(it.need&&(it.name==='answer'||it.name==='pitch_no'||(it.name==='run_control'&&(j.gone||it.args.text)))){toast(answerSaid(j,it.need,it.args.text));if(S.f&&(it.args.note||it.args.why||(it.name==='answer'&&!it.args.button)))delete S.f['askre:'+it.need];S.gone=goneMark(S.gone,j,now);snapNow()}
  else if(it.shelved){if(S.gone)delete S.gone[it.shelved];toast(j.said||`${it.say}: done`);snapNow()}  // F184: Needs you may show it at once
  else if(it.concept){S.gone={...(S.gone||{}),[it.concept]:now}}  // a picked concept stays off while the run catches up
  else if(it.ren){const x=sessionOf(it.ren);if(x){x.title=it.args.title;x.renamed=true}}  // F129
  else if(it.set){const f=`set:${it.name==='setting_project'?'project':'device'}:${it.set.id}`, was=S.f[f];loadSettings().then(()=>{if(S.f[f]===was&&!later){delete S.f[f];render(true)}});toast(String(j.out||'Saved').split('\n')[0])}  // F97
  else if(it.ctl){if(it.name==='run_control'&&it.args.key==='wip_show'){S.out={title:it.args.tid,text:String(j.out||'')};openSheet('out')}
    else toast(String(j.out||'').split('\n')[0]||`${it.say}: done`)}  // F124: a run control
  if(it.res&&FD.n===it.res)feedLoad();  // F114
  if(it.done)toast(it.done);
}
/* the cards an item still sending stands in for stay off the lists */
function obHide(){
  const ns=obHidden(S.ob,'need'), cs=obHidden(S.ob,'concept'), sh=obHidden(S.ob,'shelved'), now=Date.now();
  S.snap.needs=(S.snap.needs||[]).filter(n=>!ns.includes(n.id));
  S.snap.shelved=(S.snap.shelved||[]).filter(x=>!sh.includes(x.id));  // F184
  S.snap.concepts=needsShown(S.snap.concepts,S.gone,now).filter(c=>!cs.includes(c.id));
  const h=ctlSettle(S.snap,S.held,S.ob,now);S.held=h.held;if(h.err){S.heldErr=h.err;setTimeout(()=>{if(S.heldErr===h.err){S.heldErr='';render(true)}},CTL_HOLD)}ctlHold(S.snap,S.held);  // B851a
}
/* B164: the run is older than the page: what to do, with the restart control when the run has one */
function oldRunHTML(msg){const rc=controlOf('restart');
  return `<div class="small v-bad">${esc(msg)}</div>${!rc||S.snap.up===false?'<div class="small">Stop the run and start it again.</div>':S.sure==='restart'?ctlSure(rc):`<div class="btns"><button class="btn acc${ctlBusy('restart')?' busy':''}" data-ctl="restart">Restart the run</button></div>`}`}
const obBtns=x=>`${x.state==='failed'&&!obOld(x)?`<button class="btn pri" data-obretry="${esc(x.cid)}">Retry</button>`:''}${x.state==='failed'&&x.name==='chat_to'?`<button class="btn" data-obedit="${esc(x.cid)}">Edit</button>`:''}<button class="btn" data-obdrop="${esc(x.cid)}">Discard</button>`;
const obState=x=>obOld(x)?OLD_WAIT:x.state==='failed'?`Not sent: ${obRefused(x)?OLD_RUN:x.err||'it did not work'}`:OB.offline?'waiting for the connection':x.heldAt?'waiting for the chat to start':'sending…';
function obDraw(){
  const all=S.ob.concat(S.hob||[]), c=obCounts(all), old=S.ob.filter(obOld).length;c.failed-=old;
  const lost=notDelivered();
  const parts=[...obPill(c,OB.offline),...(old?[`${old} waiting for a restart`]:[]),...(lost.length?[`${lost.length} not delivered · tap to see`]:[])], bar=$('obbar'), pop=$('obpop');
  bar.hidden=!parts.length;
  setHTML(bar,parts.length?`<button class="obpill${c.failed||lost.length?' bad':''}" data-obopen>${c.sending?'<span class="livedot"></span>':''}${parts.map(esc).join(' · ')}</button>`:'');
  if(!all.length&&!S.oldRun&&!lost.length)S.obOpen=false;
  if(!S.obOpen)S.oldRun=false;
  if(!S.obOpen&&!pop.hidden&&pop.animate)popOut(pop);
  pop.hidden=!S.obOpen;
  setHTML(pop,S.obOpen?`<div class="obcard" role="dialog" aria-label="Outbox"><div class="row"><b class="grow">Outbox</b><button class="btn" data-obclose>Close</button></div>
    ${S.oldRun||S.ob.some(obRefused)?oldRunHTML(OLD_RUN):''}
    ${all.map(x=>`<div class="obrow ${x.state}"><div class="grow"><div class="ell2">${esc(x.say)}</div><div class="small">${esc(obState(x))}</div></div><div class="btns">${obBtns(x)}</div></div>`).join('')}
    ${lost.map(({n,p})=>`<div class="obrow failed"><div class="grow"><div class="ell2">${esc(p.text)}</div><div class="small">Not delivered: it is not in ${esc(threadTitle(n))}</div></div><div class="btns"><button class="btn pri" data-sentretry="${esc(p.id)}" data-n="${esc(n)}">Retry</button><button class="btn" data-sentdrop="${esc(p.id)}" data-n="${esc(n)}">Discard</button></div></div>`).join('')}</div>`:'');
}
/* F189b: a copy of the closed popup fades */
function popOut(pop){
  if(calm())return;
  const g=pop.cloneNode(true);g.removeAttribute('id');g.setAttribute('aria-hidden','true');g.inert=true;Object.assign(g.style,{animation:'none',pointerEvents:'none'});
  document.body.appendChild(g);
  const a=moAnim(g,[{opacity:1},{opacity:0}],{ease:'--ease',dur:'--dur-fast',fill:'forwards'});a.onfinish=a.oncancel=()=>g.remove();
}
/* the stand-ins: a starting chat in the sidebar, a sent answer in Needs you, a queued concept, a message */
/* F201: the starting chats as rows: those in the outbox, then one that has its name but that no snapshot lists yet (S.came) */
const standRows=()=>(S.came||[]).filter(x=>!sessionOf(x.name)&&Date.now()-x.at<60000).concat(S.ob.filter(x=>x.newchat).map(x=>({name:'@'+x.cid,say:x.say,state:x.state,start:x.at}))).map(x=>({...x,stand:true})).sort((a,b)=>(a.start||0)-(b.start||0));
const standRow=x=>`<div class="crow" data-k="chat:${esc(x.name)}"><button class="thread ${S.thread===x.name?'on':''} ob ${x.state}" data-thread="${esc(x.name)}">${x.state==='failed'?'':'<span class="livedot"></span>'}<span class="t">${esc(x.say)} · ${x.state==='failed'?'did not start':'starting…'}</span></button></div>`;
const sideRow=(x,quiet)=>x.stand?standRow(x):chatRow(x,quiet);
function obCards(key){return S.ob.filter(key).map(x=>card(`<div class="row obstand ${x.state}">${x.state==='failed'?'':'<span class="livedot"></span>'}<div class="grow"><div>${esc(x.say)}</div><div class="small">${esc(obState(x))}</div></div>${x.state==='failed'?`<div class="btns">${obBtns(x)}</div>`:''}</div>`,'',`data-k="ob:${esc(x.cid)}" data-v="${x.state}"`)).join('')}
/* what waits for a chat that is still starting: its first message, then what was written since */
function obBubbles(n){
  let h='';
  const up=n&&n[0]==='@'&&S.ob.find(x=>'@'+x.cid===n);
  if(up&&up.ask)h+=`<div class="u pending ${up.state}" data-k="ob:${esc(up.cid)}" data-t="${esc(tkey(up.ask))}">${esc(up.ask)}</div>`;  // B139: its first message
  for(const x of S.ob)if(x.name==='chat_to'&&obTo(x)===n)h+=`<div class="u pending ${x.state}" data-k="ob:${esc(x.cid)}" data-t="${esc(tkey(x.args.text))}">${esc(x.args.text)}${x.state==='failed'?`<div class="small">${esc(obState(x))}</div><div class="btns">${obBtns(x)}</div>`:''}</div>`;
  if(up)h+=`<div class="think">${LOGO()}${up.state==='failed'?esc(obOld(up)?OLD_WAIT:`The chat did not start: ${up.err}`):'Starting the chat… what you write goes once it is up'}</div>`;
  return h;
}
/* B154: messages a chat never got, for the outbox (a Talk one shows in Talk) */
const notDelivered=()=>Object.entries(S.sent||{}).flatMap(([n,s])=>(s.pending||[]).filter(p=>p.state==='failed'&&!p.talk).map(p=>({n,p})));
/* B164: the run restarted: what the older one did not know is sent again */
function obBoot(boot){for(const x of obDue(S.ob,boot))obRetryClick(x.cid,obBootCid(x,boot))}
function obRetryClick(cid,as){  /* Retry: a new chat sent again gets a new cid, so its stand-in follows */
  obLoad();const before=S.ob, fresh=as||newCid();obChange(b=>obRetry(b,cid,fresh,as?'':OB.tab));  // B161: the run restarted: any one tab sends it
  const was=before.find(y=>y.newchat&&!S.ob.some(z=>z.cid===y.cid));
  if(was){const ph='@'+fresh;boxMove('@'+was.cid,ph);if(S.thread==='@'+was.cid)S.thread=ph;S.waitNew={known:chats().map(c=>c.name),at:Date.now(),ph}}
  render(true);drain();
}
function obEditBack(cid){  /* a message that failed goes back in its box */
  const x=S.ob.find(y=>y.cid===cid);if(!x)return;
  obChange(b=>obDrop(b,cid));S.obOpen=false;
  if(!x.key||x.key==='home'){store.set(DRAFT_KEY('home'),x.text||'');return goView('home')}
  const to=obTo(x), t=to&&!to.startsWith('@')?to:x.key;  // a chat that came up since: its own box
  if(x.about)questionMark(t,x.about);  // F192a2: still about its question
  store.set(DRAFT_KEY(t),x.text||'');open(t);
}
addEventListener('online',()=>drain());
addEventListener('storage',e=>{if(e.key===OB_KEY){obLoad();render(true);drain()}else if(e.key&&e.key.startsWith(OB_TAB)&&!e.newValue)drain()});  // another tab
/* B161: a tab that goes leaves its items to another (or to its own reload); one that comes back looks what went meanwhile */
function obBack(){const was=JSON.stringify(S.ob);obLoad();obBeat();if(JSON.stringify(S.ob)!==was)render(true);drain()}
addEventListener('pagehide',()=>{clearTimeout(OB.beat);store.set(OB_TAB+OB.tab,'')});
addEventListener('pageshow',e=>{if(e.persisted)obBack()});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)obBack()});

