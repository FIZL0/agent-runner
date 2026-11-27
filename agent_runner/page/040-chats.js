/* --- drawing ----------------------------------------------------------------------------------------------- */
let DR=null;  // F133: a pinned chat's row being dragged (its pointer, where it started, whether the drag is on)
/* F201: the Chats rows as shown: no row moves while a chat's name is edited (ROWS, the names as last drawn) */
let ROWS=null;
const sideRows=()=>chatPlaces(chatForce(shownChats(),S.snap.chat_put_quiet,S.snap.chat_put_up,chatPins()),standRows(),chatPins(),ROWS,S.ren);
const pressHeld=()=>!!PD.row&&Date.now()-PD.row<HOLD_MS;  // a press on a chat's row
function side(){
  if(DR&&(DR.on||DR.ready&&DR.hold))return;  // F133: a redraw would drop the row from under the finger
  if(pressHeld()){PD.late=true;PD.since=PD.row;return}  // F201: drawn once the press ends
  const nav=NAV;  // F93: Talk first
  const needs=S.snap.needs.length+(S.snap.chat_needs||[]).length, use=usageOf(S.snap.status), cn=(S.snap.concepts||[]).filter(c=>!c.history).length;  /* F516: History rows wait for nothing */
  const count={home:needs,concepts:cn};
  const cs=chats(), ws=working_();
  S.sel=S.sel.filter(n=>cs.some(c=>c.name===n));  // F118: a picked chat that ended elsewhere leaves the pick
  const due0=homeNeeds()+H.alerts.length;
  if(atAll()){S.menuDot=!!due0;sideShow(allSide(),'all');return}  // F150
  if(HOME_PAGE){S.menuDot=!!due0;sideShow(offSide(),'in');return}  // F134: no run behind it
  const g=sideRows(), due=needs||cn;S.menuDot=!!due;  // F128: the phone's menu button gets a dot
  ROWS={top:g.top.map(x=>x.name),quiet:g.quiet.map(x=>x.name)};S.rowKeys=chatKeysAdd(S.rowKeys,S.came);S.came=(S.came||[]).filter(x=>!sessionOf(x.name));
  sideShow(`${allRow()}
   <div class="nav">${nav.map(([k,l])=>`<button class="ni ${!S.thread&&S.view===k?'on':''}" data-view="${k}">${I[k]}${l}${count[k]?`<span class="n" data-k="n:${k}" data-roll data-v="${count[k]}">${count[k]}</span>`:''}</button>`).join('')}</div>${walkRow()}
   <div class="shead row"><span>Chats</span><button class="shadd" data-new title="New chat">${I.plus}Chat</button></div>${chatBar()}${cs.length||g.quiet.length?'':'<div class="none">No chats yet</div>'}${g.top.map(x=>sideRow(x)).join('')}${g.quiet.length?'<div class="qline">Quiet</div>'+g.quiet.map(x=>x.response?responseRow(x):answerNewRow(sideRow(x,true),x,S.answerChats)).join(''):''}
   <div class="shead">Agents working</div>${ws.length?ws.map(s=>`<button class="thread ${S.thread===s.name?'on':''}" data-thread="${esc(s.name)}" data-k="ag:${esc(s.name)}"><span class="livedot"></span><span class="t"><span class="tt">${esc(s.title||s.task)}</span></span></button>`).join(''):'<div class="none">None right now</div>'}
   <div class="me"><div class="av">${esc((S.snap.machine||'?').charAt(0).toUpperCase())}</div><div class="grow"><span class="ell">${esc(S.snap.machine||'this machine')}</span><div class="sub">${S.snap.up===false?'no run is up':`${S.snap.slots||0} slot${S.snap.slots===1?'':'s'}`}${use?` · usage ${esc(use)}`:''}</div></div></div>${runnerVer()}`,'in');
}
/* F507: chats dragged into Quiet or out of it: shown at once, then kept by the run (chat_order) for every page */
function saveQuiet(names,to){
  const was=ROWS||{top:[],quiet:[]}, s=S.snap, put=chatDrop(was,names,to,{quiet:s.chat_put_quiet,up:s.chat_put_up,pins:chatPins()});
  if(!put)return false;
  s.chat_put_quiet=put.quiet;s.chat_put_up=put.up;s.chat_pins=put.pins;S.sel=[];render(true);
  act('chat_order',put);return true;
}
/* F471: the agent-runner version the run is on, a muted line ('' from an older run) */
const runnerVer=(c='runver')=>S.snap&&S.snap.version?`<div class="${c}">agent-runner ${esc(S.snap.version)}</div>`:'';
/* F425b: a sent response's row in Quiet: opening it starts no chat */
const responseRow=x=>`<div class="crow quiet response" data-k="chat:${esc(x.name)}"><button class="thread ${S.thread===x.name?'on':''}" data-thread="${esc(x.name)}"><span class="t"><span class="tt">${esc(x.label)}</span></span>${responseNew(x)}</button></div>`;
/* the sidebar drawn again only when it changed, its scroll and a name being typed kept */
function sideHTML(h,still){const box=$('side'), el=$('sidein'), new_=el._h!==h&&!still, spot=new_?glideSpot(el):null, had=new_?keysIn(el):null, put=keepScroll(box), f=keepFields(el);if(setHTML(el,h)){f();put();if(had)enter(el,had);glide(box,el,spot);loopsInStep(el);const t=el.querySelector('[data-f="ren"]');if(t&&S.renFocus){S.renFocus=false;kbReveal(t,true);kbFocus(t);t.select()}}}
