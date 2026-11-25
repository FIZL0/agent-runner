/* F124: a switch or a select acts at once; F202b: a setting's on its row goes to the draft */
document.addEventListener('change',e=>{
  const t=e.target, ts=t.dataset&&t.dataset.ts, f=(t.dataset&&t.dataset.f)||'';
  if(t.dataset&&t.dataset.tooluse){toolPost({op:'use',name:t.dataset.tooluse,on:t.checked},t.dataset.tooluse);return}  // F169
  if(f.startsWith('dev:')){S.f[f]=t.type==='checkbox'?String(t.checked):t.value;render(true);return}
  if(t.dataset&&t.dataset.mtear!==undefined){MT.ear=t.value;render(true);return}  // B162b1
  if(ts){talkSet(ts,t.type==='checkbox'?t.checked:t.value);return}
  if(t.dataset&&t.dataset.setpart){savePart(t);return}
  if(t.dataset&&t.dataset.setagent){pickAgent(t);return}  // F405
  if(t.dataset&&t.dataset.kinds){saveKinds(t.dataset.kinds,t.value);return}
  if(!f.startsWith('set:'))return;
  S.f[f]=t.type==='checkbox'?String(t.checked):t.value;
  if(t.dataset.now!==undefined){const [,side,...id]=f.split(':');draftSet(id.join(':'),side,{text:S.f[f]});render(true)}
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
  if(e.target.matches&&e.target.matches('[data-f="ren"],[data-rencancel]')){  // F129: Enter keeps the name (its form), Esc does not
    if(e.key==='Escape'){e.preventDefault();cancelRename()}
    return}
  if(e.key==='Escape'&&S.sheet==='need'&&S.askShot>=0){e.preventDefault();shotGo(-1);return}  // F162
  if(e.key==='Escape'&&S.sheet){e.preventDefault();closeSheet();return}  // the topmost thing only
  if(e.key==='Escape'&&S.rowOpen){e.preventDefault();rowShut();return}  // F187
  if(e.target.matches&&e.target.matches('[data-f]')&&e.key==='Enter'&&e.target.tagName==='INPUT'&&e.target.dataset.f.startsWith('set:')){
    e.preventDefault();if(e.target.dataset.now!==undefined){e.target.blur();return}  // F202b: a row's is in the draft
    const [,side,...id]=e.target.dataset.f.split(':');S.f[e.target.dataset.f]=e.target.value;saveSetting(id.join(':'),side);return}
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
document.addEventListener('input',e=>{if(e.target.matches('[data-f]')&&e.target.type!=='checkbox'){S.f[e.target.dataset.f]=e.target.value;if(e.target.dataset.now!==undefined)draftType(e.target);if(['setq','planq'].includes(e.target.dataset.f))render(true);if(e.target.dataset.f.startsWith('give')&&String(S.sure||'').startsWith('give:')){S.sure=null;render(true)}}if(e.target.matches('[data-in]')){grow(e.target);store.set(DRAFT_KEY(boxKey()),e.target.value);HI.i=null;slashShow(e.target)}});
document.addEventListener('paste',e=>{if(!e.target.matches||!e.target.matches('[data-in]'))return;
  const fs=[...(e.clipboardData?.files||[])];if(fs.length){e.preventDefault();fs.forEach(upload)}});
$('file').addEventListener('cancel',holdPlus);
$('file').addEventListener('change',e=>{holdPlus();[...e.target.files].forEach(upload);e.target.value=''});
document.addEventListener('dragover',e=>{if(e.dataTransfer&&[...e.dataTransfer.types].includes('Files'))e.preventDefault()});
document.addEventListener('drop',e=>{if(e.dataTransfer&&e.dataTransfer.files.length){e.preventDefault();[...e.dataTransfer.files].forEach(upload)}});
/* F114, F204a: a key of the row, or the search's x, keeps the field's focus (and its keyboard) */
for(const t of ['pointerdown','mousedown'])document.addEventListener(t,e=>{if(e.target.closest&&e.target.closest('.keys .tool,[data-feedkeys],[data-setqclear],[data-histqclear]'))e.preventDefault()});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&S.thread)loadFeed(S.thread)});
/* F204b: every draw looks whether Settings is in view (render()), so any way out or back counts, and so does the page hidden
   or kept by the browser; true when its search was cleared */
function settingsTrip(leaving){
  const t=settingsAway(S.setAway,!leaving&&!document.hidden&&S.view==='settings'&&!S.thread,Date.now());S.setAway=t.since;
  if(!t.late||!S.f.setq)return false;
  S.f.setq='';const el=document.querySelector('[data-f="setq"]');if(el)el.value='';
  return true;
}
document.addEventListener('visibilitychange',()=>{if(settingsTrip())render(true)});
addEventListener('pagehide',()=>settingsTrip(true));
addEventListener('pageshow',()=>{if(settingsTrip())render(true)});
