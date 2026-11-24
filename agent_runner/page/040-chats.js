/* --- drawing ----------------------------------------------------------------------------------------------- */
let DR=null;  // F133: a chat row being dragged (its pointer, where it started, whether the drag is on)
function side(){
  if(DR&&(DR.on||DR.ready&&DR.hold))return;  // F133: a redraw would drop the row from under the finger
  const nav=NAV;  // F93: Talk first
  const needs=S.snap.needs.length, use=usageOf(S.snap.status), cn=(S.snap.concepts||[]).length;
  const count={home:needs,concepts:cn};
  const cs=chats(), ws=working_();
  S.sel=S.sel.filter(n=>cs.some(c=>c.name===n));  // F118: a picked chat that ended elsewhere leaves the pick
  const due0=homeNeeds()+H.alerts.length;
  if(atAll()){S.menuDot=!!due0;sideShow(allSide(),'all');return}  // F150
  if(HOME_PAGE){S.menuDot=!!due0;sideShow(offSide(),'in');return}  // F134: no run behind it
  const g=shownChats(), due=needs||cn;S.menuDot=!!due;  // F128: the phone's menu button gets a dot
  sideShow(`${allRow()}
   <div class="nav">${nav.map(([k,l])=>`<button class="ni ${!S.thread&&S.view===k?'on':''}" data-view="${k}">${I[k]}${l}${count[k]?`<span class="n" data-k="n:${k}" data-roll data-v="${count[k]}">${count[k]}</span>`:''}</button>`).join('')}</div>${walkRow()}
   <div class="shead row"><span>Chats</span><button class="shadd" data-new title="New chat">${I.plus}Chat</button></div>${chatBar()}${cs.length?g.top.map(x=>chatRow(x)).join('')+obChatRows()+(g.quiet.length?'<div class="qline">Quiet</div>'+g.quiet.map(x=>chatRow(x,true)).join(''):''):'<div class="none">No chats yet</div>'+obChatRows()}
   <div class="shead">Agents working</div>${ws.length?ws.map(s=>`<button class="thread ${S.thread===s.name?'on':''}" data-thread="${esc(s.name)}" data-k="ag:${esc(s.name)}"><span class="livedot"></span><span class="t"><span class="tt">${esc(s.title||s.task)}</span></span></button>`).join(''):'<div class="none">None right now</div>'}
   <div class="me"><div class="av">${esc((S.snap.machine||'?').charAt(0).toUpperCase())}</div><div class="grow"><span class="ell">${esc(S.snap.machine||'this machine')}</span><div class="sub">${S.snap.up===false?'no run is up':`${S.snap.slots||0} slot${S.snap.slots===1?'':'s'}`}${use?` · usage ${esc(use)}`:''}</div></div></div>`,'in');
}
/* the sidebar drawn again only when it changed, its scroll and a name being typed kept */
function sideHTML(h,still){const box=$('side'), el=$('sidein'), new_=el._h!==h&&!still, spot=new_?glideSpot(el):null, had=new_?keysIn(el):null, put=keepScroll(box), f=keepFields(el);if(setHTML(el,h)){f();put();if(had)enter(el,had);glide(box,el,spot);loopsInStep(el);const t=el.querySelector('[data-f="ren"]');if(t&&S.renFocus){S.renFocus=false;kbReveal(t,true);kbFocus(t);t.select()}}}
