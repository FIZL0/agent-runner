/* --- live data --------------------------------------------------------------------------------------------- */
let RUN_VERSION='';  // F90
/* F149: the popup over the view when the run serves another page than this one, or needs a restart (pageNews). Refresh
   keeps what is written: boxes and the outbox are kept as they are typed, the rest by keepTyped(). */
const LATER_KEY='ar-later', TYPED_KEY='ar-typed:'+(HKEY||document.title);
S.later=tabStore.get(LATER_KEY).split(' ').filter(Boolean);
const newsNow=()=>pageNews(S.snap,PAGE_PRINT.startsWith('/*')?'':PAGE_PRINT,S.later);
function newsHTML(x){
  const later=`<button class="btn" data-newslater="${esc(x.key)}">Later</button>`;
  if(x.kind==='refresh')return `<div>A new version of this page is ready</div><div class="btns"><button class="btn acc" data-newsrefresh>Refresh</button>${later}</div>`;
  if(HOME_PAGE)return `<div>A new version is ready. Restart Runner Home to use it.</div><div class="btns">${later}</div>`;
  const rc=controlOf('restart');
  return `<div>A new version is ready. ${rc?'Restart the run to use it.':'Stop the run and start it again to use it.'}</div>${rc&&S.sure==='restart'?ctlSure(rc):`<div class="btns">${rc?`<button class="btn acc${ctlBusy('restart')?' busy':''}" data-ctl="restart">Restart the run</button>`:''}${later}</div>`}`;
}
function newsDraw(){const x=newsNow(), el=$('news');el.hidden=!x;setHTML(el,x?newsHTML(x):'')}
/* F126a: the run's own words on its pages, Home's on Home and All projects */
function loginDraw(){const t=HOME_PAGE||atAll()?H.login:S.snap.claude_login, el=$('login'), was=!el.hidden;el.hidden=!t;setHTML(el,t?`${I.alert}<span>${esc(t)}</span><button class="btn" data-login>Log in again</button>`:'');if(!t&&was&&S.sheet==='login'){closeSheet();toast('The login is renewed')}}
/* F402b3b: no run is up and the page-only process serves this page: said on every view, with Start */
function offDraw(){
  const el=$('runoff'), on=runOff(S.snap,{home:HOME_PAGE||atAll(),view:S.view,thread:S.thread}), c=on&&controlOf('start'), busy=c&&ctlBusy('start');
  el.hidden=!c;setHTML(el,c?`<span>${busy?'Starting the run…':'The run is not running'}</span><button class="btn acc${busy?' busy':''}" data-ctl="start">${esc(c.label)}</button>`:'');
}
function newsLater(key){S.later=[...S.later.filter(k=>k!==key),key].slice(-20);tabStore.set(LATER_KEY,S.later.join(' '));S.sure=null;render(true)}
const devTyped=()=>Object.keys(S.f).some(k=>k.startsWith('dev:'));
/* the words no store has yet, for the page that comes next; false when this browser keeps nothing */
function keepTyped(){
  const f=Object.fromEntries(Object.entries(S.f).filter(([k])=>!k.startsWith('dev:')&&!k.startsWith('givesec:')));
  const atts=Object.fromEntries(Object.entries(S.atts).map(([k,l])=>[k,l.filter(a=>a.path).map(a=>({name:a.name,path:a.path}))]).filter(([,l])=>l.length));
  const some=Object.keys(f).length||Object.keys(atts).length||S.ren, text=some?JSON.stringify({f,atts,ren:S.ren,setOpen:S.setOpen,setAway:S.setAway||Date.now()}):'';
  tabStore.set(TYPED_KEY,text);
  const ta=document.querySelector('[data-in]');
  return tabStore.get(TYPED_KEY)===text&&(!ta||!ta.value||HI.i!==null||store.get(DRAFT_KEY(boxKey()))===ta.value)
    &&!S.draftLost&&(!S.ob.length||store.get(OB_KEY)===JSON.stringify(S.ob));
}
function takeTyped(){
  let k=null;try{k=JSON.parse(tabStore.get(TYPED_KEY)||'null')}catch(e){}
  tabStore.set(TYPED_KEY,'');
  if(!k||typeof k!=='object')return;
  S.f={...S.f,...k.f};S.atts=Array.isArray(k.atts)?{[boxKey()]:k.atts}:k.atts||{};S.ren=k.ren||null;S.setOpen={...S.setOpen,...k.setOpen};S.setAway=Number(k.setAway)||0;
}
function newsRefresh(){
  const said=refreshHold({mic:!!(TK.rec||TK.ear||DK.rec),uploading:Object.values(S.atts).flat().some(a=>!a.path&&!a.err),form:devTyped(),secret:Object.keys(S.f).some(k=>k.startsWith('givesec:')&&S.f[k]),unkept:!keepTyped()});
  if(said){toast(said,true);return false}  // F401: what asked is told that it is held
  location.reload();return true;
}
function takeSnap(s){
  if(!s||s.error){if(s&&s.error)toast(s.error,true);return}
  if(s.version)RUN_VERSION=s.version;
  const booted=!!s.boot&&s.boot!==S.snap.boot;
  S.snap={...S.snap,...s};
  if(!HOME_PAGE)document.title=pageTitle(S.snap.project);  // B153
  if(OB.offline)drain();  // F137: the run answers again: the outbox goes on at once
  S.snap.needs=needsShown(S.snap.needs,S.gone,Date.now());  // B138: a snapshot taken before an answer keeps it off
  if(booted){S.oldRun=false;obBoot(s.boot);if(S.view==='settings'&&(S.setErr||S.set))loadSettings()}  // B164
  // F137: a chat the outbox still starts is named by new_control's answer (obSettle), not by this guess
  if(S.waitNew&&S.waitNew.ph&&S.ob.some(y=>'@'+y.cid===S.waitNew.ph)){}
  else if(S.waitNew){const fresh=chats().map(c=>c.name).filter(x=>!S.waitNew.known.includes(x));
    if(fresh.length){const nm=fresh.sort((a,b)=>b.slice(1)-a.slice(1))[0], ph=S.waitNew.ph, ws=S.waitNew.sent;S.waitNew=null;if(ws)carrySent(nm,ws.j,ws.ask);  // F137: its waiting messages go there
      if(ph){obChange(b=>obName(b,ph,nm));boxMove(ph,nm);drain()}if(!ph||S.thread===ph)open(nm,!!ph);else render();return}
    if(Date.now()-S.waitNew.at>60000)S.waitNew=null}
  for(const w of working_())if(!S.feeds[w.name]||Date.now()-(S.feeds[w.name].at||0)>15000)loadFeed(w.name);
  if(S.kept)keptCheck();  // B177
  for(const x of S.snap.sessions||[])if(x.task||x.link)S.last[x.name]={task:x.task,title:x.title,link:x.link};  // F114: what it was, once it has ended
  const tw=talkWaitName();if(tw&&TK.wait.sent){addSent(tw,TK.wait.sent.text,TK.wait.sent.at,{talk:true,first:true},0);TK.wait.sent=null}if(tw)loadFeed(tw);  // B133: each snapshot also looks for the awaited Talk reply
  render();S.live=true;if(S.needGo)needGo();
}
let lost=0;  /* the banner shows only when no snapshot came for a while, not on every reconnect */
function connect(n=0){
  let es;try{es=new EventSource(tq('events'))}catch(e){return poll()}
  const fine=()=>{n=0;clearTimeout(lost);lost=0;$('offline').hidden=true};
  es.onmessage=e=>{fine();try{takeSnap(JSON.parse(e.data))}catch(x){}};
  es.onerror=()=>{if(!lost)lost=setTimeout(()=>{$('offline').hidden=false},8000);
    if(es.readyState===2){es.onerror=null;setTimeout(()=>connect(n+1),dialWait(n))}};  // F402b3b
}
async function poll(){try{takeSnap(await (await fetch(tq('snapshot'))).json())}catch(e){}setTimeout(poll,4000)}
async function loadFeed(n){
  if(String(n||'')[0]==='@'||isNew(n))return;  // F137: a chat still starting has no feed yet; F172: nor one not started
  try{const r=await fetch(tq('feed/'+encodeURIComponent(n)));if(r.status>=500)return;  // F402b3b: nothing serves the page for a moment: the chat's words stay
    const f=await r.json();
    const old=S.feeds[n];S.feeds[n]={...f,at:Date.now()};
    const sent=S.sent[n], had=JSON.stringify((sent&&sent.pending)||[]), se=sessionOf(n);
    if(sent){sent.pending=sentStep(sent.pending,f.entries,Date.now(),!!se&&se.state!=='off',!!f.more);keepSent()}  // B154
    const moved=had!==JSON.stringify((sent&&sent.pending)||[]);
    talkHear(n);  // F93
    if(S.kept&&keptCheck())render(true);  // B177
    if(moved||!old||JSON.stringify(old.entries)!==JSON.stringify(f.entries)||old.out!==f.out)render()}
  catch(e){}
}
setInterval(()=>{if(S.thread&&!document.hidden)loadFeed(S.thread)},2000);
setInterval(()=>{for(const n of Object.keys(S.sent))if(n!==S.thread&&S.sent[n].pending.length&&!document.hidden)loadFeed(n)},4000);  // B154
setInterval(()=>{const w=talkWaitName(), n=talkName();  // F93; B133: an awaited reply is polled in any view
  if(w)loadFeed(w);else if(n&&!S.thread&&S.view==='talk')loadFeed(n)},2000);

