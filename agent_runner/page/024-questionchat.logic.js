/* --- F192a2: Chat about this on the question card: words about the open question that are not its answer ----------- */
const QUESTION_ABOUT='About your question “', QUESTION_NOT='” (not my answer): ';
/* how the box's words go to chat n (send()): as they are, until 095-question.js sets its questionGo() here */
const questionOn={send:(n,text,go)=>go(text,{})};
/* what is sent for a message with the question marked above the box. A command goes as it is, and the mark stays */
const questionWraps=text=>!/^\/[a-z][\w:-]*(\s|$)/i.test(text);
const questionAbout=(ask,text)=>QUESTION_ABOUT+ask.question+QUESTION_NOT+text;
const questionIsAbout=text=>String(text||'').startsWith(QUESTION_ABOUT)&&text.includes(QUESTION_NOT);
/* the question to ask: /live's, else the one talked about (kept), which /live no longer says once the person has spoken */
const questionNow=(live,kept)=>live?live.ask||kept||null:null;
/* is the marked question still asked, so that its card comes back after the send? With no word of /live, it is */
const questionStill=(live,kept,mark)=>{const ask=questionNow(live,kept);return !live||!live.ok||!!ask&&ask.id===mark.id};
/* the marks a reload kept, as drafts are: [[chat, its question]] */
function questionMarks(text){
  let l;try{l=JSON.parse(text||'[]')}catch(e){return[]}
  return Array.isArray(l)?l.filter(x=>Array.isArray(x)&&/^c\d+$/.test(x[0])&&x[1]&&typeof x[1].id==='string'&&typeof x[1].question==='string'&&Array.isArray(x[1].options)):[];
}
const questionChatHTML=ask=>`<button type="button" class="btn qchat" data-qchat="${esc(ask.id)}">Chat about this</button>`;
/* the question, marked above the box */
const questionMarkHTML=(n,ask)=>`<div class="card qcard qabout" role="group" aria-label="Chat about this question" data-k="question:${esc(n)}" data-v="about:${esc(ask.id)}"><div class="row"><span class="grow"><span class="small">Chat about this, not your answer</span><span class="q">${esc(ask.question)}</span></span><button type="button" class="icon" data-qunchat="${esc(n)}" aria-label="Back to the question" title="Back to the question">✕</button></div></div>`;
