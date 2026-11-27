/* --- F150: Home's actions (start, pause, slots, stop): an outbox of their own, shared by every page of this Home, so one
   started before a switch to another project is still followed there. Home runs each cid once, so any tab may send it */
const HO_KEY='ar-outbox:@home', HO={busy:new Set(),kept:true,timer:0,wait:2000};
S.hob=HB?obParse(store.get(HO_KEY)):[];
function homeLoad(){if(HB&&HO.kept)S.hob=obParse(store.get(HO_KEY))}
function homeChange(fn){homeLoad();S.hob=fn(S.hob);const t=S.hob.length?JSON.stringify(S.hob):'';store.set(HO_KEY,t);HO.kept=store.get(HO_KEY)===t}
function homeAct(key,name,arg,say){
  homeChange(b=>obAdd(b.filter(x=>!(x.state==='failed'&&x.args.project===key&&x.name===name)),{cid:newCid(),name,args:{project:key,...(arg?{arg:String(arg)}:{})},state:'sending',err:'',at:Date.now(),say}));
  render(true);homeDrain();
}
/* one at a time per project; a start, which is slow, holds up no other project */
function homeDrain(){clearTimeout(HO.timer);homeLoad();for(const k of new Set(S.hob.map(x=>x.args.project)))homeSend(k)}
async function homeSend(key){
  if(HO.busy.has(key))return;HO.busy.add(key);
  try{
    for(let it;homeLoad(),(it=obNext(S.hob.filter(x=>x.args.project===key)));){
      let j;
      try{const r=await fetch(tq(HB+'act'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...it.args,name:it.name,cid:it.cid})});
        if(r.status>=500)throw new Error(`HTTP ${r.status}`);
        j=await r.json()}
      catch(e){HO.timer=setTimeout(homeDrain,HO.wait);HO.wait=Math.min(HO.wait*2,30000);obDraw();return}
      HO.wait=2000;homeLoad();
      if(!S.hob.some(x=>x.cid===it.cid))continue;  // discarded while it went
      homeChange(b=>obSettle(b,it.cid,j,''));
      homeDone(it,j);
    }
  }finally{HO.busy.delete(key)}
  render(true);
}
function homeDone(it,j){
  const key=it.args.project;
  if(!j||!j.ok){toast(homeSaid(it.name,it.args.arg,it.say,j),true);return}
  if(it.name==='start')H.begun[key]=Date.now();else if(it.name==='stop')delete H.begun[key];
  H.turn++;  // a list asked for before this is older than it
  H.projects=H.projects&&H.projects.map(p=>p.key===key?projectDid(p,it.name,it.args.arg):p);
  const p0=(H.projects||[]).find(p=>p.key===key), said=homeSaid(it.name,it.args.arg,it.say,j,p0&&p0.slots);if(said)toast(said);  // B851c: no raw output; none when the card shows it
  loadProjects();
}
const homeHas=cid=>S.hob.some(x=>x.cid===cid);
function homeRetry(cid){homeChange(b=>obRetry(b,cid,newCid(),''));render(true);homeDrain()}
addEventListener('storage',e=>{if(e.key===HO_KEY){homeLoad();render(true)}});
addEventListener('online',()=>homeDrain());
/* --- F150: Runner Home in the app (option D of K7's page): All projects is the sidebar's first row; tapping it turns the
   sidebar into the project list and the main page into the Overview; a project turns it back. The level is the view */
const homeNeeds=()=>needsOf(H.projects);
const projectsNow=()=>(H.projects||[]).map(p=>projectNow(H.begun[p.key]&&(p.state||'off')==='off'&&Date.now()-H.begun[p.key]<START_MS?{...p,starting:true}:p,S.hob));
const START_MS=90000;  // how long a run that was started reads as starting
const atAll=()=>S.view==='projects'&&!S.thread;
/* the view last open in this tab ('' in a chat): what goDown falls back on. A switch to another project opens its Home (F203) */
const TAB_KEY='ar-tab', LEVEL_KEY='ar-level';
const lastTab=()=>{const v=tabStore.get(TAB_KEY);return NAV.some(n=>n[0]===v)?v:''};
const rowsNow=()=>switcherRows(projectsNow(),HKEY,HB,T);
const projectHref=key=>projectHome(HB,key,T);
/* the list's level or the project's, drawn, and slid when it is another one than before */
let level='';
function sideShow(h,to){
  const el=$('side'), was=level, calm=matchMedia('(prefers-reduced-motion:reduce)').matches;
  if(was!==to){
    if(!was&&to==='in'&&tabStore.get(LEVEL_KEY)==='all'&&HB&&H.projects&&!oneProject(H.projects)){sideHTML(allSide(),true);level='all';return sideShow(h,to)}  // it came from another page's list
    level=to;tabStore.set(LEVEL_KEY,to);
    for(const g of el.querySelectorAll('.sghost'))g.remove();
    el.classList.remove('up');
    if(was&&!calm){
      const g=$('sidein').cloneNode(true);g.removeAttribute('id');g.classList.add('sghost');g.setAttribute('aria-hidden','true');g.inert=true;g.style.top=-el.scrollTop+'px';
      for(const x of g.querySelectorAll('[id]'))x.removeAttribute('id');
      el.appendChild(g);if(to==='in')g.classList.add('out');else el.classList.add('up');
      g.addEventListener('animationend',()=>g.remove());$('sidein').addEventListener('animationend',()=>{g.remove();el.classList.remove('up')},{once:true});
      setTimeout(()=>{g.remove();if(level===to)el.classList.remove('up')},400);
    }
    scrollStop(el);
    if(was==='in')S.sideAt=el.scrollTop;
    sideHTML(h,true);el.scrollTop=to==='in'?S.sideAt||0:0;
  }else sideHTML(h);
  if(el._run&&el._to!==S.drawer&&!SW)runStop(el);
  el.classList.toggle('open',S.drawer);$('scrim').classList.toggle('on',S.drawer);
}
const meRow=(name,sub)=>`<div class="me"><div class="av">${esc((name||'?').charAt(0).toUpperCase())}</div><div class="grow"><span class="ell">${esc(name||'this machine')}</span><div class="sub">${sub}</div></div></div>`;
/* a project's level starts with the way up: its count is what needs you in the other projects */
function allRow(){
  if(!HB||oneProject(H.projects))return brand();
  const n=needsOf(H.projects,HKEY)+H.alerts.length, cur=(H.projects||[]).find(p=>p.key===HKEY);
  return `<button class="ni allp" data-up title="All projects">${I.back}All projects${n?`<span class="n" data-k="n:all" data-roll data-v="${n}" title="need you in other projects">${n}</span>`:''}</button>${H.opening&&H.opening!==HKEY?`<div class="slevel opening"><span class="livedot"></span> Opening ${esc((projectOf(H.opening)||{}).name||H.opening)}…</div>`:`<div class="slevel">${esc(cur&&cur.name||S.snap.project||HKEY)}</div>`}`;
}
function allSide(){
  const rows=rowsNow(), n=homeNeeds()+H.alerts.length;let i=0;
  const row=r=>{const k=++i, opens=H.opening===r.key, hint=k<10?` title="Alt+${k}"`:'';
    return `<a class="prow ${r.on?'on ':''}${opens?'opening ':''}${r.group}" href="${esc(r.href)}" data-pkey="${esc(r.key)}" data-k="p:${esc(r.key)}"${hint}><span class="pdot ${esc(r.group)}"></span><span class="t">${esc(r.name)}</span>${opens?`<span class="st">${OPENING}</span>`:['running','idle','off'].includes(r.said)?'':`<span class="st">${esc(r.said)}</span>`}${r.needs?`<span class="n" data-k="n:p:${esc(r.key)}" data-roll data-v="${r.needs}" title="needs you">${r.needs}</span>`:''}</a>`};
  return `<div class="slevel">All projects</div><div class="nav"><button class="ni ${H.tab!=='devices'?'on':''}" data-alltab="">${I.projects}Overview${n?`<span class="n" data-k="n:over" data-roll data-v="${n}">${n}</span>`:''}</button></div>
    <div class="plist">${H.projects===null?'<div class="none">Loading…</div>':PGROUPS.map(([g,label])=>{const rs=rows.filter(r=>r.group===g);return rs.length?`<div class="shead">${label}</div>${rs.map(row).join('')}`:''}).join('')||'<div class="none">No projects</div>'}</div>
    <div class="nav"><button class="ni ${H.tab==='devices'?'on':''}" data-alltab="devices">${I.tools}Devices</button></div>${meRow(H.machine,'Runner Home')}`;
}
/* a project with no run up: its name and state, the way up, and nothing of a run */
function offSide(){const p=projectOf(HKEY);
  return `${allRow()}<div class="nav"><button class="ni on" data-view="home">${I.home}${p?esc(projectState(p)).replace(/^./,c=>c.toUpperCase()):'Project'}</button></div>${walkRow()}${meRow(H.machine,'Runner Home')}`}
const projectOf=key=>projectsNow().find(p=>p.key===key);
/* up to the list, with Back to come down again (the drawer stays open), and down to the open project where it was left */
function goUp(stay,keys){
  if(atAll()||!HB||oneProject(H.projects))return;
  S.below={v:S.view,t:S.thread,c:S.ctx};H.tab='';tabStore.set('ar-alltab','');devSet('');
  if(!stay)try{history.pushState({level:'all'},'')}catch(e){}
  const open=S.drawer;goView('projects');if(open){S.drawer=true;render(true)}
  if(keys)focusSide('[data-alltab]');
  loadProjects();loadDevices();
}
function goDown(stay,keys){
  if(!atAll()||!HKEY)return;
  const p=!HOME_PAGE&&!stay&&projectOf(HKEY);if(p&&projectGroup(p)==='off'&&!p.starting&&!p.page){openProject(HKEY,projectLink(HB,HKEY,T));return}  // its run ended meanwhile and nothing serves its page (F402b2): its page as it is off
  const b=S.below||{v:lastTab()||'home',t:null,c:null};S.below=null;
  if(!stay)try{history.pushState({level:'in'},'')}catch(e){}
  if(b.t){S.view=viewOf(b.v);S.ctx=b.c;open(b.t)}else goView(b.v==='projects'?'home':b.v);
  if(keys)focusSide('[data-up]');
}
function focusSide(s){const el=$('sidein').querySelector(s);if(el)el.focus({preventScroll:true})}
addEventListener('popstate',e=>{if(e.state&&e.state.level==='all'){goUp(true);devPlace(e.state)}else if(atAll())goDown(true)});
function goProject(r){if(r.on)atAll()?goDown():0;else openProject(r.key,r.href)}
/* B769b: a pressed project is marked as opening at once, until its page comes. A load that fails without leaving this page
   says so only where there is a Navigation API, so the mark also goes after OPEN_MS; navigateerror of a load that a newer
   press replaced comes while that press starts its own */
const OPEN_MS=20000, OP={timer:0,going:false,said:''};
function openProject(key,href){
  openingHush();clearTimeout(OP.timer);H.opening=key;OP.timer=setTimeout(openingEnd,OPEN_MS);
  render(true);
  if(!openingSeen()){const p=projectOf(key);toast(OP.said=`Opening ${p&&p.name||key}…`);clearTimeout(toast.h)}  // it stays as long as the mark
  OP.going=true;try{location.href=href}finally{setTimeout(()=>{OP.going=false},0)}
}
function openingHush(){if(OP.said&&$('toast').textContent===OP.said)$('toast').hidden=true;OP.said=''}
function openingEnd(){clearTimeout(OP.timer);openingHush();if(!H.opening)return;H.opening='';render(true)}
/* the mark is on screen: a number key also opens a project from where no row or card of it shows */
const openingSeen=()=>[...document.querySelectorAll('.opening')].some(el=>{const b=el.getBoundingClientRect();return b.width>0&&b.right>0&&b.left<innerWidth&&b.bottom>0&&b.top<innerHeight});
const OPENING='<span class="livedot"></span> Opening…';
addEventListener('pageshow',openingEnd);
if(window.navigation&&navigation.addEventListener)navigation.addEventListener('navigateerror',()=>{if(!OP.going)openingEnd()});
/* B153: the run's own page top-left: the project's name, a link to Runner Home when it is installed */
function brand(){const href=homeHref(HB,T,S.snap.home,location), inner=`<div class="logo">${esc(PN().charAt(0).toLowerCase())}</div><b>${esc(PN())}</b>`;
  return href?`<a class="brand" href="${esc(href)}" title="Runner Home: every project's run">${inner}</a>`:`<div class="brand">${inner}</div>`}
function meterHTML(m){const pct=Math.max(0,Math.min(100,+m.pct||0)), c=pct>=90?'b':pct>=75?'w':'';
  return `<div class="meter"><span>${esc(m.name)}</span><div class="bar"><i class="${c}" style="width:${pct}%"></i></div><span class="r">${esc(m.said)}</span></div>`}
const hobOf=(key)=>(S.hob||[]).filter(x=>x.args.project===key&&x.state==='failed').map(x=>`<div class="row obstand failed" data-k="ob:${esc(x.cid)}"><div class="grow"><div>${esc(x.say)}</div><div class="small">Not done: ${esc(x.err||'it did not work')}</div></div><div class="btns">${obBtns(x)}</div></div>`).join('');
function mainBtn(p){const b=projectMain(p);
  return !b?'':b.open?`<a class="btn${H.opening===p.key?' busy':''}" href="${esc(projectHref(p.key))}" data-pkey="${esc(p.key)}">Open</a>`:`<button class="btn${b.busy?' busy':' pri'}" ${b.busy?'disabled':''} data-pact="${b.a}" data-pkey="${esc(p.key)}">${b.label}</button>`}
const dotsBtn=p=>`<button class="btn" data-projmore="${esc(p.key)}" aria-label="More for ${esc(p.name||p.key)}" title="More">…</button>`;
function landedLine(p){const l=p.landed||[], n=p.landed_n||l.length;return n?`<div class="ptasks small"><div>Landed today · ${n}</div>${l.map(x=>`<div class="ell">${esc(x)}</div>`).join('')}</div>`:''}
/* the project's warnings: no settings found, a wrong [run] agent */
const projectWarn=p=>[p.no_settings,p.agent_problem].filter(Boolean).map(w=>`<div class="small"><span class="v-warn">${esc(w)}</span></div>`).join('');
function projectCard(p){
  const off=projectGroup(p)==='off', opens=H.opening===p.key, words=opens?OPENING:esc(projectWords(p)), tasks=p.running||[], name=`<a class="pname grow ell" href="${esc(projectHref(p.key))}" data-pkey="${esc(p.key)}">${esc(p.name||p.key)}</a>`;
  const warn=projectWarn(p);
  return card(`<div class="row"><span class="pdot ${projectGroup(p)}"></span>${name}${off&&(p.left||opens)?`<span class="small">${words}</span>`:''}${mainBtn(p)}${dotsBtn(p)}</div>${off?'':
    `${tasks.length?`<div class="ptasks">${tasks.map(id=>`<div class="ell" title="${esc(id)}">${esc((p.titles||{})[id]||id)}</div>`).join('')}</div>`:''}<div class="small">${words}</div>${landedLine(p)}`}${warn}${hobOf(p.key)}`,
    `pcard tap${off?' off':''}${opens?' opening':''}`,`data-pgo="${esc(projectHref(p.key))}" data-pkey="${esc(p.key)}" data-k="proj:${esc(p.key)}" data-v="${esc(projectState(p))}"`);
}
/* a thing that waits on the person, in any project: it opens there */
function askRow(a){const here=a.key===HKEY&&!HOME_PAGE;
  return card(`<div class="row"><div class="grow"><b class="ell2">${esc(a.what)}</b><div class="small">${esc(a.name)}${a.id?` · ${esc(a.id)}`:''}</div></div><a class="btn" href="${esc(projectLink(HB,a.key,T)+('#'+(a.id?'need-'+a.id:'home')))}"${here?` data-askhere="${esc(a.id)}"`:''}>Open</a></div>`,'need',`data-k="ask:${esc(a.key)}:${esc(a.id||a.what)}"`)}
function deviceCard(d){const v=d.verdict||{};
  return card(`<div class="row"><div class="grow"><b>${esc(d.host)}</b>${d.here?' <span class="small">· this one</span>':''}${devVerdict(v)}</div></div>${(d.meters||[]).map(meterHTML).join('')}`,
    'tap devcard',`tabindex="0" role="button" data-devopen="${esc(d.id)}" data-k="device:${esc(d.id)}"`);
}
const ASKS_SHOWN=3;
const homeErr=()=>H.err?card(`<div class="small"><span class="v-bad">${esc(H.err)}</span></div><div class="btns"><button class="btn" data-pload>Retry</button></div>`):'';
function devicesHTML(){const ds=H.devices;
  return `<div class="col">${homeErr()}${ds===null?emptyCard('Loading…'):ds.length?ds.map(deviceCard).join(''):emptyCard('No devices.')}</div>`}
function projectsHTML(){
  if(HOME_PAGE&&!atAll())return offHTML();
  if(H.tab==='devices')return devOn()?devHTML():devicesHTML();
  const ps=projectsNow(), asks=projectAsks(ps), total=homeNeeds()+H.alerts.length;
  const alerts=H.alerts.map(a=>card(`<div class="row"><div class="who">${I.alert}</div><div class="grow">${esc(a.what)}</div>${a.clean?`<button class="btn acc" data-devopen="${esc(a.device)}">Clean</button>`:''}</div>`,'need')).join('');
  const more=asks.length-ASKS_SHOWN, all=H.more?PGROUPS.length&&projectOrder(ps).filter(p=>(p.asks||[]).length).map(p=>`<div class="qline" data-k="pname:${esc(p.key)}">${esc(p.name||p.key)}</div>${projectAsks([p]).map(askRow).join('')}`).join(''):asks.slice(0,ASKS_SHOWN).map(askRow).join('');
  const needs=`<div class="sec">Needs you${total?` · <span data-k="n:sec" data-roll data-v="${total}">${total}</span>`:''}<span class="ln"></span></div>${alerts}${all}${more>0?`<div data-k="pmore"><button class="btn" data-pmore aria-expanded="${H.more}">${H.more?'Show fewer':`Show ${more} more, by project`}</button></div>`:''}${total?'':emptyCard('Nothing needs you.')}`;
  const groups=PGROUPS.map(([g,label])=>{const l=projectOrder(ps).filter(p=>projectGroup(p)===g);return l.length?`<div class="sec">${label}<span class="ln"></span></div>${l.map(projectCard).join('')}`:''}).join('');
  return `<div class="col">${homeErr()}${H.projects===null?(H.err?'':emptyCard('Loading…')):needs+(groups||exampleOffer({busy:EX.busy,err:esc(EX.err)}))}</div>`;
}
/* a project with no run up, on its own page: what it has, and Start run; it turns into its app once up */
function offHTML(){
  const p=projectOf(HKEY), asks=p?projectAsks([p]):[], qs=p&&p.queue||[];
  if(!p)return `<div class="col">${homeErr()||emptyCard(H.projects===null?'Loading…':'Runner Home does not list this project.')}</div>`;
  const up=p.state&&p.state!=='off', more=(p.left||0)-qs.length;
  const said=up?'Its run is up and its page is on its way.':p.starting?'Starting its run. This page turns into its app once it is up.':'No run is up.';
  return `<div class="col">${homeErr()}${card(`<div class="row"><div class="grow"><b>${esc(p.name||p.key)}</b><div class="small">${p.starting?'<span class="livedot"></span> ':''}${said}</div></div>${up?'':mainBtn(p)}${dotsBtn(p)}</div>${projectWarn(p)}${landedLine(p)}${hobOf(p.key)}`,'pcard',`data-k="proj:${esc(p.key)}" data-v="${esc(projectState(p))}"`)}
    <div class="sec">Needs you${p.needs?` · <span data-k="n:sec" data-roll data-v="${p.needs}">${p.needs}</span>`:''}<span class="ln"></span></div>${asks.length?asks.map(a=>card(`<b class="ell2">${esc(a.what)}</b><div class="small">${esc(a.id)}${a.id?' · ':''}answer it once the run is up</div>`,'need',`data-k="ask:${esc(a.key)}:${esc(a.id||a.what)}"`)).join(''):emptyCard('Nothing needs you.')}
    <div class="sec">Queue${p.left?` · <span data-k="n:queue" data-roll data-v="${p.left}">${p.left}</span>`:''}<span class="ln"></span></div>${qs.length?card(qs.map(q=>`<div class="lrow" data-k="pq:${esc(q.id)}"><span>${esc(q.title)}</span><span class="small">${esc(q.id)}</span></div>`).join(''),'','data-k="pq"')+(more>0?`<div class="small">and ${more} more</div>`:''):emptyCard(p.left?'Nothing in it can start by itself.':'The queue is empty.')}</div>`;
}
/* its run came up: the page is its app now, at the same address. Not while something is open on it */
function turnIntoApp(){
  const p=HOME_PAGE&&HKEY&&!atAll()&&projectOf(HKEY);
  if(!p||!p.page||S.sheet||Date.now()-Number(tabStore.get('ar-turned'))<8000)return;
  tabStore.set('ar-turned',String(Date.now()));location.reload();
}
const PCACHE='ar-projects';
function projectsKept(){let o;try{o=JSON.parse(store.get(PCACHE)||'null')}catch(e){}
  if(HB&&o&&Array.isArray(o.projects)){H.projects=o.projects.filter(p=>p&&typeof p.key==='string');H.machine=String(o.machine||'')}}
async function loadProjects(){
  if(!HB||H.busy)return;H.busy=true;const turn=H.turn;
  try{const d=await (await fetch(tq(HB+'projects'))).json();
    if(d.ok){if(HOME_PAGE){S.snap.page=d.page;S.snap.restart_needed=d.restart_needed}  // F149
      H.err='';H.login=d.claude_login||'';  // F126a
      if(turn===H.turn){H.projects=d.projects||[];H.machine=d.machine||'';store.set(PCACHE,JSON.stringify({projects:H.projects,machine:H.machine}))
        for(const p of H.projects)if((p.state||'off')!=='off')delete H.begun[p.key]}
      if(HOME_PAGE)document.title=HKEY?pageTitle((projectOf(HKEY)||{}).name||HKEY):(H.machine?H.machine+' · ':'')+'Runner Home'}else H.err=d.out||'The projects could not be read.'}
  catch(e){H.err=`Could not reach Runner Home: ${plainErr(e)}`}
  H.busy=false;render();S.live=S.live||HOME_PAGE;turnIntoApp();
  if(turn!==H.turn)loadProjects();  // an action settled meanwhile
}
async function loadDevices(){
  if(!HB)return;
  try{const d=await (await fetch(tq(HB+'devices'))).json();if(d.ok){H.devices=d.devices||[];H.alerts=d.needs||[]}}catch(e){}
  render();
}
async function homePost(path,body){
  let d;
  try{d=await (await fetch(tq(HB+path),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json()}
  catch(e){d={ok:false,out:`Could not reach Runner Home: ${plainErr(e)}`}}
  H.turn++;loadProjects();return d;
}
async function addProject(){
  const path=String(S.f.padd||'').trim();if(!path)return;
  H.said='';H.adding=true;render(true);
  const d=await homePost('add',{path});H.adding=false;
  if(d.ok){delete S.f.padd;if(S.sheet==='addproject')closeSheet();toast(d.out||'Added')}else{H.said=d.out||'It was not added';render(true)}
}
/* F118: a chat row: its delete button, dimmed with Undo in that spot once deleted; the Delete N bar */
/* --- B832: a live chat's DECIDE question under Home's Needs you, at once, before the run files it (snapshot `chat_needs`).
   An option waits out QUESTION_HOLD with Undo, then goes to the chat as the question card sends it; typed words go as a
   message; Chat opens the chat. CN.held: chat -> {id, name, timer}; CN.sent: question key -> {cid, out (when it left the
   outbox)}: kept off while its message is in the outbox and QUESTION_LAND after, by when the snapshot knows; one that failed
   there is back at once */
const CN={held:new Map(),sent:new Map()};
const chatNeedKey=c=>c.chat+' '+c.id;
function chatNeedOff(s){
  const it=(S.ob||[]).find(x=>x.cid===s.cid);if(it)return it.state!=='failed';
  s.out=s.out||Date.now();return Date.now()-s.out<QUESTION_LAND;
}
function chatNeedsShown(){
  const all=(S.snap&&S.snap.chat_needs)||[], keys=new Set(all.map(chatNeedKey));
  for(const k of CN.sent.keys())if(!keys.has(k))CN.sent.delete(k);
  return all.filter(c=>{const s=CN.sent.get(chatNeedKey(c));return !(s&&chatNeedOff(s))});
}
function chatNeedCard(c){
  const k=chatNeedKey(c), h=CN.held.get(c.chat), held=h&&h.id===c.id, f='cnsay:'+c.chat;
  const top=`<div class="row"><div class="grow"><b class="ell2">${esc(c.question)}</b><div class="small">${esc(c.title)}${c.at?` · ${esc(agoWords(c.at*1000,' ago'))}`:''}</div></div><button class="btn" data-thread="${esc(c.chat)}">Chat</button></div>`;
  const body=held?`<div class="row" role="status"><span class="grow">Sending “${esc(h.name)}”</span><button type="button" class="btn" data-cnundo="${esc(c.chat)}">Undo</button></div>`
    :`${c.options.length?`<div class="btns">${c.options.map((o,i)=>`<button type="button" class="btn${o.rec?' pri':''}" data-cnpick="${i}" data-cnchat="${esc(c.chat)}" data-cnid="${esc(c.id)}">${esc(questionLabel(o))}</button>`).join('')}</div>`:''}<form class="row" data-cnform="${esc(c.chat)}"><input class="fld grow" data-f="${esc(f)}" value="${esc(S.f[f]||'')}" placeholder="Answer in your words" aria-label="Answer in your words" enterkeyhint="send"><button class="btn">Send</button></form>`;
  return card(top+body,'need',`data-k="chatneed:${esc(k)}" data-v="${held?'held':''}"`);
}
function chatNeedSend(n,text,say){
  const it=outbox('chat_to',{text,to:n},{text,key:n,say:`To ${threadTitle(n)}: ${text}`});
  CN.sent.set(say,{cid:it&&it.cid,out:0});
}
function chatNeedPick(n,id,i){
  const c=chatNeedsShown().find(x=>x.chat===n&&x.id===id), o=c&&c.options[i];if(!o||CN.held.has(n))return;
  const h={id,name:o.name};h.timer=setTimeout(()=>{if(CN.held.get(n)!==h)return;CN.held.delete(n);chatNeedSend(n,h.name,chatNeedKey(c));render(true)},QUESTION_HOLD);
  CN.held.set(n,h);render(true);
}
function chatNeedUndo(n){const h=CN.held.get(n);if(!h)return;clearTimeout(h.timer);CN.held.delete(n);render(true)}
const chatNeedOn=(k,f)=>document.addEventListener(k,f);  // before 183-click.js's, so it can stop them
chatNeedOn('click',e=>{const x=e.target.closest('[data-cnpick],[data-cnundo]');if(!x)return;e.stopImmediatePropagation();
  if(x.dataset.cnundo)chatNeedUndo(x.dataset.cnundo);else chatNeedPick(x.dataset.cnchat,x.dataset.cnid,+x.dataset.cnpick)});
chatNeedOn('submit',e=>{const n=e.target.dataset&&e.target.dataset.cnform;if(!n)return;e.preventDefault();e.stopImmediatePropagation();
  const f='cnsay:'+n, text=String(S.f[f]||'').trim(), c=chatNeedsShown().find(x=>x.chat===n);if(!text||!c)return;
  delete S.f[f];chatNeedSend(n,text,chatNeedKey(c));render(true)});
/* F197b3: a concept's details popup opened (from Home's Needs you card or its Concepts row): New and Updated clear here at
   once and, quietly, for every device; a failure only leaves the badge for the next snapshot */
function conceptOpened(id){const a=conceptSeen(id,S.snap.concepts);if(!a)return;
  for(const c of S.snap.concepts||[])if((c.concept||c.id)===a.concept){c.news='';c.news_words=''}
  fetch(tq('act'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'concept_opened',args:a})}).catch(()=>{})}
