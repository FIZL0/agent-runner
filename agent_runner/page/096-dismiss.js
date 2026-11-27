/* F437a: Minimize on the question card: the card becomes one line with Show question, kept over a redraw and a reload (per
   browser and project, the latest 100; other tabs follow). Nothing is sent or answered; a later question comes open.
   F192b's Dismiss is gone from the card: what it dismissed stays gone (QN.gone, only read now) */
const QGONE_KEY='ar-qgone'+(HKEY?':'+HKEY:''), QMIN_KEY='ar-qmin'+(HKEY?':'+HKEY:'');
const questionKept=k=>{try{const l=JSON.parse(store.get(k)||'[]');return Array.isArray(l)?l.filter(x=>typeof x==='string'):[]}catch(e){return[]}};
QN.gone=new Set(questionKept(QGONE_KEY));
QN.min=new Set(questionKept(QMIN_KEY));
function questionMinimize(n,id,on){
  const ask=questionAsk(n);if(!ask||ask.id!==id||questionState(ask,QN.held.get(n),QN.sent.get(n))!=='ask'||Date.now()-QN.back<QUESTION_AGAIN)return;
  const k=questionKey(n,id), l=new Set([...questionKept(QMIN_KEY),...QN.min]);
  l.delete(k);if(on)l.add(k);
  QN.min=new Set([...l].slice(-100));
  store.set(QMIN_KEY,JSON.stringify([...QN.min]));
  QN.back=Date.now();  // a double tap on either does not press what came under the finger
  questionDraw();
}
document.addEventListener('click',e=>{
  const el=e.target.closest('[data-qmin],[data-qshow],[data-qrowmin],[data-qrowshow]');if(!el)return;  // F496: the whole top row toggles too
  const d=el.dataset, on=!!(d.qmin||d.qrowmin);
  questionMinimize(S.thread,d.qmin||d.qshow||d.qrowmin||d.qrowshow,on);
  if(!e.detail){const b=document.querySelector('#dock [data-qshow],#dock [data-qmin]');if(b)b.focus({preventScroll:true})}  // pressed with a key: the focus stays with the card
});
addEventListener('storage',e=>{  // another tab
  if(e.key!==QGONE_KEY&&e.key!==QMIN_KEY)return;
  QN.gone=new Set(questionKept(QGONE_KEY));QN.min=new Set(questionKept(QMIN_KEY));render(true);
});
