/* --- F192c: the card shrinks while typing ----------------------------------------------------------------------------
   Focus or typing in the message box shrinks the open question card to its minimized line (QN.auto, as a scroll does,
   F511); a tap on the line opens it again, and so does leaving the box empty. QN.typing: the question shrunk so;
   QN.typeOpen: the one opened again by a tap while typing, left open until the box is left. A card minimized by hand
   (QN.min) is never touched. The draw keeps the box and its focus, so the keyboard stays where it is. */
QN.typing='';QN.typeOpen='';
const questionBox=t=>!!(t&&t.matches&&t.matches('[data-in]'));
function questionTyping(){
  const k=questionUp(S.thread);if(!k||QN.typeOpen===k)return;
  QN.auto.add(k);QN.typing=k;clearTimeout(QN.growT);QN.growT=0;questionDraw();
}
function questionTypingEnd(t){
  const k=QN.typing;QN.typeOpen='';
  if(!k||(t&&t.value||'').trim())return;
  QN.typing='';QN.auto.delete(k);questionDraw();
}
for(const [k,f] of [['focusin',t=>{if(TOUCH())questionTyping()}],['input',questionTyping],['focusout',questionTypingEnd]])  // one loop: other tests cut the page at the box's own input listener
  // focus shrinks only on touch, where the keyboard takes the room: on a desktop the box holds focus from the start
  document.addEventListener(k,e=>{if(questionBox(e.target))f(e.target)});
document.addEventListener('click',e=>{  // a tap on the line while typing: it stays open until the box is left
  const el=e.target&&e.target.closest&&e.target.closest('[data-qshow],[data-qrowshow]');if(!el||!QN.typing)return;
  QN.typeOpen=QN.typing;QN.typing='';
});
