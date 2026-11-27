let lastPlace=null;
S.at={};S.pin=true;S.last={};S.keys=false;
const chatShown=()=>!S.thread&&S.view==='talk';
/* F189a: press: a press asked for it, so it glides; anything else is at once, but leaves a glide under way to reach the end */
function toEnd(press){const b=$('body');seeRoom();if(press)scrollGlide(b,endOf);else if(!MO.scroll.has(b)&&!(typeof handOn==='function'&&handOn()))b.scrollTop=b.scrollHeight;S.pin=true;seeBar()}
/* B873: the person's own hand on the chat (a finger down, or a wheel in the last 250 ms): nothing else moves its scroll then */
const HAND={down:false,wheel:0};
const handOn=()=>HAND.down||Date.now()-HAND.wheel<250;
document.addEventListener('touchstart',()=>{HAND.down=true},{capture:true,passive:true});
for(const t of ['touchend','touchcancel'])document.addEventListener(t,e=>{if(!e.touches.length)HAND.down=false},{capture:true,passive:true});
document.addEventListener('wheel',()=>{HAND.wheel=Date.now()},{capture:true,passive:true});
/* B873: a glide under way on b that goes to its end (toEnd's), not to a place above it */
const glidesEnd=b=>{const g=MO.scroll.get(b);return !!g&&g.to===endOf};
/* F171: the room Talk's top bar (with a notice's row) and dock take from the chat behind them; and the top bar away or not */
let SEE={top:0,size:'',run:0,away:false};
function seeRoom(){
  if(!chatShown()){if(FD.shown)feedPlace();return}
  const s=document.querySelector('.main').style, bar=$('top').offsetHeight, set=(k,v)=>s.setProperty(k,v+'px');
  set('--seebar',bar);set('--seetop',bar+document.querySelector('.notices').offsetHeight);set('--seedock',$('dock').offsetHeight);
}
function seeBar(){
  if(chatShown())SEE=barAway(SEE,$('body'));else SEE={top:0,size:'',run:0,away:false};
  document.querySelector('.main').classList.toggle('away',SEE.away);
}
/* F150: the one + of a view, at the top right: what it adds is its word */
function plusBtn(){
  const b=(attr,word,title,off)=>`<button class="btn plus" ${attr} title="${title}"${off?' disabled':''}>${I.plus}${word}</button>`;
  if(HOME_PAGE?S.thread||!atAll():S.thread&&(isNew(S.thread)||S.thread[0]==='@'))return '';
  if(S.thread)return b('data-new','Chat','New chat',!!PLUS_HOLD);  // B762: a chat or a slot's session; not one still empty or starting
  return{projects:()=>b('data-addproject','Project','Add a project'),home:()=>b('data-about="new"','Task','Add a task',!!PLUS_HOLD),plan:()=>b('data-about="new"','Task','Add a task',!!PLUS_HOLD),
    concepts:()=>b('data-about="newconcept"','Concept','New concept'),
    tools:()=>S.tools&&S.tools.secure?b('data-tool="add"','Device','Add a device'):'',talk:()=>b('data-newtalk','New talk','New Talk chat')}[S.view]?.()||'';
}
/* the top bar: the menu (with its dot, F128), back, the title, Talk's settings, the state pill, the session, and the view's + (F150) */
function topHTML(){
  const n=S.thread, p=runPill(S.snap), x=n&&sessionOf(n);
  return `<button class="icon menu" data-menu aria-label="Menu${S.menuDot?': something needs you':''}">${I.menu}${S.menuDot?'<span class="bdot"></span>':''}</button>${n?`<button class="icon" data-home aria-label="Back">${I.back}</button>`:devBackBtn()}${x&&!isAgent(n)?`<button type="button" class="title" data-chats aria-haspopup="dialog" title="Switch chat"><span class="tt">${esc(threadTitle(n))}</span>${I.chev}</button>`:`<div class="title">${n?`<span class="tt">${esc(threadTitle(n))}</span>`:{talk:'Talk',home:'',status:'Status',plan:'Plan',history:'History',concepts:'Concepts',tools:'Tools',settings:'Settings',projects:allTitle()}[S.view]}</div>`}${p.text&&!atAll()?`<button class="pill ${p.cls}" data-view="status" data-k="pill" data-roll data-v="${esc(p.text)}" title="The run: open Status">${esc(p.text)}</button>`:''}${!n&&S.view==='talk'?`<button class="icon" data-sheet="talk" aria-label="Talk settings" title="Talk settings">${I.settings}</button>`:''}${x&&x.link?`<a class="icon" href="${esc(x.link)}" target="_blank" rel="noopener" aria-label="Open its session" title="Open its session">${I.ext}</a>`:''}${plusBtn()}`;
}
function render(force){
  keepPlace();  // B177
  settingsTrip();  // F204b
  if(!force&&(PD.down||selecting()||MO.vt)){const now=Date.now();PD.since=PD.late?PD.since:now;PD.late=true;if(now-PD.since<HOLD_MS)return}  // but never for long
  PD.late=false;
  markSeen();  // F128
  obHide();
  const n=S.thread, body=$('body'), dockEl=$('dock');
  if(HOME_PAGE){S.thread=null;if(!HKEY||S.view!=='projects')S.view=HKEY?'home':'projects'}
  const place=HOME_PAGE?'home page:'+S.view+(H.tab||'')+(H.dev?':'+H.dev:''):n?'t:'+n:'v:'+S.view+(S.view==='projects'&&H.tab?':'+H.tab+(H.dev?':'+H.dev:''):''), moved=place!==lastPlace, chatOn=!!n||S.view==='talk';
  if(moved&&(lastPlace||talkLate())&&!HOME_PAGE&&chatShown())talkBack();  // B802
  if(!HOME_PAGE&&!chatShown())talkAway();  // B836
  const put=keepScroll(body), had=keysIn(body), hadTop=keysIn($('top')), keep=keepFields(body);
  if(moved)scrollStop(body);
  if(moved&&lastPlace)S.at[lastPlace]=body.scrollTop;
  obDraw();  // F137
  newsDraw();  // F149
  loginDraw();
  offDraw();  // F402b3b
  walkDraw();  // F194b
  setBarDraw();  // F202b
  waitBarDraw();  // F442
  rowSettle();side();sheetDraw();
  if(HOME_PAGE){  // F134: Home's own page: All projects, and F150 a project with no run up
    setHTML($('top'),`<button class="icon menu" data-menu aria-label="Menu${S.menuDot?': something needs you':''}">${I.menu}${S.menuDot?'<span class="bdot"></span>':''}</button>${devBackBtn()}<div class="title">${atAll()?allTitle():esc((projectOf(HKEY)||{}).name||HKEY)}</div>${plusBtn()||'<span class="icon"></span>'}`);
    if(moved)body._h=null;
    const ph=projectsHTML(), spot=moved||body._h===ph?null:glideSpot(body);
    if(setHTML(body,ph)){keep();if(moved){body.scrollTop=S.at[place]||0;if(S.live&&lastPlace)viewIn(body)}else{put();enter(body,had);glide(body,body,spot);leaving(body)}loopsInStep(body)}
    pageColor(false);lastPlace=place;dockEl.hidden=true;return;
  }
  const top=$('top'), th=topHTML(), topSpot=moved||top._h===th?null:glideSpot(top);
  if(setHTML(top,th)){enter(top,moved&&lastPlace?keysIn(top):hadTop);glide(top,top,topSpot);loopsInStep(top)}
  let h='',dock='';
  feedDraw(n);  // F114
  if(n){const agent=isAgent(n);h=$('body').hidden?'':feedHTML(n);
    dock=(isNew(n)?'':feedEnd(n)+sessRow(n)+keysRow())+box(agent?`Message ${threadTitle(n)}`:isNew(n)?newPh(S.ctx):`Reply to ${threadTitle(n)}`,
      (agent?'Goes straight to this agent, between its steps. ':'')+keysLine(!!modelOf(n)))}  // B120: the keys, from BOX_KEYS
  else if(S.view==='talk')h=talkHTML();
  else h={home:homeHTML,status:statusHTML,plan:planHTML,history:historyHTML,concepts:conceptsHTML,tools:toolsHTML,settings:settingsHTML,projects:projectsHTML}[S.view]();
  const ta=document.querySelector('[data-in]'), focused=ta&&document.activeElement===ta, sel=ta?[ta.selectionStart,ta.selectionEnd]:null;
  const main=document.querySelector('.main');  // F115: a chat looks like the terminal
  main.classList.toggle('term',chatOn);main.style.colorScheme=chatOn&&TERM.mode?TERM.mode:'';main.classList.toggle('see',chatShown());pageColor(chatOn);
  if(moved){body._h=null;dockEl._h=null}
  const spot=moved||body._h===h?null:glideSpot(body);
  const drew=!n&&S.view==='settings'?settingsDraw(body,h):!n&&S.view==='plan'?planDraw(body,h):!n&&S.view==='history'?histDraw(body,h):setHTML(body,h);
  let drewDock=false;
  if(!n&&S.view==='talk'){  // F124: the mic and the box cross-fade: both stay in the dock
    drewDock=setHTML(dockEl,'<div class="talkdock"><div class="talkmic" id="talkmic"></div><div class="talkbox" id="talkbox"></div></div>');
    setHTML($('talkmic'),talkMic());drewDock=setHTML($('talkbox'),box('Type to Talk',talkFoot()))||drewDock;
    talkDraw();
  }else{drewDock=setHTML(dockEl,dock);dockEl.classList.remove('typing')}
  dockEl.hidden=!n&&S.view!=='talk';
  if(moved)seeBar();
  if(!force&&!drew&&!drewDock){lastPlace=place;return}
  const nta=document.querySelector('[data-in]');
  if(nta){const v=HI.i!==null&&HI.key===boxKey()?histGet(HI.key)[HI.i]||'':store.get(DRAFT_KEY(boxKey()));if(nta.value!==v)nta.value=v;grow(nta,true);if(focused&&nta!==ta){nta.focus({preventScroll:true});if(sel)nta.setSelectionRange(sel[0],sel[1])}if(focused)slashShow(nta)}  // B119: the menu stays open; B120: so does a recalled message
  if(drew)keep();
  if(moved){
    const follow=lastPlace&&(lastPlace.startsWith('t:@')&&n||lastPlace.startsWith('t:+')&&n&&n[0]==='@');  // a starting chat got its name, a new one started: the same chat
    if(chatShown())toEnd();else{body.scrollTop=S.at[place]||0}
    if(S.live&&lastPlace&&!follow){const was=lastPlace.startsWith('t:');if(n&&was){}else if(n||was)viewSlide(n?'in':'out');else viewIn(body)}  // F206: from chat to chat at once
    if(n)sentFrom(body,had);
    freshWords(body);
  }else if(drew){
    if(chatShown()&&S.pin)toEnd();
    else put();
    enter(body,had);glide(body,body,spot);leaving(body);freshWords(body);sentFrom(body,had);
  }
  if(drew)loopsInStep(body);
  seeBar();
  lastPlace=place;
}
/* F83: Talk follows its newest words until the person scrolls up; it follows a box that grows or a keyboard too */
$('body').addEventListener('scroll',()=>{if(chatShown()){S.pin=typeof glidesEnd==='function'?glidesEnd($('body'))||!MO.scroll.has($('body'))&&atEnd($('body')):MO.scroll.has($('body'))||atEnd($('body'));seeBar()}},{passive:true});
if(window.ResizeObserver)new ResizeObserver(()=>{if(chatShown()&&S.pin)toEnd()}).observe($('body'));
/* B160, F126a: a notice's row comes or goes: the text stays where it was (a pinned chat by the line above) */
let noticeH=0, noticeAt=null;
function noticeRoom(h){const d=h-noticeH, same=noticeAt===lastPlace;noticeH=h;noticeAt=lastPlace;if(d&&same&&!(chatShown()&&S.pin)&&$('body').scrollTop>0)$('body').scrollTop+=d}
if(window.ResizeObserver)new ResizeObserver(()=>{seeRoom();noticeRoom(document.querySelector('.notices').offsetHeight);seeBar()}).observe(document.querySelector('.notices'));
if(window.ResizeObserver){const o=new ResizeObserver(()=>{if(!chatShown()){if(FD.shown)feedPlace();return}if(S.pin)toEnd();else{seeRoom();seeBar()}});o.observe($('top'));o.observe($('dock'));new ResizeObserver(()=>{if(FD.shown)feedPlace()}).observe(document.querySelector('.main'))}
/* B160: the page's own background, behind Safari's bar and the keyboard, is the view's */
let edgeWait=0;
function pageColor(chat){
  document.documentElement.classList.toggle('term',!!chat);
  const c=getComputedStyle(document.body).backgroundColor, m=$('themecolor');if(!m||m.content===c)return;
  const first=!m.content;m.content=c;
  if(!IOS)return;
  for(const e of document.querySelectorAll('.edge'))e.remove();
  clearTimeout(edgeWait);
  /* Safari tints its bars from a fixed layer over the page's edge, and only looks when one comes: a swap in one go is not seen */
  if(!first)edgeWait=setTimeout(()=>{for(const k of ['top','bottom']){const e=document.createElement('div');e.className='edge edge-'+k;document.body.appendChild(e)}},300);
}
/* B160: a phone's keyboard shrinks only the visual viewport (iOS does not shrink dvh) and pans the page, so while it is
   open .app takes the visual viewport's height and place. Not while pinch-zoomed: then the person pans. iOS sends its
   events in any order and late, so for KB_MS after a field is entered or left kbFit() also runs on every frame. */
/* F516: Concepts' History: past concepts whose page is still there, newest first, in a fold closed at first; each row
   grayed (.past), with View and Chat only (no Drop: a history row has no actions) */
function conceptHistoryHTML(cs){  // cs: [concept, its index in S.snap.concepts]
  return cs.length?`<details class="chist" data-k="chist"><summary class="sec">History (${cs.length})<span class="ln"></span></summary>${cs.map(([c,i])=>conceptCard({...c,acts:[]},i).replace('class="card ','class="card past ')).join('')}</details>`:'';
}
