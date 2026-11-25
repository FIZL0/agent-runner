/* F192b: Dismiss on the question card: the card goes and stays gone over a reload (per browser and project, the latest
   100). Nothing is sent or answered: the run still files the question under Needs you, and a later question has its card */
const QGONE_KEY='ar-qgone'+(HKEY?':'+HKEY:'');
const questionGoneGet=()=>{try{const l=JSON.parse(store.get(QGONE_KEY)||'[]');return Array.isArray(l)?l.filter(x=>typeof x==='string'):[]}catch(e){return[]}};
QN.gone=new Set(questionGoneGet());
function questionDismiss(n,id){
  const ask=questionAsk(n);if(!ask||ask.id!==id||questionState(ask,QN.held.get(n),QN.sent.get(n))!=='ask'||Date.now()-QN.back<QUESTION_AGAIN)return;
  QN.gone=new Set([...new Set([...questionGoneGet(),...QN.gone,questionGoneKey(n,id)])].slice(-100));
  store.set(QGONE_KEY,JSON.stringify([...QN.gone]));
  questionDraw();
}
document.addEventListener('click',e=>{
  const el=e.target.closest('[data-qdismiss]');if(!el)return;
  questionDismiss(S.thread,el.dataset.qdismiss);
  if(!e.detail){const ta=document.querySelector('[data-in]');if(ta)ta.focus({preventScroll:true})}  // pressed with a key: the focus stays near
});
addEventListener('storage',e=>{if(e.key===QGONE_KEY){QN.gone=new Set(questionGoneGet());render(true)}});  // another tab
