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
function newsLater(key){S.later=[...S.later.filter(k=>k!==key),key].slice(-20);tabStore.set(LATER_KEY,S.later.join(' '));S.sure=null;render(true)}
const devTyped=()=>Object.keys(S.f).some(k=>k.startsWith('dev:'));
/* the words no store has yet, for the page that comes next; false when this browser keeps nothing */
function keepTyped(){
  const f=Object.fromEntries(Object.entries(S.f).filter(([k])=>!k.startsWith('dev:')&&!k.startsWith('givesec:')));
  const atts=Object.fromEntries(Object.entries(S.atts).map(([k,l])=>[k,l.filter(a=>a.path).map(a=>({name:a.name,path:a.path}))]).filter(([,l])=>l.length));
  const some=Object.keys(f).length||Object.keys(atts).length||S.ren, text=some?JSON.stringify({f,atts,ren:S.ren,setOpen:S.setOpen}):'';
  tabStore.set(TYPED_KEY,text);
  const ta=document.querySelector('[data-in]');
  return tabStore.get(TYPED_KEY)===text&&(!ta||!ta.value||HI.i!==null||store.get(DRAFT_KEY(boxKey()))===ta.value)
    &&(!S.ob.length||store.get(OB_KEY)===JSON.stringify(S.ob));
}
function takeTyped(){
  let k=null;try{k=JSON.parse(tabStore.get(TYPED_KEY)||'null')}catch(e){}
  tabStore.set(TYPED_KEY,'');
  if(!k||typeof k!=='object')return;
  S.f={...S.f,...k.f};S.atts=Array.isArray(k.atts)?{[boxKey()]:k.atts}:k.atts||{};S.ren=k.ren||null;S.setOpen={...S.setOpen,...k.setOpen};
}
function newsRefresh(){
  const said=refreshHold({mic:!!(TK.rec||TK.ear||DK.rec),uploading:Object.values(S.atts).flat().some(a=>!a.path&&!a.err),form:devTyped(),secret:Object.keys(S.f).some(k=>k.startsWith('givesec:')&&S.f[k]),unkept:!keepTyped()});
  if(said)return toast(said,true);
  location.reload();
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
    if(fresh.length){const nm=fresh[fresh.length-1], ph=S.waitNew.ph, ws=S.waitNew.sent;S.waitNew=null;if(ws)carrySent(nm,ws.j,ws.ask);  // F137: its waiting messages go there
      if(ph){obChange(b=>obName(b,ph,nm));boxMove(ph,nm);drain()}if(!ph||S.thread===ph)open(nm);else render();return}
    if(Date.now()-S.waitNew.at>60000)S.waitNew=null}
  for(const w of working_())if(!S.feeds[w.name]||Date.now()-(S.feeds[w.name].at||0)>15000)loadFeed(w.name);
  if(S.kept)keptCheck();  // B177
  for(const x of S.snap.sessions||[])if(x.task||x.link)S.last[x.name]={task:x.task,title:x.title,link:x.link};  // F114: what it was, once it has ended
  const tw=talkWaitName();if(tw&&TK.wait.sent){addSent(tw,TK.wait.sent.text,TK.wait.sent.at,{talk:true,first:true},0);TK.wait.sent=null}if(tw)loadFeed(tw);  // B133: each snapshot also looks for the awaited Talk reply
  render();S.live=true;if(S.needGo)needGo();
}
function connect(){
  let es;try{es=new EventSource(tq('events'))}catch(e){return poll()}
  let lost=0;  /* the banner shows only when no snapshot came for a while, not on every reconnect */
  const fine=()=>{clearTimeout(lost);lost=0;$('offline').hidden=true};
  es.onmessage=e=>{fine();try{takeSnap(JSON.parse(e.data))}catch(x){}};
  es.onerror=()=>{if(!lost)lost=setTimeout(()=>{$('offline').hidden=false},8000)};
}
async function poll(){try{takeSnap(await (await fetch(tq('snapshot'))).json())}catch(e){}setTimeout(poll,4000)}
async function loadFeed(n){
  if(String(n||'')[0]==='@'||isNew(n))return;  // F137: a chat still starting has no feed yet; F172: nor one not started
  try{const f=await (await fetch(tq('feed/'+encodeURIComponent(n)))).json();
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

/* B177: the open view and chat, per project and per tab (the title names the project on the run's own address) */
const PLACE_KEY='ar-place:'+(HKEY||document.title);
let placeWas='';
function keepPlace(){const p=JSON.stringify({v:S.view,t:S.thread||'',...(isNew(S.thread)?{c:S.ctx}:{})});if(!HOME_PAGE&&p!==placeWas){tabStore.set(PLACE_KEY,placeWas=p);if(S.view!=='projects')tabStore.set('ar-tab',S.thread?'':S.view)}}
/* before the first draw; the link's # goes from the address, so a later reload opens what was open then */
function takePlace(){
  if(HOME_PAGE)return;
  const p=placeOf(tabStore.get(PLACE_KEY),location.hash,!!HB,S.ob.filter(x=>x.newchat).map(x=>'@'+x.cid));
  S.view=p.v;S.thread=p.t||null;S.ctx=p.c||null;S.kept=p.t;S.quiet=p.t[0]==='@'?p.t:'';S.needGo=p.need||'';
  if(p.link)try{history.replaceState(null,'',location.pathname+location.search)}catch(e){}
}
/* the chat a reload opened: true when the run has no such chat, and Home is open instead */
function keptCheck(){
  const n=S.kept, f=S.feeds[n];
  if(S.thread!==n||n[0]==='@'||isNew(n)||sessionOf(n)||f&&f.ok){S.kept='';return false}
  if(!S.snap.at||!f||f.name!==n||S.sent[n]&&(S.sent[n].pending||[]).length)return false;
  S.kept='';S.thread=null;S.ctx=null;S.view='home';return true;
}
/* a link to this page, followed in the tab that has it open */
addEventListener('hashchange',()=>{
  if(HOME_PAGE||!placeOf('',location.hash,!!HB).link)return;
  takePlace();S.drawer=false;S.sheet='';S.sure=null;render(true);placeLoad();if(S.needGo)needGo();
});
/* F150: a link to an item of Needs you: its sheet, once the run's word is there */
function needGo(){const id=S.needGo;if(!id||!S.snap.at)return;S.needGo='';if(needOf(id))needOpen(id)}
function placeLoad(){if(S.thread)loadFeed(S.thread);if(S.view==='tools')loadTools();if(S.view==='settings')loadSettings()}

/* --- doing things ------------------------------------------------------------------------------------------ */
function open(n){const quiet=!!S.quiet&&S.quiet===S.thread;S.quiet='';S.thread=n;if(!isNew(n))S.ctx=null;S.drawer=false;S.sheet='';S.sure=null;loadFeed(n);render(true);if(!quiet)setTimeout(()=>document.querySelector('[data-in]')?.focus({preventScroll:true}),50)}  // B177: not for a stand-in a reload opened
function goView(v){S.view=viewOf(v);S.thread=null;S.ctx=null;S.drawer=false;S.sheet='';S.sure=null;render(true);if(S.view==='settings')loadSettings();if(S.view==='tools')loadTools()}
async function send(){
  const ta=document.querySelector('[data-in]');const text=(ta?.value||'').trim();
  const key=boxKey(), atts=S.atts[key]||[];  // B182: this box's own
  if(atts.some(a=>!a.path&&!a.err))return toast('Wait for the attachments to finish uploading');
  const paths=atts.filter(a=>a.path).map(a=>a.path);
  if(!text&&!paths.length)return;
  sentMark(text);
  if(!S.thread&&S.view==='talk'){  // F93; F83: out of the box at once, back in it if it did not go
    histAdd(key,text);HI.i=null;store.set(DRAFT_KEY(key),'');if(ta)ta.value='';delete S.atts[key];
    if(!await talkSend(compose(null,text,paths))){if(!store.get(DRAFT_KEY(key)))store.set(DRAFT_KEY(key),text);if(atts.length)S.atts[key]=[...atts,...(S.atts[key]||[])];render(true)}return}
  const ctx=S.ctx, to=S.thread||'';
  const msg=compose(ctx,text,paths);
  histAdd(key,text);HI.i=null;  // B120: Up brings it back
  store.set(DRAFT_KEY(key),'');if(ta)ta.value='';
  delete S.atts[key];
  const rq=sendReq(ctx,to,msg);
  if(rq.name==='new_control'){newChat(rq.name,rq.args,ctx?ctx.label:text||`${paths.length} attachment(s)`,msg);return}  // B139, F176
  // F137: out of the box at once, a pending message until chat_to answers (obDone), red with Retry if it fails
  if(FD.shown)sendFly();  // the session draws it itself
  outbox('chat_to',{text:msg,to,...(S.thread===to&&sessWorks(to)?{force:true}:{}),...(FD.n===to&&FD.foot&&FD.foot.text?{unsent:true}:{})},{text,key,say:`To ${threadTitle(to)}: ${text||paths.length+' attachment(s)'}`});
}
/* F137: a new chat opens at once as a stand-in ('@cid') that takes messages; new_control starts it without
   waiting, and its messages go once it has a name. B139: ask, its first message, shows in the stand-in. */
function newChat(name,args,say,ask){const known=chats().map(c=>c.name), it=outbox(name,{...args,wait:false},{newchat:true,say,...(ask?{ask}:{})});
  S.waitNew={known,at:Date.now(),ph:'@'+it.cid};open('@'+it.cid)}
/* F172: a card's Chat opens its new chat view; the session starts with the first message (send) */
function about(a){
  const [k,v]=[a.split(':')[0],a.slice(a.indexOf(':')+1)];
  if(a==='new')S.ctx={kind:'new',label:'Add a task'};
  else if(a==='newconcept')S.ctx={kind:'newconcept',label:'New concept'};
  else if(k==='concept'){const c=S.snap.concepts[+v];if(!c)return;S.ctx={kind:'concept',id:c.concept||c.id,title:c.title,label:c.title||c.concept}}
  else if(k==='setting'){const x=settingOf(v);if(!x)return;S.ctx={kind:'setting',id:`[${x.table}] ${x.key}`,title:x.name,label:x.name}}
  else if(k==='plan'){const q=S.snap.queue.concat(S.snap.shelved||[]).find(x=>x.id===v);if(!q)return;S.ctx={kind:'plan',id:q.id,title:q.title,label:`${q.id} ${q.title}`}}
  else return;
  open(ctxKey(S.ctx));const ta=document.querySelector('[data-in]');if(ta)kbFocus(ta);  // in the tap itself, so a phone's keyboard comes
}
async function upload(file){
  const it={name:file.name||'file'};(S.atts[boxKey()]=S.atts[boxKey()]||[]).push(it);
  if((file.type||'').startsWith('image/')){const r=new FileReader();r.onload=()=>{it.thumb=r.result;render(true)};r.readAsDataURL(file)}
  render(true);
  try{const r=await fetch(tq('upload?name='+encodeURIComponent(it.name)),{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:file});
    const j=await r.json();if(j.ok)it.path=j.path;else{it.err=j.out||'upload failed';toast(it.err,true)}}
  catch(e){it.err=plainErr(e);toast(`Upload failed: ${it.err}`,true)}
  render(true);
}

let tapped={n:'',at:0};
document.addEventListener('click',async e=>{
  const q=s=>e.target.closest(s);let x;
  if(S.undo&&!q('[data-undo]'))finalDelete();  // F118: any other click makes the delete final
  if(x=q('[data-feedkey]')){feedKey(x.dataset.feedkey);return}  // F114
  if(q('[data-newsrefresh]')){newsRefresh();return}  // F149
  if(x=q('[data-newslater]')){newsLater(x.dataset.newslater);return}
  if(q('[data-feedkeys]')){S.keys=!S.keys;render(true);return}
  if(q('[data-login]')){loginOpen();return}  // F126b
  if(q('[data-feedtext]')){feedText();return}
  if(x=q('[data-feedcopy]')){const pre=$('feedtext'), pick=()=>{const r=document.createRange();r.selectNodeContents(pre);const g=getSelection();g.removeAllRanges();g.addRange(r)};
    try{await navigator.clipboard.writeText(S.feedText||'');toast('Copied')}catch(err){pick();toast('Selected: copy it with your own Copy')}return}
  if(x=q('[data-resume]')){const n=x.dataset.resume;outbox('resume_chat',{chat:n},{res:n,say:`Resume ${threadTitle(n)}`});return}
  if(q('#sheetscrim')||q('[data-closesheet]')){closeSheet();return}
  if(q('.rowacts'))S.rowOpen='';  // F187: its own handler goes on
  if(q('[data-slimbox]')){feedSlim(false);const t=document.querySelector('[data-in]');if(t&&(!TOUCH()||!e.detail))t.focus({preventScroll:true});return}  // B192: no keyboard on a phone yet: it would resize the session
  if(x=q('[data-halt]')){const n=x.dataset.halt;act('stop_session',{session:n}).then(()=>liveLoad());return}
  if(q('[data-slashopen]')){const t=document.querySelector('[data-in]');if(t){if(!t.value.trim()){t.value='/';store.set(DRAFT_KEY(boxKey()),'/');grow(t)}kbFocus(t);t.setSelectionRange(t.value.length,t.value.length);slashShow(t)}return}
  if(x=q('[data-mode]')){closeSheet();setMode(x.dataset.mode);return}
  if(x=q('[data-sesstask]')){const t=((FD.live||{}).tasks||[]).find(y=>y.id===x.dataset.sesstask);closeSheet();if(t)sessTask(t,x.dataset.do);return}
  if(x=q('[data-update]')){outbox('claude_update',{cmd:x.dataset.update},{upd:1,say:'Update the agent CLI',done:'The agent CLI is updated'});return}
  if(x=q('[data-restart]')){const n=x.dataset.restart;closeSheet();outbox('restart_chat',{chat:n},{res:n,say:`Restart ${threadTitle(n)}`});return}
  if(x=q('[data-sheet]')){openSheet(x.dataset.sheet);return}
  if(x=q('[data-rowmenu]')){rowExpand(x.dataset.rowmenu);return}
  if(x=q('[data-ren]')){startRename(x.dataset.ren);return}
  if(x=q('[data-fix]')){S.fixOpen=S.fixOpen===x.dataset.fix?'':x.dataset.fix;S.sure=null;render(true);return}
  if(x=q('[data-slashpick]')){slashTake(+x.dataset.slashpick);return}  // B119
  if(q('[data-obopen]')){S.obOpen=true;obDraw();return}  // F137: the outbox's pill opens its popup
  if(q('[data-obclose]')||e.target.id==='obpop'){S.obOpen=false;obDraw();return}
  if(x=q('[data-obretry]')){const id=x.dataset.obretry;homeHas(id)?homeRetry(id):obRetryClick(id);return}
  if(x=q('[data-sentdrop]')){sentDrop(x.dataset.n,x.dataset.sentdrop);render(true);return}  // B154
  if(x=q('[data-sentretry]')){const n=x.dataset.n, p=sentDrop(n,x.dataset.sentretry);
    if(p&&p.talk&&!talkOld().includes(n))talkSend(p.text);else if(p)outbox('chat_to',{text:p.text,to:n},{text:p.text,key:n,say:`To ${threadTitle(n)}: ${p.text}`});return}
  if(x=q('[data-obdrop]')){if(homeHas(x.dataset.obdrop)){homeChange(b=>obDrop(b,x.dataset.obdrop));render(true);return}obChange(b=>obDrop(b,x.dataset.obdrop));
    if(String(S.thread||'')[0]==='@'&&!S.ob.some(y=>'@'+y.cid===S.thread))S.thread=null;  // its stand-in chat went
    if(S.waitNew&&S.waitNew.ph&&!S.ob.some(y=>'@'+y.cid===S.waitNew.ph))S.waitNew=null;
    render(true);return}
  if(x=q('[data-obedit]')){obEditBack(x.dataset.obedit);return}
  // F150: the levels of the sidebar, and All projects' buttons (Runner Home's /act and /remove)
  if(q('[data-up]')){goUp(false,!e.detail);return}
  if(x=q('[data-alltab]')){H.tab=x.dataset.alltab;tabStore.set('ar-alltab',H.tab);S.drawer=false;render(true);loadDevices();return}
  if(q('[data-pmore]')){H.more=!H.more;render(true);return}
  if(q('[data-pload]')){loadProjects();loadDevices();return}
  if(q('[data-addproject]')){H.said='';openSheet('addproject');const i=$('sheet').querySelector('input');if(i)kbFocus(i);return}
  if(q('[data-plusslot]')){plusSlot();return}
  if(x=q('[data-projmore]')){openSheet('project',x.dataset.projmore);return}
  if(x=q('[data-pact]')){const k=x.dataset.pkey, p=projectOf(k), a=x.dataset.pact, arg=x.dataset.parg||'', m=p&&projectMore(p).find(b=>b.a===a);if(!p)return;
    if(m&&m.sure&&!x.hasAttribute('data-sure')){S.sure=`proj:${m.label}:${k}`;render(true);return}
    S.sure=null;homeAct(k,a,arg,`${{start:'Start run',pause:'Pause',resume:'Go on',stop:'Stop',slots:`${arg} slot${arg==='1'?'':'s'}`}[a]} · ${p.name||k}`);return}
  if(x=q('[data-punlist]')){const k=x.dataset.pkey;if(!x.hasAttribute('data-sure')){S.sure='proj:Unlist:'+k;render(true);return}
    closeSheet();homePost('remove',{project:k}).then(d=>toast(d.out||(d.ok?'Unlisted':'That did not work'),!d.ok));return}
  if(x=q('[data-askhere]')){e.preventDefault();S.needGo=x.dataset.askhere;goDown();goView('home');needGo();return}
  if((x=q('a[data-pkey]'))&&x.dataset.pkey===HKEY&&atAll()&&!(e.ctrlKey||e.metaKey||e.shiftKey)){e.preventDefault();goDown(false,!e.detail);return}
  if((x=q('[data-pgo]'))&&x.dataset.pkey===HKEY&&HKEY&&atAll()&&!q('a,button,input,form')){goDown();return}
  if((x=q('[data-pgo]'))&&!q('a,button,input,form')){location.href=x.dataset.pgo;return}
  if(slashOpen()&&!q('[data-in]'))slashClose();
  if(q('[data-undo]')){S.undo=null;render(true);return}
  if(x=q('[data-pin]')){const n=x.dataset.pin,names=chatNames(),p=chatPins().filter(m=>names.includes(m));  // F133
    const pins=p.includes(n)?p.filter(m=>m!==n):p.concat([n]);saveChatOrder(chatMove(names,pins,n,names.indexOf(n)),pins);return}
  if(x=q('[data-del]')){S.undo={names:[x.dataset.del],bar:false};S.sel=[];render(true);return}
  if(q('[data-delsel]')){if(S.sel.length){S.undo={names:S.sel,bar:true};S.sel=[]}render(true);return}
  if((x=q('[data-thread]'))&&/^c\d+$/.test(x.dataset.thread)){  // F118: Ctrl/Cmd+click picks, Shift+click a range
    const how=e.shiftKey?'range':e.ctrlKey||e.metaKey?'toggle':'';
    const p=chatPick(chatNames(),S.sel,S.selLast,x.dataset.thread,how);S.sel=p.sel;S.selLast=p.last;
    if(how){e.preventDefault();render(true);return}
    const now=Date.now(), twice=tapped.n===x.dataset.thread&&now-tapped.at<400;tapped={n:x.dataset.thread,at:now};  // F129: a double-click renames
    if(twice&&!S.drawer){startRename(x.dataset.thread);return}
  }
  if(q('[data-micreport]'))return micCopy();
  if(x=q('[data-mictest]'))return micTest(x.dataset.mictest);  // B162b1
  if(q('[data-mictestcopy]'))return micCopyText('Mic test',micTestText());
  if(q('[data-mic]')){micLog(`click, detail ${e.detail}`);if(TS.mic==='hold'&&(e.detail>0||Date.now()-TK.upAt<1000))return;return listen()}  // F93; F124: held (pointerdown), a key still toggles
  if(q('[data-spk]')){if(talkReads())return hush();if(TK.held&&!TK.ear&&TK.state!=='thinking')return speak(TK.held);unlockAudio();talkSet('read',!TS.read);return}
  if(x=q('[data-talkmode]'))return talkMode(x.dataset.talkmode);
  if(x=q('[data-speak]'))return playReply(x.dataset.speak);
  if(q('[data-menu]')){S.drawer=true;render();return}
  if(q('#scrim')){S.drawer=false;render();return}
  if(x=q('[data-view]')){const v=x.dataset.view;return viewGo(()=>goView(v),S.thread)}
  if(q('[data-home]')){viewGo(()=>{S.thread=null;S.ctx=null;render(true)},S.thread);return}
  if(x=q('[data-tool]'))return toolClick(x);  // F169
  if(q('[data-slots-n]')||q('.fld')||q('.sw'))return;
  if(q('[data-unsure]')){S.sure=null;render(true);return}
  if(x=q('[data-ctl]')){const c=controlOf(x.dataset.ctl);if(!c)return;
    const n=c.needs==='n'?String(S.f.slotsn||'').trim():'', tid=x.dataset.tid||'';
    const need=c.answer?needOf(tid):null;if(c.answer&&!need)return;
    const text=need?(need.labels||{})[c.key]||c.label:'', note=need&&x.closest('#sheet')?S.f[askField(tid)]:'';  // F180
    const rq=controlClick(c,{n,tid,sure:x.hasAttribute('data-sure'),text,note});
    if(rq.ask){S.sure=c.key+(tid?':'+tid:'');render(true);return}  // F82: asked in the page, no browser dialog
    if(c.needs==='n'&&!/^\d+$/.test(n))return toast('Type how many slots first',true);
    S.sure=null;S.f.slotsn='';
    if(c.chat){const n=c.where==='need'&&(S.snap.needs||[]).find(x=>x.id===tid);  // B139, C35: it asks a new chat
      newChat(rq.name,rq.args,`${c.label} ${tid}`,n?needChatAsk(n):c.where==='concept'?'':`do ${tid} here`);return}
    if(S.sheet)closeSheet();
    outbox(rq.name,rq.args,{ctl:c.key+':'+tid,say:need?`${tid} · answered “${text}”`:c.label+(tid?` ${tid}`:''),...(c.where==='need'?{need:tid}:c.where==='concept'?{concept:tid}:c.where==='shelved'?{shelved:tid}:{})});return}  // F124: through the outbox
  if(x=q('[data-pitchopen]')){const n=S.snap.needs[+x.dataset.pitchopen];if(!n)return;  // F98
    S.pitchOpen={...(S.pitchOpen||{}),[n.id]:!(S.pitchOpen||{})[n.id]};S.sure=null;render(true);return}
  if(x=q('[data-pitchno]')){const n=S.snap.needs[+x.dataset.pitchno];if(!n)return;
    const how=x.dataset.how, tid=x.dataset.tid||'';
    if(!x.hasAttribute('data-sure')){S.sure=`pitch:${n.id}:${how}:${tid}`;render(true);return}
    const why=x.closest('#sheet')?String(S.f[askField(n.id)]||'').trim():'';
    S.sure=null;outbox('pitch_no',{pid:n.id,how,tid,confirm:true,...(why?{why}:{})},{need:n.id,say:`${n.id} · Not this${tid?': '+tid:''}`});return}
  if(x=q('[data-task]')){openTask(x.dataset.task);return}  // F85
  if(x=q('[data-setopen]')){const id=x.dataset.setopen;S.setOpen[id]=!S.setOpen[id];render(true);return}  // F97
  if(q('[data-setload]')){loadSettings();return}
  if(x=q('[data-setsave]')){saveSetting(x.dataset.id,x.dataset.setsave);return}
  if(x=q('[data-setreset]')){resetSetting(x.dataset.id,x.dataset.setreset);return}
  if(x=q('[data-setstep]')){stepSetting(x.dataset.id,+x.dataset.setstep);return}
  if(x=q('[data-setmore]')){openSheet('setting',x.dataset.setmore);return}
  if(q('[data-setchanged]')){S.setChanged=!S.setChanged;render(true);return}
  if(x=q('[data-thread]')){const n=x.dataset.thread;return viewGo(()=>{S.ctx=null;open(n)},n===S.thread?null:n)}
  if(q('[data-newtalk]'))return newTalk();  // F157
  if(q('[data-new]')){S.drawer=false;newChat('new_control',{},'New chat');return}
  if(x=q('[data-needopen]')){needOpen(x.dataset.needopen);return}  // F162
  if(x=q('[data-askfold]')){S.askFold={...S.askFold,[x.dataset.askfold]:!S.askFold[x.dataset.askfold]};render(true);return}
  if(q('[data-askload]')){S.askWhy={};S.askText={};render(true);askLoad(S.sheetArg);return}
  if(x=q('[data-shot]')){shotGo(+x.dataset.shot);return}
  if(q('[data-shotclose]')){shotGo(-1);return}
  if(x=q('[data-give]')){giveSend(x.dataset.give,x.hasAttribute('data-sure'));return}  // F175a
  if(x=q('[data-stepcopy]')){const pre=$('sheet').querySelector(`[data-stepcmd="${x.dataset.stepcopy}"]`);if(!pre)return;
    try{await navigator.clipboard.writeText(pre.textContent);toast('Copied')}catch(err){const r=document.createRange();r.selectNodeContents(pre);const g=getSelection();g.removeAllRanges();g.addRange(r);toast('Selected: copy it with your own Copy')}return}
  if(x=q('[data-reply]')){needReply(x.dataset.reply);return}
  if(x=q('[data-about]'))return plusHeld(x)?undefined:about(x.dataset.about);
  if(x=q('[data-quick]')){S.ctx=null;const t=x.textContent.trim();  // B139: a new chat
    newChat('quick_ask',{key:x.dataset.quick},t,t);return}
  if(x=q('[data-pick]')){const c=S.snap.concepts[+x.dataset.pick],o=c&&(c.options||[])[+x.dataset.o];if(!o)return;
    outbox('answer',{tid:c.id,text:`go with ${o.name}`},{concept:c.id,say:`${c.concept||c.id} · go with ${o.name}`,done:`Going with ${o.name}`});return}
  if(x=q('[data-unatt]')){(S.atts[boxKey()]||[]).splice(+x.dataset.unatt,1);render(true);return}
  if(q('[data-clip]')){$('file').click();return}
  if(q('[data-dict]'))return dictate();  // F115
  if(x=q('[data-stop]')){const n=x.dataset.stop||shownSession();if(n)act('interrupt',{session:n});return}
});
document.addEventListener('submit',e=>{e.preventDefault();
  if(e.target.matches('[data-padd]'))return addProject();  // F150
  if(e.target.matches('[data-logincode]'))return loginCode();  // F126b
  if(e.target.matches('[data-renform]'))return saveRename();  // F129
  send()});
/* F124, F97: a switch or a select acts at once; a setting's on its row saves at once too */
document.addEventListener('change',e=>{
  const t=e.target, ts=t.dataset&&t.dataset.ts, f=(t.dataset&&t.dataset.f)||'';
  if(t.dataset&&t.dataset.tooluse){toolPost({op:'use',name:t.dataset.tooluse,on:t.checked},t.dataset.tooluse);return}  // F169
  if(f.startsWith('dev:')){S.f[f]=t.type==='checkbox'?String(t.checked):t.value;render(true);return}
  if(t.dataset&&t.dataset.mtear!==undefined){MT.ear=t.value;render(true);return}  // B162b1
  if(ts){talkSet(ts,t.type==='checkbox'?t.checked:t.value);return}
  if(t.dataset&&t.dataset.setpart){savePart(t);return}
  if(t.dataset&&t.dataset.kinds){saveKinds(t.dataset.kinds,t.value);return}
  if(!f.startsWith('set:'))return;
  S.f[f]=t.type==='checkbox'?String(t.checked):t.value;
  if(t.dataset.now!==undefined){const [,side,...id]=f.split(':');saveSetting(id.join(':'),side)}  // F166: a row's own switch or select
});
function selectedText(t){
  if(t&&typeof t.selectionStart==='number'&&t.selectionEnd>t.selectionStart)return true;
  return !!String(window.getSelection&&window.getSelection()||'');
}
/* F150: Alt+1 to 9: the project at that place of All projects. Not where Alt types a character (a Mac's text box) */
addEventListener('keydown',e=>{
  const m=/^Digit([1-9])$/.exec(e.code||'');
  if(!m||!HB||!e.altKey||e.ctrlKey||e.metaKey||e.shiftKey||e.getModifierState&&e.getModifierState('AltGraph')||typingIn(e.target)&&e.key!==m[1])return;
  const r=rowsNow()[m[1]-1];if(!r||oneProject(H.projects))return;
  e.preventDefault();goProject(r);
});
document.addEventListener('keydown',e=>{
  /* B116: Ctrl+C interrupts the open chat while it works (not while text is selected, so copying still works);
     B120: in the message box Esc closes the menu, then interrupts a working chat (never goes back), else leaves
     the box; out of the box Esc never interrupts, it goes back */
  if(e.ctrlKey&&!e.metaKey&&!e.altKey&&(e.key==='c'||e.key==='C')&&!selectedText(e.target)){const n=shownSession();if(n&&busy(n)){e.preventDefault();act('interrupt',{session:n});return}}  // B141
  if(e.target.matches&&e.target.matches('[data-f="ren"]')){  // F129: Enter keeps the name (its form), Esc does not
    if(e.key==='Escape'){e.preventDefault();S.ren=null;render(true)}
    return}
  if(e.key==='Escape'&&S.sheet==='need'&&S.askShot>=0){e.preventDefault();shotGo(-1);return}  // F162
  if(e.key==='Escape'&&S.sheet){e.preventDefault();closeSheet();return}  // the topmost thing only
  if(e.key==='Escape'&&S.rowOpen){e.preventDefault();rowShut();return}  // F187
  if(e.target.matches&&e.target.matches('[data-f]')&&e.key==='Enter'&&e.target.tagName==='INPUT'&&e.target.dataset.f.startsWith('set:')){
    e.preventDefault();const [,side,...id]=e.target.dataset.f.split(':');S.f[e.target.dataset.f]=e.target.value;saveSetting(id.join(':'),side);return}
  if(e.target.matches&&e.target.matches('[data-f^="askre:"]')&&e.key==='Enter'){  // F162: Enter sends a reply; beside answers the note waits for one
    const n=needOf(S.sheetArg);if(n&&needReplies(n)&&!composing(e)){e.preventDefault();needReply(n.id)}return}
  if(e.target.matches&&e.target.matches('[data-f^="give"]')&&e.key==='Enter'){  // F175a: as Done does; one with a secret it cannot take has no Done
    const b=$('sheet').querySelector('[data-give]:not([data-sure])');if(b&&!b.disabled&&!composing(e)){e.preventDefault();giveSend(b.dataset.give,false)}return}
  if(e.target.matches&&e.target.matches('[data-in]')){
    if(slashOpen()&&!composing(e)){  // B119: arrows move, Enter or Tab picks, Esc closes the menu and stays in the box
      if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();SL.i=slashMove(SL.i,SL.items.length,e.key);slashShow(e.target,true);return}
      if(e.key==='Escape'){e.preventDefault();slashClose();return}
      /* B188: on touch Shift does not count: a phone's keyboard that has shifted itself for a capital may send Return with it */
      if(e.key==='Tab'||(e.key==='Enter'&&(!e.shiftKey||TOUCH())&&slashPicks(e.target))){e.preventDefault();slashTake(SL.i);return}
      if(e.key==='Enter')slashClose();  // the command is typed in full: Enter sends it (B181: a new line on touch)
    }
    if(e.key==='Enter'&&boxEnter(e,TOUCH())==='send'){e.preventDefault();send();return}
    if((e.key==='ArrowUp'||e.key==='ArrowDown')&&histKey(e,e.target)){e.preventDefault();return}  // B120: earlier messages
    if(e.key==='Escape'){const n=shownSession();if(n&&busy(n)){e.preventDefault();act('interrupt',{session:n});return}}  // B120; B142: the shown session
    if(e.key==='Escape'){e.preventDefault();e.target.blur();return}
    return}
  if(e.key==='Escape'&&S.sel.length){S.sel=[];render(true);return}  // F118
  if(e.key==='Escape'&&S.drawer){S.drawer=false;render();return}
  if(e.key==='Escape'&&S.thread&&!(e.target.matches&&e.target.matches('input,textarea,select'))){viewGo(()=>{S.thread=null;S.ctx=null;render(true)},S.thread);return}  /* out of the box, Esc goes back */
  const c=e.target.closest&&e.target.closest('.card.tap');if(c&&c===e.target&&(e.key==='Enter'||e.key===' ')){e.preventDefault();c.click()}
});
/* B188: a soft keyboard's Return whose keydown did not say Enter (keyCode 229, or no key name) picks at the line break
   itself; an input method that takes its words makes none */
document.addEventListener('beforeinput',e=>{
  if((e.inputType==='insertLineBreak'||e.inputType==='insertParagraph')&&!e.isComposing&&TOUCH()&&e.target.matches&&e.target.matches('[data-in]')&&slashOpen()&&slashPicks(e.target)){e.preventDefault();slashTake(SL.i)}
});
document.addEventListener('input',e=>{if(e.target.matches('[data-f]')&&e.target.type!=='checkbox'){S.f[e.target.dataset.f]=e.target.value;if(e.target.dataset.f==='setq')render(true);if(e.target.dataset.f.startsWith('give')&&String(S.sure||'').startsWith('give:')){S.sure=null;render(true)}}if(e.target.matches('[data-in]')){grow(e.target);store.set(DRAFT_KEY(boxKey()),e.target.value);HI.i=null;slashShow(e.target)}});
document.addEventListener('paste',e=>{if(!e.target.matches||!e.target.matches('[data-in]'))return;
  const fs=[...(e.clipboardData?.files||[])];if(fs.length){e.preventDefault();fs.forEach(upload)}});
$('file').addEventListener('cancel',holdPlus);
$('file').addEventListener('change',e=>{holdPlus();[...e.target.files].forEach(upload);e.target.value=''});
document.addEventListener('dragover',e=>{if(e.dataTransfer&&[...e.dataTransfer.types].includes('Files'))e.preventDefault()});
document.addEventListener('drop',e=>{if(e.dataTransfer&&e.dataTransfer.files.length){e.preventDefault();[...e.dataTransfer.files].forEach(upload)}});
/* F114: a key of the row keeps the box's focus (and its keyboard) */
for(const t of ['pointerdown','mousedown'])document.addEventListener(t,e=>{if(e.target.closest&&e.target.closest('.keys .tool,[data-feedkeys]'))e.preventDefault()});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&S.thread)loadFeed(S.thread)});
/* F133: drag a chat row to set its place, by pointer events so a phone's touch works too: a mouse drags at once,
   a touch after a short hold (a swipe before it still scrolls the list); the drop is kept by the run */
const dragEnd=()=>{if(!DR)return;const {row,on}=DR, y=on?shiftOf(row).m42:0;clearTimeout(DR.hold);row.classList.remove('lift','drag');row.style.transform='';DR=null;if(y)glideTo(row,0,y);if(on)render(true)};
document.addEventListener('pointerdown',e=>{
  const row=e.target.closest&&e.target.closest('.crow[data-crow]');
  if(!row||e.button>0||e.target.closest('.pin,.del,.rowmenu,.rowacts')||S.undo||e.shiftKey||e.ctrlKey||e.metaKey)return;
  dragEnd();
  DR={row,name:row.dataset.crow,id:e.pointerId,y0:e.clientY,on:false,ready:e.pointerType==='mouse'};
  if(!DR.ready)DR.hold=setTimeout(()=>{if(DR&&DR.row===row){DR.ready=true;row.classList.add('lift')}},350);
});
document.addEventListener('pointermove',e=>{
  if(!DR||e.pointerId!==DR.id)return;
  const dy=e.clientY-DR.y0;
  if(!DR.on){
    if(Math.abs(dy)<6)return;
    if(!DR.ready){dragEnd();return}  // a touch that moves before the hold is a scroll
    DR.on=true;DR.row.classList.add('drag');try{DR.row.setPointerCapture(e.pointerId)}catch(err){}
  }
  DR.row.style.transform=`translateY(${dy}px)`;e.preventDefault();
});
document.addEventListener('touchmove',e=>{if(DR&&DR.ready)e.preventDefault()},{passive:false});  // held: no scroll
document.addEventListener('pointerup',e=>{
  if(!DR||e.pointerId!==DR.id)return;
  if(!DR.on)return dragEnd();
  const name=DR.name, others=[...document.querySelectorAll('.crow[data-crow]')].filter(r=>r!==DR.row);
  const to=others.filter(r=>{const b=r.getBoundingClientRect();return b.top+b.height/2<e.clientY}).length;
  dragEnd();
  noClick=true;setTimeout(()=>noClick=false,0);  // the click that ends a drag opens nothing
  const names=chatNames(),pins=chatPins().filter(m=>names.includes(m)),order=chatMove(names,pins,name,to);
  if(order.join()!==names.join())saveChatOrder(order,pins);
});
document.addEventListener('pointercancel',e=>{if(DR&&e.pointerId===DR.id)dragEnd()});
document.addEventListener('contextmenu',e=>{if(DR&&DR.ready&&e.target.closest&&e.target.closest('.crow'))e.preventDefault()});
let noClick=false;
document.addEventListener('click',e=>{if(noClick){noClick=false;e.preventDefault();e.stopPropagation();return}rowTap(e)},true);
/* F83: a press under way holds the refreshes back, so what it lands on is still there when it ends */
document.addEventListener('pointerdown',e=>{PD.down=!(e.button>0)},true);
for(const t of ['contextmenu','blur','visibilitychange'])addEventListener(t,()=>{PD.down=false},true);
for(const t of ['blur','focus','pagehide'])addEventListener(t,()=>{if(TK.ear)micLog('window '+t)});  // B162: a permission question, another app
for(const t of ['pointerup','pointercancel'])document.addEventListener(t,()=>{PD.down=false;if(PD.late)setTimeout(()=>{if(!PD.down)render()},60)},true);
document.addEventListener('selectionchange',()=>{if(PD.late&&!PD.down&&!selecting())render()});
/* B162: the mic report's pointer events: those on the mic, a new report from a press while nothing listens */
for(const t of ['pointerdown','pointerup','pointercancel','gotpointercapture','lostpointercapture','touchend','touchcancel','contextmenu'])document.addEventListener(t,e=>{
  if(!(e.target&&e.target.closest&&e.target.closest('[data-mic]'))&&!(TK.hold&&e.pointerId!=null&&e.pointerId===TK.holdId))return;
  micLog([t,e.pointerType,e.pointerId==null?'':'id '+e.pointerId,document.hidden?'page hidden':''].filter(Boolean).join(' '),t==='pointerdown'&&!TK.ear);
},{capture:true,passive:true});
document.addEventListener('visibilitychange',()=>{if(TK.ear)micLog(document.hidden?'page hidden':'page shown');
  if(document.hidden)letGo('page hidden');soundSeen(document.hidden);if(!document.hidden)talkNext()});  // B174
/* F124: hold to talk: the mic listens while it is held, silence or not (hear), and sends when it is let go */
document.addEventListener('pointerdown',e=>{
  if(!(e.target.closest&&e.target.closest('[data-mic]'))||TS.mic!=='hold'||e.button>0)return;
  TK.hold=true;TK.holdId=e.pointerId;
  try{e.target.closest('[data-mic]').setPointerCapture(e.pointerId)}catch(err){}  // B162: a finger that drifts off it still holds it
  if(TK.state!=='listening')listen();  // auto listen is on already: letting go sends it
  else if(TK.ear&&TK.ear.stopped)TK.ear.more=true;  // B162: held again before the last one ended: it goes on after that end
});
/* B162: a pointercancel (iOS took the touch) does not end the hold: the finger is still down. Its touchend does, and
   after a touchcancel the mic stops by itself at a silence, or at the next hold's end */
const letGo=by=>{if(TK.hold){TK.hold=false;TK.upAt=Date.now();micStop(by);if(by!=='page hidden')unlockAudio();talkNext()}};
document.addEventListener('pointerup',e=>{if(e.pointerId===TK.holdId)letGo('pointerup')});
const onMic=e=>e.target.closest&&e.target.closest('[data-mic]');  // a touch event's target is where that finger went down
document.addEventListener('pointercancel',e=>{if(e.pointerId===TK.holdId&&e.pointerType!=='touch'){TK.hold=false;talkNext()}});  // a pen or mouse has no touchend
document.addEventListener('touchend',e=>{if(onMic(e)&&!(e.targetTouches&&e.targetTouches.length))letGo('touchend')},{passive:true});
/* B166: Hold's release is a tap that lets the page play sound; which of its events the browser takes for one differs, so
   each tries until one played. Not in Tap: its touchend comes before the mic's start (B132) */
for(const t of ['touchend','click'])document.addEventListener(t,e=>{if(TS.mic==='hold'&&!TK.hold&&onMic(e))unlockAudio()},{passive:true});
document.addEventListener('touchcancel',e=>{if(onMic(e)){TK.hold=false;talkNext()}},{passive:true});
document.addEventListener('contextmenu',e=>{if(e.target.closest&&e.target.closest('[data-mic]'))e.preventDefault()});
/* F124: a swipe right anywhere opens the sidebar drawer and a swipe left closes it, following the finger;
   a swipe down closes the sheet. B167: a touch is one thing until the finger lifts: one that scrolled never becomes a
   swipe, and a drawer swipe keeps the page from scrolling (so touchmove is not passive). Not from a text box, a sideways scroller, a held mic, a row being dragged or
   a mostly vertical move; Safari keeps its own back swipe at the very edge. */
let SW=null;
/* F147: a panel goes on from where the finger left it, with its speed; .drag stays on (no transition) until it is there */
function runStop(el){  // from where it is, the stylesheet's transition takes it on (or a finger)
  const a=el&&el._run;if(!a)return;
  const c=getComputedStyle(el), st={transform:c.transform,opacity:c.opacity}, p=el===$('scrim')?'opacity':'transform';
  el.style[p]=st[p];el._run=null;a.cancel();void el.offsetWidth;el.classList.remove('drag');el.style[p]='';
  if(el===$('side'))runStop($('scrim'));
}
function springRun(el,frames,css){
  const done=()=>{el._run=null;el.classList.remove('drag')};
  if(!el.animate||calm())return done();
  const a=el._run=el.animate(frames.map(css),{duration:(frames.length-1)*16,easing:'linear'});a.onfinish=a.oncancel=()=>{if(el._run===a)done()};
}
/* where a panel is now (it may still be on its way), and the finger has it */
function grab(el,axis,rest){let at=rest;try{at=shiftOf(el)[axis]}catch(e){}runStop(el);return at}
const sideways=el=>{for(;el&&el!==document.body;el=el.parentElement)if(el.scrollWidth>el.clientWidth+1&&/(auto|scroll)/.test(getComputedStyle(el).overflowX))return true;return false};
/* B167: what a touch could scroll, and did it: a change of height is the page's own scroll (a chat's new message) */
const scrollers=el=>{const a=[];for(;el&&el!==document.body;el=el.parentElement)if(el.scrollHeight>el.clientHeight+1)a.push([el,el.scrollTop,el.scrollHeight]);return a};
const scrolled=a=>a.some(s=>{const [el,top,h]=s;if(el.scrollHeight===h)return el.scrollTop!==top;s[1]=el.scrollTop;s[2]=el.scrollHeight;return false});
const drawerOn=()=>{const m=document.querySelector('.top .menu');return !!(m&&m.offsetParent)};
document.addEventListener('touchstart',e=>{
  if(SW&&SW.on&&!SW.sheet){if(e.touches.length>1)return;swipeEnd(false)}  // B167: a second finger does not end the lock
  SW=null;const t=e.touches[0], el=e.target;
  if(e.touches.length!==1||!el.closest||el.closest('input,textarea,select,[contenteditable],iframe,.obpop,.cview,.mic.hold')||DR&&DR.on)return;
  if(S.sheet){if(el.closest('#sheet')&&$('sheet').scrollTop<=0)SW={sheet:true,x:t.clientX,y:t.clientY,at:e.timeStamp,d:0,on:false,ly:t.clientY,lt:e.timeStamp,v:0,base:0};return}
  if(!drawerOn()||el.closest('#body,#dock')&&sideways(el))return;
  SW={x:t.clientX,y:t.clientY,at:e.timeStamp,d:0,on:false,open:S.drawer,w:$('side').offsetWidth||280,lx:t.clientX,lt:e.timeStamp,v:0,id:t.identifier,scr:scrollers(el)};
},{passive:true});
document.addEventListener('touchmove',e=>{
  if(!SW)return;
  const t=SW.on&&[...e.touches].find(f=>f.identifier===SW.id)||e.touches[0], dx=t.clientX-SW.x, dy=t.clientY-SW.y;
  if(DR&&DR.ready&&DR.hold){if(SW.on)swipeEnd(false);SW=null;return}  // the row is held: it is being dragged
  if(SW.sheet){
    if(!SW.on){if(Math.abs(dy)<10&&Math.abs(dx)<10)return;if(dy<Math.abs(dx)||$('sheet').scrollTop>0){SW=null;return}SW.on=true;SW.base=Math.max(0,grab($('sheet'),'m42',0));$('sheet').classList.add('drag')}
    if(e.timeStamp>SW.lt){SW.v=(t.clientY-SW.ly)/(e.timeStamp-SW.lt);SW.ly=t.clientY;SW.lt=e.timeStamp}
    SW.d=Math.max(0,SW.base+dy);$('sheet').style.transform=`translateY(${SW.d}px)`;return;
  }
  if(!SW.on&&!SW.lvl){if(!e.cancelable||scrolled(SW.scr)){SW=null;return}  // B167: it is a scroll
    if(SW.open&&HB&&!atAll()&&!oneProject(H.projects)&&swipeTakes(dx,dy,false)==='drag'){SW.lvl=true;if(DR)dragEnd()}  // F150: up a level
    else{const s=swipeTakes(dx,dy,SW.open);if(s==='wait')return;if(!s){SW=null;return}
    SW.on=true;if(DR)dragEnd();SW.base=Math.max(-SW.w,grab($('side'),'m41',SW.open?0:-SW.w));$('side').classList.add('drag');$('scrim').classList.add('drag','on')}}
  if(e.cancelable)e.preventDefault();  // B167: no scroll until the finger lifts
  SW.d=dx;if(SW.lvl)return;
  if(e.timeStamp>SW.lt){SW.v=(t.clientX-SW.lx)/(e.timeStamp-SW.lt);SW.lx=t.clientX;SW.lt=e.timeStamp}
  const at=SW.px=Math.max(-SW.w,Math.min(0,SW.base+dx));
  $('side').style.transform=`translateX(${at}px)`;$('scrim').style.opacity=String(1+at/SW.w);
},{passive:false});
function swipeEnd(done){
  const w=SW;SW=null;if(w&&w.lvl){noClick=true;setTimeout(()=>noClick=false,50);PD.down=false;if(done&&w.d>48)goUp();return}
  if(!w||!w.on)return;
  const still=performance.now()-w.lt>120, v=still?0:w.v;  // it rested before it was let go
  if(w.sheet){const el=$('sheet'), go=done&&(w.d>80||v>.5&&w.d>10);el.style.transform='';
    if(go)closeSheet();
    if(drawerOn())springRun(el,springFrames(w.d,go?el.offsetHeight*1.03:0,v).map(x=>Math.max(0,x)),x=>({transform:`translateY(${x}px)`}));else el.classList.remove('drag');
    return}
  const side=$('side'), scrim=$('scrim');side.style.transform='';scrim.style.opacity='';
  S.drawer=done?swipeOpens(w.d,v,w.w,w.open):w.open;
  noClick=true;setTimeout(()=>noClick=false,50);PD.down=false;render(true);
  const fs=springFrames(w.px||0,S.drawer?0:-w.w,v).map(x=>Math.max(-w.w,Math.min(0,x)));side._to=S.drawer;
  springRun(side,fs,x=>({transform:`translateX(${x}px)`}));springRun(scrim,fs,x=>({opacity:1+x/w.w}));
}
document.addEventListener('touchend',e=>{if(SW&&SW.on&&!SW.sheet&&[...e.touches].some(f=>f.identifier===SW.id))return;swipeEnd(true)},{passive:true});
document.addEventListener('touchcancel',()=>swipeEnd(false),{passive:true});
/* F150: switching draws the project's last snapshot at once. One is kept per project, the last SNAPS of them, each up to
   SNAP_MAX characters (the rest of this browser's room is the outbox's) */
const SNAP='ar-snap:', SNAPS=6, SNAP_MAX=200000;
function snapKeep(){
  if(HOME_PAGE||!HKEY||!S.snap.at)return;
  const text=JSON.stringify(snapKept(S.snap));if(text.length>SNAP_MAX){store.set(SNAP+HKEY,'');return}
  let l;try{l=JSON.parse(store.get(SNAP+'@')||'[]')}catch(e){}
  l=[HKEY,...(Array.isArray(l)?l:[]).filter(k=>k!==HKEY)];
  for(const k of l.slice(SNAPS))store.set(SNAP+k,'');
  store.set(SNAP+'@',JSON.stringify(l.slice(0,SNAPS)));store.set(SNAP+HKEY,text);
}
function snapTake(){
  if(HOME_PAGE||!HKEY)return;
  let s;try{s=JSON.parse(store.get(SNAP+HKEY)||'null')}catch(e){}
  if(s&&typeof s==='object'&&['status','sessions','queue','needs','concepts','log'].every(k=>Array.isArray(s[k])))S.snap={...S.snap,...s};
}
addEventListener('pagehide',snapKeep);
document.addEventListener('visibilitychange',()=>{if(document.hidden)snapKeep()});
addEventListener('pagehide',finalDelete);  // F118: leaving the page makes a pending delete final

projectsKept();snapTake();H.tab=tabStore.get('ar-alltab');  // F150: what was last seen draws at once
takePlace();  // B177: before the first draw
takeTyped();  // F149
render(true);
if(HOME_PAGE){  // F134: Home's own page: no run behind it, only Home's projects and devices
  loadProjects();loadDevices();homeDrain();setInterval(loadProjects,HKEY?2500:5000);setInterval(loadDevices,30000);
}else{
connect();
placeLoad();  // B177
drain();  // F137: what a reload left in the outbox goes now (the run page runs each cid once)
if(HB){loadProjects();homeDrain();let tick=0;  // F134: every 5 s while All projects shows, else every 30 s
  setInterval(()=>{if(atAll()||++tick%6===0)loadProjects()},5000);
  setInterval(()=>{if(atAll())loadDevices()},30000);loadDevices()}
}
/* B179: a concept's page in the Home Screen app, where a new tab would be iOS's browser over the app */
function conceptOpen(src,title){
  const el=$('cview');
  el.innerHTML=`<div class="top"><button class="icon" data-cviewclose aria-label="Back" title="Back">${I.back}</button><b class="ell">${esc(title)}</b></div><iframe src="${esc(src)}" sandbox="allow-scripts" title="${esc(title)}"></iframe>`;
  el.hidden=false;el.querySelector('button').focus({preventScroll:true});
}
function conceptClose(){const el=$('cview');el.hidden=true;el.innerHTML=''}
document.addEventListener('click',e=>{
  if(e.target.closest('[data-cviewclose]')){conceptClose();return}
  const a=ON_HOME_SCREEN&&e.target.closest('a[target="_blank"]'), k=a?appLink(a.href,location.origin,ROOT):'';
  if(!k)return;
  e.preventDefault();
  if(k==='concept'){const q=a.closest('.card')&&a.closest('.card').querySelector('.q');conceptOpen(a.href,q?q.textContent:'Concept')}
  else location.href=a.href;
});
/* Esc closes the topmost thing only */
window.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('cview').hidden===false){e.preventDefault();e.stopImmediatePropagation();conceptClose()}},true);
