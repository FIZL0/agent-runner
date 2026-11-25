/* --- F192a1: the question card (questionHTML and the rest in the logic script) -----------------------------------
   held: chat -> the answer that waits out its hold {id, name, at, timer}; sent: chat -> the last one that went {id, name,
   cid}; back: when an Undo brought a card back. In memory only: a reload in the hold sends nothing, the card is there again.
   F192a2: mark: chat -> the question marked above its box (over a reload too, as its draft is); kept: chat -> the question
   talked about, its card back though /live no longer says it (in memory only); marked: when the mark came */
const QMARK_KEY='ar-qmark:'+(HKEY||document.title);
const QN={held:new Map(),sent:new Map(),back:0,mark:new Map(questionMarks(tabStore.get(QMARK_KEY))),kept:new Map(),marked:0};
const questionAsk=n=>FD.n===n?questionNow(FD.live,QN.kept.get(n)):null;
const questionSpoken=n=>questionSpoke(n,S.ob,(S.sent[n]&&S.sent[n].pending)||[],Date.now()-((S.sent[n]||{}).at||0));
/* the card of chat n, drawn over its chips (sessRow) */
function questionCard(n){
  if(!/^c\d+$/.test(n||''))return '';
  const sent=questionSent(QN.sent.get(n),S.ob,(S.sent[n]||{}).at);if(sent)QN.sent.set(n,sent);
  const mark=QN.mark.get(n);if(mark&&!QN.held.has(n))return questionMarkHTML(n,mark);
  return questionHTML(n,questionSpoken(n)?null:questionAsk(n),QN.held.get(n),sent);
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
/* /live was read: an answer held to a question that is gone (answered elsewhere or in words, the chat went on) is not sent */
function questionSee(n){
  const kept=QN.kept.get(n), live=FD.n===n&&FD.live;if(kept&&live&&live.ask&&live.ask.id!==kept.id)QN.kept.delete(n);  // another is asked
  const h=QN.held.get(n);if(!h||!questionSpoken(n)&&(FD.n!==n||questionOpen(FD.live&&{...FD.live,ask:questionAsk(n)},h.id)))return;
  clearTimeout(h.timer);QN.held.delete(n);toast(`“${h.name}” was not sent: the question is no longer open`,true);
}
async function questionSend(n,h){
  if(Date.now()-h.at>QUESTION_HOLD+2000&&FD.n===n){  // the page slept through the hold: what is asked now?
    if(document.hidden){h.timer=setTimeout(()=>questionSend(n,h),1000);return}  // liveLoad asks nothing then
    await liveLoad();
  }
  questionSee(n);
  if(QN.held.get(n)!==h)return;  // Undo, or no longer asked
  QN.held.delete(n);
  const moved=questionMove(n,false), it={id:h.id,name:h.name,cid:'',at:Date.now()};
  QN.sent.set(n,{...it,over:true});  // answered, before outbox() draws
  sendHold(n,SEND_HOLD);
  if(FD.shown&&FD.n===n)feedRest();
  it.cid=outbox('chat_to',{text:h.name,to:n,...(FD.n===n&&FD.foot&&FD.foot.text?{unsent:true}:{})},{text:h.name,key:n,say:`To ${threadTitle(n)}: ${h.name}`}).cid;
  QN.sent.set(n,it);
  moved();
}
/* F192a2: Chat about this: the question marked above the box, and the box in focus, in the tap itself */
function questionMark(n,ask){
  if(ask)QN.mark.set(n,ask);else QN.mark.delete(n);
  tabStore.set(QMARK_KEY,QN.mark.size?JSON.stringify([...QN.mark]):'');
}
function questionChat(n,id){
  const ask=questionAsk(n);if(!ask||ask.id!==id||questionState(ask,QN.held.get(n),QN.sent.get(n))!=='ask'||Date.now()-QN.back<QUESTION_AGAIN)return;
  questionMark(n,ask);QN.marked=Date.now();questionDraw();
  const ta=document.querySelector('[data-in]');if(ta)kbFocus(ta);
}
function questionUnchat(n){
  if(!QN.mark.has(n)||Date.now()-QN.marked<QUESTION_AGAIN)return;
  questionMark(n,null);QN.back=Date.now();questionDraw();
}
/* a message from chat n's box goes (send()): with the question marked, it is about it, and the card comes back; else it
   answers a question that was talked about, as any typed message does. go(words, more) puts it in the outbox */
function questionGo(n,text,go){
  const mark=QN.mark.get(n);
  if(!mark||!questionWraps(text)){
    const kept=QN.kept.get(n), at=Date.now(), it=go(text,{});
    if(kept&&questionWraps(text)){QN.sent.set(n,{id:kept.id,name:'',cid:it.cid,at});questionDraw()}
    return;
  }
  const moved=questionMove(n,false);
  if(FD.n!==n||questionStill(FD.live,QN.kept.get(n),mark))QN.kept.set(n,mark);
  questionMark(n,null);QN.back=Date.now();
  go(questionAbout(mark,text),{about:mark});
  moved();
}
document.addEventListener('click',e=>{
  const el=e.target.closest('[data-qchat],[data-qunchat]');if(!el)return;
  if(el.dataset.qchat)return questionChat(S.thread,el.dataset.qchat);
  questionUnchat(el.dataset.qunchat);
  if(!e.detail){const b=document.querySelector('#dock [data-qchat]');if(b)b.focus({preventScroll:true})}
});
document.addEventListener('click',e=>{
  const el=e.target.closest('[data-qpick],[data-qundo]');if(!el)return;
  const key=!e.detail, n=el.dataset.qundo||S.thread;
  if(el.dataset.qundo)questionUndo(n);else questionPick(n,el.dataset.q,+el.dataset.qpick);
  if(key){const b=document.querySelector('#dock [data-qundo],#dock [data-qpick]');if(b)b.focus({preventScroll:true})}  // pressed with a key: the focus stays with the card
});
