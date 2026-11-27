/* --- F466d: the Tools page's terminal: a shell on this machine, over https or loopback only. What is typed and shown
   stays in this tab (S.term) and the run's memory; nothing keeps it. Its output is drawn straight into #termout, so the
   sheet's markup never changes while it runs. */
const TERM_KEYS=[['Ctrl-C','\x03'],['Ctrl-D','\x04'],['Esc','\x1b'],['Tab','\t'],['↑','\x1b[A'],['↓','\x1b[B'],['←','\x1b[D'],['→','\x1b[C']];
function terminalHTML(){
  const d=S.tools||{}, off=d.secure?'':'disabled', n=d.terminals||0;
  return `<div class="sec">Terminal<span class="ln"></span></div>${card(`<b>Terminal</b><div class="small">A shell on this machine as the runner's user, for a command you would type here. Agents cannot open or read it, and nothing typed is kept. It ends when you close it, close the tab, or after 15 min with nothing typed.</div>
    <div class="btns"><button class="btn pri" data-tool="termopen" data-where="project" ${off}>Open in the project</button><button class="btn" data-tool="termopen" data-where="home" ${off}>Open in home</button>${n?`<button class="btn bad" data-tool="termendall">End every terminal (${n})</button>`:''}</div>`)}`;
}
SHEETS.terminal=()=>`<h2>Terminal</h2><pre class="out termout" id="termout" role="log" aria-live="off"></pre>
  <div class="btns termkeys" role="group" aria-label="Keys">${TERM_KEYS.map(([l],i)=>`<button class="btn" data-tool="termkey" data-i="${i}">${l}</button>`).join('')}<button class="btn" data-tool="termcopy">Copy</button><button class="btn" data-tool="termpaste">Paste</button></div>
  <label class="small">Command<input class="fld" id="termin" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="send"></label>
  <div class="small" id="termsaid" role="status"></div>
  <div class="btns"><button class="btn pri" data-tool="termenter">Send</button><button class="btn" data-tool="termclose">End and close</button></div>`;
/* what a dumb terminal draws: colour codes out, backspace and a lone carriage return applied */
function termPlain(t){
  t=t.replace(/\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]/g,'').replace(/\r\n/g,'\n');
  let o='';for(const ch of t){if(ch==='\b')o=o.slice(0,-1);else if(ch==='\r')o=o.slice(0,o.lastIndexOf('\n')+1);else if(ch>=' '||ch==='\n'||ch==='\t')o+=ch}
  return o;
}
async function termPost(body){
  try{const r=await fetch(tq('tools'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return await r.json()}
  catch(e){return {ok:false,out:'Could not reach the run page.'}}
}
function termSaid(w){const el=$('termsaid');if(el)el.textContent=w||''}
async function termPoll(){
  const t=S.term;if(!t||t.busy)return;t.busy=true;
  const j=await termPost({op:'term_read',id:t.id,at:t.at});t.busy=false;
  if(S.term!==t)return;
  if(S.sheet!=='terminal')return termEnd();  // closed some other way (Esc, Back)
  if(!j.ok){termSaid(plainOut(j,'The terminal has ended.'));return termStop()}
  t.at=j.at;if(j.data){t.text=(t.text+termPlain(j.data)).slice(-100000);const el=$('termout');if(el){el.textContent=t.text;el.scrollTop=el.scrollHeight}}
  if(j.ended){termSaid('The shell has ended.');termStop()}
}
function termStop(){const t=S.term;if(t){clearInterval(t.timer);S.term=null}}
async function termSend(data){const t=S.term;if(!t)return;const j=await termPost({op:'term_send',id:t.id,data});if(!j.ok)termSaid(plainOut(j,'That did not reach the terminal.'));termPoll()}
function termEnd(){const t=S.term;if(!t)return;termStop();termPost({op:'term_close',id:t.id})}
addEventListener('pagehide',()=>{const t=S.term;if(t&&navigator.sendBeacon)navigator.sendBeacon(tq('tools'),new Blob([JSON.stringify({op:'term_close',id:t.id})],{type:'application/json'}))});
addEventListener('keydown',e=>{if(e.target&&e.target.id==='termin'&&e.key==='Enter'){e.preventDefault();termClick({dataset:{tool:'termenter'}})}});
async function termClick(x){
  const {tool,where}=x.dataset;
  if(tool==='termopen'){
    termEnd();const j=await termPost({op:'term_open',where});
    if(!j.ok){toast(plainOut(j,'The terminal could not open.'));return}
    S.term={id:j.id,at:0,text:'',busy:false};S.term.timer=setInterval(termPoll,700);openSheet('terminal');termSaid(j.out);termPoll();return}
  if(tool==='termendall'){termStop();const j=await termPost({op:'term_close_all'});toast(plainOut(j,'That failed.'));return loadTools()}
  if(tool==='termclose'){termEnd();closeSheet();return loadTools()}
  if(tool==='termkey')return termSend(TERM_KEYS[+x.dataset.i][1]);
  if(tool==='termenter'){const el=$('termin');const v=el?el.value:'';if(el)el.value='';return termSend(v+'\n')}
  if(tool==='termcopy'){try{await navigator.clipboard.writeText(String(getSelection()||'')||(S.term||{}).text||($('termout')||{}).textContent||'');termSaid('Copied.')}catch(e){termSaid('Copy is not allowed here: hold the text to select it.')}return}
  if(tool==='termpaste'){try{const v=await navigator.clipboard.readText();const el=$('termin');if(el){el.value+=v;el.focus()}}catch(e){termSaid('Paste is not allowed here: hold the Command box and paste.')}return}
}
