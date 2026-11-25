/* --- F192a1: the question card: the question the open chat's last answer ends on (/live's `ask`) ------------------ */
const QUESTION_HOLD=5000, QUESTION_AGAIN=500, QUESTION_LAND=10000;  // ms: an answer waits this long with Undo; a second tap on the same spot is not a new press; a sent message hides the card this long at most, /live knows by then
/* what stands above the box: 'held' (an answer waits, with Undo), 'ask' (the card), '' nothing. sent: the answer that went */
function questionState(ask,held,sent){
  if(held)return 'held';
  if(!ask||!ask.id||!(ask.options||[]).length)return '';
  return sent&&sent.id===ask.id&&!sent.back?'':'ask';
}
/* an answer that went, at a draw: while the outbox has it, it stands; once it is out, it either went (`at`: when the
   chat's last message went) or was discarded, which brings the card back */
function questionSent(sent,ob,at){
  if(!sent||sent.over||ob.some(x=>x.cid===sent.cid))return sent;
  return{...sent,over:true,back:!(at>=sent.at)};
}
/* has the person sent chat n words that it does not have yet? They answer its question, until /live says what is asked then */
const questionSpoke=(n,ob,pending,ago)=>ob.some(x=>x.name==='chat_to'&&x.args.to===n&&x.state!=='failed')||ago<QUESTION_LAND&&pending.some(p=>p.state!=='failed');
/* may the held answer still go? Not once /live says the question is gone or another; with no word of it, it may */
const questionOpen=(live,id)=>!live||!live.ok||!!(live.ask&&live.ask.id===id);
const questionLabel=o=>o.name+(o.rec?' (recommended)':'');
function questionHTML(n,ask,held,sent){
  const st=questionState(ask,held,sent);if(!st)return '';
  if(st==='held')return `<div class="card qcard qheld" role="status" data-k="question:${esc(n)}" data-v="held"><div class="row"><span class="grow">Sending “${esc(held.name)}”</span><button type="button" class="btn" data-qundo="${esc(n)}">Undo</button></div></div>`;
  return `<div class="card qcard" role="group" aria-label="Question" data-k="question:${esc(n)}" data-v="${esc(ask.id)}"><div class="q">${esc(ask.question)}</div>${ask.options.map((o,i)=>`<button type="button" class="btn${o.rec?' pri':''}" data-qpick="${i}" data-q="${esc(ask.id)}">${esc(questionLabel(o))}</button>`).join('')}</div>`;
}
