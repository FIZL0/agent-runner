/* --- F192a1: the question card (questionHTML and the rest in the logic script) -----------------------------------
   held: chat -> the answer that waits out its hold {id, name, at, timer}; sent: chat -> the last one that went {id, name,
   cid}; back: when an Undo brought a card back. In memory only: a reload in the hold sends nothing, the card is there again.
   F192a2: mark: chat -> the question marked above its box (over a reload too, as its draft is); marked: when the
   mark came. F430: a question talked about stays /live's ask, so its card is back on its own, on every device
   F192a3: an ask with `need` is also that item under Needs you: its answer settles the item, and one given there takes the
   card and the mark (/live's `answered`)
   F192b: gone: the questions dismissed. F437a: min: the minimized ones (both 096-dismiss.js)
   F437b: keys: the question the key row was opened under, with the keyboard button
   F437c: away: the chat whose reader is scrolled up, its card hidden where it stands; awayT: it is about to be back; cls: .main's classes */
const QMARK_KEY='ar-qmark:'+(HKEY||document.title);
const QN={held:new Map(),sent:new Map(),back:0,mark:new Map(questionMarks(tabStore.get(QMARK_KEY))),marked:0,gone:new Set(),min:new Set(),keys:'',away:'',awayT:0,auto:new Set(),growT:0,done:new Set(),rowX:new Map(),cls:'false false'};
/* F192b2: /live's questions of chat n (`asks`, else `ask`); of several, the ones not dismissed or answered here */
const questionAll=n=>{const v=FD.n===n&&FD.live;return!v?[]:Array.isArray(v.asks)&&v.asks.length?v.asks:v.ask?[v.ask]:[]};
const questionAsks=n=>{const l=questionAll(n);return l.length>1?l.filter(a=>!QN.gone.has(questionKey(n,a.id))&&!QN.done.has(questionKey(n,a.id))):l};
/* the question chat n asks first, or the one of id */
const questionAsk=(n,id)=>{const l=questionAsks(n);return(id?l.find(a=>a.id===id):l[0])||null};
const questionSpoken=n=>questionSpoke(n,S.ob,(S.sent[n]&&S.sent[n].pending)||[],Date.now()-((S.sent[n]||{}).at||0));
/* an answer to it, here or under Needs you, is on its way */
const questionSettling=ask=>!!(ask&&ask.need)&&S.ob.some(x=>x.need===ask.need&&x.state!=='failed'&&(x.name==='question_answer'||x.name==='answer'||/^need_(yes|no|answer\d+|drop)$/.test((x.args||{}).key||'')));  // not Later
/* the question chat n's card may ask: not one answered in words or under Needs you, or dismissed before */
const questionShown=(n,ask)=>questionSpoken(n)||questionSettling(ask)||ask&&QN.gone.has(questionKey(n,ask.id))?null:ask;
/* F437b: the key of the question whose card is open, whole or in its hold; '' with none, or marked or minimized */
function questionUp(n){
  if(!/^c\d+$/.test(n||''))return '';
  const held=QN.held.get(n);if(held)return questionKey(n,held.id);
  const ask=QN.mark.has(n)?null:questionShown(n,questionAsk(n)), k=ask?questionKey(n,ask.id):'';
  return questionState(ask,null,QN.sent.get(n))==='ask'&&!QN.min.has(k)&&!QN.auto.has(k)?k:'';
}
/* the card of chat n, drawn over its chips (sessRow) */
function questionCard(n){
  if(!/^c\d+$/.test(n||''))return '';
  questionAwayClass();
  let sent=QN.sent.get(n);
  if(sent&&sent.need)questionNeedSent(n,sent);
  else if(sent=questionSent(sent,S.ob,(S.sent[n]||{}).at))QN.sent.set(n,sent);
  if(sent&&sent.back)QN.done.delete(questionKey(n,sent.id));  // F192b2: discarded, it is in the row again
  const mark=QN.mark.get(n);if(mark&&!QN.held.has(n))return questionMarkHTML(n,mark);
  const ask=questionAsk(n);
  const many=QN.held.has(n)?[]:questionAsks(n).filter(a=>questionShown(n,a)&&questionState(a,null,sent)==='ask');
  if(many.length>1&&!QN.min.has(questionKey(n,ask.id))&&!QN.auto.has(questionKey(n,ask.id))){questionRowKeepSoon(n);return questionRowHTML(n,many)}
  return questionHTML(n,questionShown(n,ask),QN.held.get(n),sent,!!ask&&(QN.min.has(questionKey(n,ask.id))||QN.auto.has(questionKey(n,ask.id))),many);  // F192c1: the line counts them
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
  const ask=questionAsk(n,id), o=ask&&ask.options[i];
  if(!o||questionState(ask,QN.held.get(n),QN.sent.get(n))!=='ask'||Date.now()-QN.back<QUESTION_AGAIN)return;
  const h={id,name:o.name,at:Date.now(),...(ask.need?{need:ask.need}:{}),...(questionAll(n).length>1?{of:ask}:{}),...(questionTasks(ask,o)?{tasks:questionTasks(ask,o),question:ask.question}:{})};  // F192b2: one of several; F192d2: its stored tasks
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
  const moved=questionMove(n,false), it={id:h.id,name:h.name,cid:'',at:Date.now()}, ask=FD.n===n&&questionAsk(n,h.id), need=ask?ask.need:h.need;  // filed in the hold
  if(h.of)QN.done.add(questionKey(n,h.id));  // F192b2: the row moves to the next
  if(h.tasks)return questionQueue(n,h,it,moved);
  if(need){
    it.need=need;QN.sent.set(n,it);
    it.cid=outbox('question_answer',{chat:n,id:h.id,text:h.name},{need,say:`${need} · answered “${h.name}”`,done:`${need} answered: ${h.name}`}).cid;
    moved();return;
  }
  QN.sent.set(n,{...it,over:true});  // answered, before outbox() draws
  sendHold(n,SEND_HOLD);
  if(FD.shown&&FD.n===n)feedRest();
  const text=h.of?questionAnswered(h.of,h.name):h.name;  // F192b2: of several, it names its question, so the others stay open
  it.cid=outbox('chat_to',{text,to:n,...(FD.n===n&&FD.foot&&FD.foot.text?{unsent:true}:{})},{text,key:n,say:`To ${threadTitle(n)}: ${h.name}`}).cid;
  QN.sent.set(n,it);
  moved();
}
/* F192d2: an option with stored tasks queues them at once (POST /queue, F192d1), with no message sent to the chat; the chat
   gets the one line of what was queued from the server, and the toast says it now. A failure brings the card back */
async function questionQueue(n,h,it,moved){
  QN.sent.set(n,{...it,over:true});render(true);moved();
  let j=null;try{const r=await fetch(tq('queue'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chat:n,question:h.question,option:h.name})});j=await r.json()}catch(e){j=null}
  if(j&&j.ok){toast(j.out);if(FD.n===n)await liveLoad();return}
  QN.sent.set(n,{...it,over:true,back:true});QN.done.delete(questionKey(n,h.id));
  toast(`“${h.name}” queued nothing: ${(j&&j.out)||'the run app did not answer'}`,true);
  if(S.thread===n)questionDraw();
}
/* F192a2: Chat about this: the question marked above the box, and the box in focus, in the tap itself */
function questionMark(n,ask){
  if(ask)QN.mark.set(n,ask);else QN.mark.delete(n);
  tabStore.set(QMARK_KEY,QN.mark.size?JSON.stringify([...QN.mark]):'');
}
function questionChat(n,id){
  const ask=questionAsk(n,id);if(!ask||questionState(ask,QN.held.get(n),QN.sent.get(n))!=='ask'||Date.now()-QN.back<QUESTION_AGAIN)return;
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
/* F437c: the card and its minimized line hide while the reader is scrolled up, in the history or where the terminal scrolls
   itself (.qaway); B854b: they keep no room, so the text shows down to the box; a held answer and the mark stay */
const questionAway=n=>!!n&&QN.away===n&&FD.n===n&&FD.shown&&!QN.held.has(n)&&!QN.mark.has(n);
function questionFarNow(){
  if(!FD.shown||!FD.n)return false;
  const el=pastUp()&&$('feedpast');
  return questionFar(QN.away===FD.n,{up:el?pastEnd()-el.scrollTop:0,off:FD.off,jump:FD.jump||questionPillNow()});
}
function questionPillNow(){
  const t=FD.whole&&!FD.foot&&feedTerm();if(!t)return false;
  const b=t.buffer.active;
  return questionPill(feedLines(t),t.cols,(y,x)=>{const l=b.getLine(b.baseY+y), c=l&&l.getCell(x);return!!(c&&!c.isBgDefault())});
}
/* each scroll, and each draw of the session: hidden at once, back once it stayed at the bottom */
function questionScroll(){
  const on=questionFarNow();
  if(on||!FD.shown||QN.away!==FD.n){clearTimeout(QN.awayT);QN.awayT=0;questionAwaySet(on?FD.n:'')}
  else if(!QN.awayT)QN.awayT=setTimeout(()=>{QN.awayT=0;if(!questionFarNow())questionAwaySet('')},QUESTION_BACK);
}
function questionAwaySet(n){
  if(QN.away===n)return;
  QN.away=n;
  if(n){const k=questionUp(n);if(k){QN.auto.add(k);clearTimeout(QN.growT);QN.growT=0;render(true)}}  // F511: a scroll shrinks the card to its pill
  else questionGrowSoon();
  questionAwayClass();
  if((S.keys||TOUCH()&&FD.whole)&&questionUp(FD.n))render(true);  // the key row comes or goes with it (F437b)
  if($('pastjump'))pastJumpDraw();
}
/* qkeys: the key row is there only while the card is hidden; it stands in the card's room */
function questionAwayClass(){
  const on=questionAway(FD.n), k=on?questionUp(FD.n):'', keys=!!k&&QN.keys!==k, is=`${on} ${keys}`;if(QN.cls===is)return;
  QN.cls=is;const m=document.querySelector('.main').classList;
  questionAwayMove(on,()=>{m.toggle('qaway',on);m.toggle('qkeys',keys)});
}
/* B854c: hiding and coming back slide and fade (~180ms); the room goes only once it has faded, so nothing jumps
   while it shows; calm() (reduced motion) skips it; a new turn stops the old motion where it is */
const QUESTION_MOVE=[{opacity:1,transform:'none'},{opacity:0,transform:'translateY(12px)'}];
function questionAwayMove(on,set){
  if(QN.mv){QN.mv.cancel();QN.mv=null}
  const c=document.querySelector('#dock .qcard:not(.qheld,.qabout,.qmin)'), o={ease:'--ease',dur:'--dur',fill:'both'};
  if(!on){set();const a=c&&moAnim(c,[...QUESTION_MOVE].reverse(),o);if(a){QN.mv=a;a.onfinish=()=>{a.cancel();if(QN.mv===a)QN.mv=null}}return}
  const a=c&&moAnim(c,QUESTION_MOVE,o);if(!a)return set();
  QN.mv=a;a.onfinish=()=>{if(QN.mv!==a)return;QN.mv=null;set();a.cancel()};
}
/* the room of a hidden card, over what stands under it: the jump button floats there */
function questionRoom(){
  const c=questionAway(FD.n)&&document.querySelector('#dock .qcard'), next=c&&c.nextElementSibling;
  return next?Math.max(0,next.offsetTop-c.offsetTop):0;
}
questionOn.scroll=questionScroll;questionOn.room=questionRoom;
/* F511 (K27, option B): QN.auto: the questions a scroll shrank to the Decide pill. Back at the bottom the pill stays, and
   grows into the card on a tap or after QUESTION_GROW ms still with no touch; it grows upward from where the pill
   stands, so what is under the finger does not move */
function questionGrowSoon(){
  clearTimeout(QN.growT);QN.growT=0;
  if(!QN.auto.size||QN.away)return;
  QN.growT=setTimeout(()=>{QN.growT=0;if(QN.away||questionFarNow())return;QN.auto.clear();questionDraw()},QUESTION_GROW);
}
for(const t of['touchstart','pointerdown','wheel'])document.addEventListener(t,()=>{if(QN.growT)questionGrowSoon()},{passive:true,capture:true});
document.addEventListener('click',e=>{  // before 096-dismiss.js shows it: a tap on the pill grows it now
  const el=e.target.closest('[data-qshow],[data-qrowshow]');if(!el)return;
  clearTimeout(QN.growT);QN.growT=0;QN.auto.clear();
});
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
/* F192b2: the row of several questions. ✕ dismisses one (per question id, kept as F192b's were: QN.gone); the row
   keeps its sideways place over a redraw (QN.rowX, per chat), and the count follows the card in view */
function questionDismiss(n,id){
  const ask=questionAsk(n,id);if(!ask||questionAll(n).length<2||Date.now()-QN.back<QUESTION_AGAIN)return;
  QN.gone.add(questionKey(n,id));QN.back=Date.now();
  try{store.set(QGONE_KEY,JSON.stringify([...QN.gone].slice(-100)))}catch(e){}  // 096-dismiss.js keeps them
  questionDraw();
}
function questionRowAt(r){
  const l=[...r.children], x=r.scrollLeft, o=l.length?l[0].offsetLeft:0;
  let i=0;l.forEach((c,j)=>{if(Math.abs(c.offsetLeft-o-x)<Math.abs(l[i].offsetLeft-o-x))i=j});
  const t=r.parentNode&&r.parentNode.querySelector('.qcount'), s=questionCount(i,l.length);if(t&&t.textContent!==s)t.textContent=s;
}
function questionRowKeepSoon(n){
  Promise.resolve().then(()=>{
    const r=document.querySelector('#dock .qswipe');if(!r||!r.children)return;
    const x=QN.rowX.get(n)||0;if(Math.abs(r.scrollLeft-x)>1)r.scrollLeft=x;
    questionRowAt(r);
  });
}
document.addEventListener('scroll',e=>{
  const r=e.target;if(!r||!r.classList||!r.classList.contains('qswipe'))return;
  QN.rowX.set(S.thread,r.scrollLeft);questionRowAt(r);
},{capture:true,passive:true});
document.addEventListener('click',e=>{
  const el=e.target.closest('[data-qgone]');if(!el)return;
  questionDismiss(S.thread,el.dataset.qgone);
  if(!e.detail){const b=document.querySelector('#dock [data-qgone],#dock [data-qpick]');if(b)b.focus({preventScroll:true})}
});
