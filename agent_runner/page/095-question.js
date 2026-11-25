/* --- F192a1: the question card (questionHTML and the rest in the logic script) -----------------------------------
   held: chat -> the answer that waits out its hold {id, name, at, timer}; sent: chat -> the last one that went {id, name,
   cid}; back: when an Undo brought a card back. In memory only: a reload in the hold sends nothing, the card is there again */
const QN={held:new Map(),sent:new Map(),back:0};
const questionAsk=n=>FD.n===n&&FD.live&&FD.live.ask||null;
/* the card of chat n, drawn over its chips (sessRow) */
function questionCard(n){
  if(!/^c\d+$/.test(n||''))return '';
  const sent=questionSent(QN.sent.get(n),S.ob,(S.sent[n]&&S.sent[n].pending)||[]);if(sent)QN.sent.set(n,sent);
  return questionHTML(n,questionAsk(n),QN.held.get(n),sent);
}
/* before a draw that may bring, change or take the card; what it returns is called after: the card fades in and the frame
   glides with the dock. still: the chat was just opened, so nothing moves */
function questionMove(n,still){
  questionSee(n);
  const at=()=>{const c=document.querySelector('#dock .qcard');return c?c.dataset.k+c.dataset.v:''}, was=feedTop(), had=at();
  return()=>{
    const now=at();if(still||now===had)return;
    if(now)moAnim(document.querySelector('#dock .qcard'),[{transform:'translateY(14px)',opacity:0},{transform:'none',opacity:1}],{ease:'--ease',dur:'--dur'});
    feedGlide(was);
  };
}
function questionDraw(){const moved=questionMove(S.thread,false);render(true);moved()}
function questionPick(n,id,i){
  const ask=questionAsk(n), o=ask&&ask.id===id&&ask.options[i];
  if(!o||questionState(ask,QN.held.get(n),QN.sent.get(n))!=='ask'||Date.now()-QN.back<QUESTION_AGAIN)return;
  const h={id,name:o.name,at:Date.now()};
  h.timer=setTimeout(()=>questionSend(n,h),QUESTION_HOLD);QN.held.set(n,h);
  questionDraw();
}
function questionUndo(n){
  const h=QN.held.get(n);if(!h||Date.now()-h.at<QUESTION_AGAIN)return;
  clearTimeout(h.timer);QN.held.delete(n);QN.back=Date.now();
  questionDraw();
}
/* /live was read: an answer held to a question that is gone (answered elsewhere, the chat went on) is not sent */
function questionSee(n){
  const h=QN.held.get(n);if(!h||FD.n!==n||questionOpen(FD.live,h.id))return;
  clearTimeout(h.timer);QN.held.delete(n);toast(`“${h.name}” was not sent: the question is no longer open`,true);
}
async function questionSend(n,h){
  if(Date.now()-h.at>QUESTION_HOLD+2000&&FD.n===n)await liveLoad();  // the page slept through the hold: what is asked now?
  questionSee(n);
  if(QN.held.get(n)!==h)return;  // Undo, or no longer asked
  QN.held.delete(n);
  const moved=questionMove(n,false), it={id:h.id,name:h.name,cid:''};
  QN.sent.set(n,{...it,over:true});  // answered, before outbox() draws
  sendHold(n,SEND_HOLD);
  if(FD.shown&&FD.n===n)feedRest();
  it.cid=outbox('chat_to',{text:h.name,to:n,...(FD.n===n&&FD.foot&&FD.foot.text?{unsent:true}:{})},{text:h.name,key:n,say:`To ${threadTitle(n)}: ${h.name}`}).cid;
  QN.sent.set(n,it);
  moved();
}
document.addEventListener('click',e=>{
  const el=e.target.closest('[data-qpick],[data-qundo]');if(!el)return;
  const key=!e.detail, n=el.dataset.qundo||S.thread;
  if(el.dataset.qundo)questionUndo(n);else questionPick(n,el.dataset.q,+el.dataset.qpick);
  if(key){const b=document.querySelector('#dock [data-qundo],#dock [data-qpick]');if(b)b.focus({preventScroll:true})}  // pressed with a key: the focus stays with the card
});
