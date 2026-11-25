/* --- F192a1: the question card (questionHTML and the rest in the logic script) -----------------------------------
   held: chat -> the answer that waits out its hold {id, name, at, timer}; sent: chat -> the last one that went {id, name,
   cid}; back: when an Undo brought a card back. In memory only: a reload in the hold sends nothing, the card is there again.
   F192a2: mark: chat -> the question marked above its box (over a reload too, as its draft is); marked: when the
   mark came. F430: a question talked about stays /live's ask, so its card is back on its own, on every device
   F192a3: an ask with `need` is also that item under Needs you: its answer settles the item, and one given there takes the
   card and the mark (/live's `answered`)
   F192b: gone: the questions dismissed. F437a: min: the minimized ones (both 096-dismiss.js) */
const QMARK_KEY='ar-qmark:'+(HKEY||document.title);
const QN={held:new Map(),sent:new Map(),back:0,mark:new Map(questionMarks(tabStore.get(QMARK_KEY))),marked:0,gone:new Set(),min:new Set()};
const questionAsk=n=>FD.n===n&&FD.live&&FD.live.ask||null;
const questionSpoken=n=>questionSpoke(n,S.ob,(S.sent[n]&&S.sent[n].pending)||[],Date.now()-((S.sent[n]||{}).at||0));
/* an answer to it, here or under Needs you, is on its way */
const questionSettling=ask=>!!(ask&&ask.need)&&S.ob.some(x=>x.need===ask.need&&x.state!=='failed'&&(x.name==='question_answer'||x.name==='answer'||/^need_(yes|no|answer\d+|drop)$/.test((x.args||{}).key||'')));  // not Later
/* the card of chat n, drawn over its chips (sessRow) */
function questionCard(n){
  if(!/^c\d+$/.test(n||''))return '';
  let sent=QN.sent.get(n);
  if(sent&&sent.need)questionNeedSent(n,sent);
  else if(sent=questionSent(sent,S.ob,(S.sent[n]||{}).at))QN.sent.set(n,sent);
  const mark=QN.mark.get(n);if(mark&&!QN.held.has(n))return questionMarkHTML(n,mark);
  const ask=questionAsk(n), k=ask&&questionKey(n,ask.id);
  return questionHTML(n,questionSpoken(n)||questionSettling(ask)||ask&&QN.gone.has(k)?null:ask,QN.held.get(n),sent,!!ask&&QN.min.has(k));
}
/* an answer that settles an item is out of the outbox: done or discarded, /live says whether the question is still asked */
function questionNeedSent(n,sent){
  if(!sent.cid||sent.over||S.ob.some(x=>x.cid===sent.cid))return;
  sent.over=true;
  setTimeout(async()=>{if(FD.n===n)await liveLoad();sent.back=true;if(S.thread===n)questionDraw()},0);
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
  const h={id,name:o.name,at:Date.now(),...(ask.need?{need:ask.need}:{})};
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
  const live=FD.n===n&&FD.live, over=live&&live.answered||[];
  if(over.includes((QN.mark.get(n)||{}).id))questionMark(n,null);
  const h=QN.held.get(n);if(!h||!questionSpoken(n)&&!questionSettling(h)&&(FD.n!==n||questionOpen(FD.live,h.id)))return;
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
  const moved=questionMove(n,false), it={id:h.id,name:h.name,cid:'',at:Date.now()}, ask=FD.n===n&&questionAsk(n), need=ask&&ask.id===h.id?ask.need:h.need;  // filed in the hold
  if(need){
    it.need=need;QN.sent.set(n,it);
    it.cid=outbox('question_answer',{chat:n,id:h.id,text:h.name},{need,say:`${need} · answered “${h.name}”`,done:`${need} answered: ${h.name}`}).cid;
    moved();return;
  }
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
   answers the question, as any typed message does. go(words, more) puts it in the outbox */
function questionGo(n,text,go){
  const mark=QN.mark.get(n);
  if(!mark||!questionWraps(text)){go(text,{});return}
  const moved=questionMove(n,false);
  questionMark(n,null);QN.back=Date.now();
  go(questionAbout(mark,text),{about:mark});
  moved();
}
questionOn.send=questionGo;
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
