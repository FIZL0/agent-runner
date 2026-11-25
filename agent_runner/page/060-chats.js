function chatRow(s,quiet){
  const n=s.name,u=S.undo,gone=!!(u&&u.names.includes(n)),cls=[S.thread===n&&!gone?'on':'',S.sel.includes(n)?'sel':'',gone?'gone':''].join(' ');
  if(S.ren&&S.ren===n)return `<form class="renform" data-renform data-k="chat:${esc(n)}"><input data-f="ren" aria-label="The chat's name" maxlength="80" autocomplete="off"><button class="icon" type="button" data-rencancel aria-label="Cancel rename" title="Cancel rename">${I.x}</button></form>`;  // F129, F446
  const due=!gone&&replyDue(s);  // F128
  const row=`<button class="thread ${cls}" ${gone?'':`data-thread="${esc(n)}" title="Double-click to rename"`}>${s.state==='live'?'':'<span class="off" title="not running"></span>'}<span class="t"><span class="tt">${esc(chatTitle(s))}</span></span>${due?'<span class="bdot" role="img" aria-label="needs your reply" title="needs your reply"></span>':''}</button>`;
  const btn=gone?(u.bar?'':`<button class="del undo" data-undo>Undo</button>`):
    `<button class="del" data-del="${esc(n)}" aria-label="Delete this chat" title="Delete this chat">${I.trash}</button>`;
  const pinned=chatPins().includes(n), pin=gone?'':`<button class="pin${pinned?' on':''}" data-pin="${esc(n)}" aria-pressed="${pinned}" aria-label="${pinned?'Unpin':'Pin'} this chat" title="${pinned?'Unpin':'Pin'} this chat">${I.pin}</button>`;
  const on=!gone&&S.rowOpen===n, menu=gone?'':on?`<span class="rowacts" role="group" aria-label="This chat"><button data-ren="${esc(n)}" aria-label="Rename this chat">${I.edit}</button><button class="${pinned?'on':''}" data-pin="${esc(n)}" aria-pressed="${pinned}" aria-label="${pinned?'Unpin':'Pin'} this chat">${I.pin}</button><button data-del="${esc(n)}" aria-label="Delete this chat">${I.trash}</button></span>`:
    `<button class="rowmenu" data-rowmenu="${esc(n)}" aria-expanded="false" aria-label="More for this chat">${I.dots}</button>`;  // F187
  return `<div class="crow${quiet?' quiet':''}${pinned?' pinned':''}${on?' open':''}" data-k="chat:${esc(n)}" ${gone?'':`data-crow="${esc(n)}"`}>${row}${pin}${btn}${menu}</div>`;
}
/* F187: on touch, the chat row opened by its three dots: one at a time, its buttons in the row, Delete in the dots' place.
   A tap anywhere else only closes it, and so do Esc, one of its buttons and the drawer closing */
function rowExpand(n){S.rowOpen=n;render(true);const b=document.querySelector('.rowacts button');if(b){b.focus({preventScroll:true});if(b.animate)moAnim(b.parentElement,[{transform:'translateX(24px)',opacity:0},{transform:'none',opacity:1}],FOLD_MO)}}
function rowShut(){const n=S.rowOpen, was=document.querySelector('.rowacts');S.rowOpen='';render(true);const b=document.querySelector(`[data-rowmenu="${CSS.escape(n)}"]`);if(b){b.focus({preventScroll:true});if(b.animate)rowActsOut(b.parentElement,was)}}
/* F189b: a copy of a closed row's buttons goes back; the dots come in their place */
function rowActsOut(row,was){
  const g=was&&row&&!calm()&&was.cloneNode(true);if(!g)return;
  g.className='rowacts gone0';g.style.left='auto';g.setAttribute('aria-hidden','true');g.inert=true;for(const x of g.querySelectorAll('*'))for(const k of Object.keys(x.dataset))delete x.dataset[k];
  row.appendChild(g);
  const a=moAnim(g,[{transform:'none',opacity:1},{transform:'translateX(24px)',opacity:0}],{...FOLD_MO,fill:'forwards'});a.onfinish=a.oncancel=()=>g.remove();
  moAnim(row.querySelector('.rowmenu'),[{opacity:0},{opacity:1}],{ease:'--ease',dur:'--dur'});
}
function rowTap(e){
  if(!S.rowOpen||e.target.closest('.rowacts button,[data-rowmenu]'))return;
  e.preventDefault();e.stopPropagation();rowShut();
}
function rowSettle(){if(S.rowOpen&&(S.sheet||S.ren||atAll()||!sessionOf(S.rowOpen)||drawerOn()&&!S.drawer))S.rowOpen=''}
/* F129: Rename, in the row itself: Enter keeps it; Esc, its Cancel button (F446) or opening another chat (renameLeave) does not */
function startRename(n){const x=sessionOf(n);if(!x)return;S.ren=n;S.f.ren=chatTitle(x);if(drawerOn())S.drawer=true;S.renFocus=true;render(true)}
function cancelRename(){S.ren=null;render(true)}
function renameLeave(n){if(S.ren&&n&&n!==S.ren)S.ren=null}  // the caller draws
function saveRename(){
  const n=S.ren, title=String(S.f.ren||'').replace(/\s+/g,' ').trim(), x=sessionOf(n);S.ren=null;
  if(x&&title&&title!==chatTitle(x))outbox('rename_chat',{chat:n,title},{ren:n,say:`Rename ${chatTitle(x)} to “${title}”`});
  else render(true);
}
function chatBar(){
  if(S.undo&&S.undo.bar)return `<div class="selbar"><span>Deleted ${S.undo.names.length} chats</span><button class="btn" data-undo>Undo</button></div>`;
  return S.sel.length>1?`<div class="selbar"><span>${S.sel.length} selected</span><button class="btn" data-delsel>Delete ${S.sel.length}</button></div>`:'';
}
/* F118: a delete is final once the person clicks anything but Undo (or leaves the page): only then is it sent */
function finalDelete(){
  const u=S.undo;if(!u)return;S.undo=null;
  if(u.names.includes(S.thread)){S.thread=null;S.ctx=null}
  S.snap.sessions=S.snap.sessions.filter(s=>!u.names.includes(s.name));
  fetch(tq('act'),{method:'POST',keepalive:true,headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'delete_chats',args:{names:u.names}})})
    .then(r=>r.json()).then(j=>{if(!j.ok)actFailed(j,'The delete did not work')}).catch(e=>toast(`Could not reach the run page: ${plainErr(e)}`,true));
  render(true);
}
/* B213, B768: the file picker just closed: the top bar's + Task and + Chat take no press for a second, so a double press in the picker cannot land on one */
const PLUS_HELD='.plus[data-about="new"],.plus[data-new]';
let PLUS_HOLD=0;
function holdPlus(){
  clearTimeout(PLUS_HOLD);PLUS_HOLD=setTimeout(()=>{
    PLUS_HOLD=0;const b=document.querySelector(PLUS_HELD);if(b)b.disabled=false;render();  // at once: a draw can wait on a finger or a selection
  },1000);
  render();
}
function plusHeld(x){return !!PLUS_HOLD&&x.matches(PLUS_HELD)}
