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
/* has the person sent chat n words that it does not have yet? Unless they are about its question (F192a2), they answer its question, until /live says what is asked then */
const questionSpoke=(n,ob,pending,ago)=>ob.some(x=>x.name==='chat_to'&&x.args.to===n&&x.state!=='failed'&&!questionIsAbout(x.args.text))||ago<QUESTION_LAND&&pending.some(p=>p.state!=='failed'&&!questionIsAbout(p.text));
/* may the held answer still go? Not once /live says the question is gone or another; with no word of it, it may */
const questionOpen=(live,id)=>!live||!live.ok||!!(live.ask&&live.ask.id===id);
/* a question, as QN.gone (F192b, dismissed) and QN.min (F437a, minimized) have it */
const questionKey=(n,id)=>n+' '+id;
/* F437c: is the reader away from the bottom? o: up (px the history is scrolled from its end), off (px the frame is pulled),
   jump (the terminal itself is scrolled). was: they were; it takes more to go than to stay, so the edge does not flicker */
const QUESTION_EDGE=24, QUESTION_BACK=150;  // px; ms at the bottom before the card is back
const questionFar=(was,o)=>!!o.jump||Math.max(o.up||0,o.off||0)>(was?1:QUESTION_EDGE);
/* the agent CLI's own Jump to bottom pill, on a screen too low for feedFoot to find its prompt: by its place, the middle,
   and its ground (lit), which the same words in an answer do not have */
const questionPill=(lines,cols,lit)=>lines.some((l,y)=>[...l.matchAll(FEED_PILL)].some(m=>{
  const at=feedCells(l.slice(0,m.index));return Math.abs(at-(cols-feedCells(m[0].trim())-2)/2)<1&&lit(y,at+2)}));
const questionIcon=d=>`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg>`;
const questionLabel=o=>o.name+(o.rec?' (recommended)':'');
function questionHTML(n,ask,held,sent,min){
  const st=questionState(ask,held,sent);if(!st)return '';
  if(st==='held')return `<div class="card qcard qheld" role="status" data-k="question:${esc(n)}" data-v="held"><div class="row"><span class="grow">Sending “${esc(held.name)}”</span><button type="button" class="btn" data-qundo="${esc(n)}">Undo</button></div></div>`;
  if(min)return `<div class="card qcard qmin" role="group" aria-label="Question, minimized" data-k="question:${esc(n)}" data-v="min:${esc(ask.id)}"><div class="row qrow" data-qrowshow="${esc(ask.id)}"><span class="grow ell">${esc(ask.question)}</span><button type="button" class="icon" data-qshow="${esc(ask.id)}" aria-label="Show question" title="Show question">${questionIcon('M6 15l6-6 6 6')}</button></div></div>`;
  return `<div class="card qcard" role="group" aria-label="Question" data-k="question:${esc(n)}" data-v="${esc(ask.id)}"><div class="row qtop qrow" data-qrowmin="${esc(ask.id)}"><span class="grow q">${esc(ask.question)}</span><button type="button" class="icon" data-qmin="${esc(ask.id)}" aria-label="Minimize question" title="Minimize question">${questionIcon('M5 12h14')}</button></div>${ask.options.map((o,i)=>`<button type="button" class="btn${o.rec?' pri':''}" data-qpick="${i}" data-q="${esc(ask.id)}">${esc(questionLabel(o))}</button>`).join('')}${questionChatHTML(ask)}</div>`;
}
