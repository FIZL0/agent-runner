/* The page's pure parts, run in node by tests/test_web.py: no DOM here. */
/* a Needs you item's possible answers (F74): yes / no for a CONFIRM or a yes-or-no ask, else its options */
function answerOpts(it){return((it&&it.answers)||[]).map(a=>a.value)}  // C33: the row's own, from ui_model.need_answers
/* F162: a Needs you card and its popup: what they say is the row's own (ui_model's detail); a run without it has the ask */
const E_=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const askWords=s=>E_(s).replace(/`([^`]+)`/g,'<code>$1</code>');  // `code` as code
function needD(n){const ask=n.ask||n.title||n.what||'';
  if(!n.detail&&n.label==='DECIDE')return{said:'Choose',title:n.title||n.id,where:'',summary:ask,question:ask,lead:[],steps:[],expect:[],notes:[],shots:[]};
  return n.detail||{said:'Needs you',title:n.title||n.id,where:'',summary:ask,lead:[],steps:[ask],expect:[],notes:[],shots:[]}}
const needLab=n=>{const d=needD(n);return d.said+(d.where?` · ${d.where}`:'')};
/* B793a: the heading is what is asked (a DECIDE's question, the rest's summary), whole, with the task's title small under it ('' when it adds nothing) */
const needAsk=n=>{const d=needD(n);return d.question||d.summary||d.title};
const needTitle=n=>{const d=needD(n);return d.title!==n.id&&d.title!==needAsk(n)?d.title:''};
const needHead=n=>askWords(needAsk(n));
/* the card's words, one button that opens the popup: what is wanted and where, what is asked, the title, a
   DECIDE's background; nothing of it is cut */
function needTap(n){const d=needD(n), k=d.steps.length, t=needTitle(n), say=d.question?d.lead.join(' '):'';
  return `<button class="asktap" data-needopen="${E_(n.id)}" aria-haspopup="dialog"><span class="asklab">${E_(needLab(n))}</span><b class="q">${needHead(n)}</b>${t?`<span class="small">${E_(t)}</span>`:''}${say?`<span class="askdo">${askWords(say)}</span>`:''}<span class="small">${['Press for details',k>1?`${k} steps`:'',E_(n.id),E_(n.age||'')].filter(Boolean).join(' · ')}</span></button>`}
/* F175a: a step's link to open and its command to copy */
function stepMore(m,j){if(!m)return '';
  return (/^https?:/i.test(m.link||'')?`<div class="btns"><a class="btn" href="${E_(m.link)}" target="_blank" rel="noopener noreferrer">Open</a></div>`:'')
    +(m.cmd?`<div class="small">Run on ${E_(m.on||'this machine')}</div><pre class="out" data-stepcmd="${j}"><code>${E_(m.cmd)}</code></pre><div class="btns"><button class="btn" data-stepcopy="${j}">Copy</button></div>`:'')}
/* F175a: the inputs of a Needs you item, a field each; o: secure (a secret may be sent from this page), field and out
   (the input that was refused, and why). No value is in the markup: keepFields() puts it back */
const needInputs=n=>needD(n).inputs||[];
const giveField=(id,x)=>`${x.kind==='secret'?'givesec':'give'}:${id}:${x.key}`;
const GIVE_HTTP='No secret is taken here: this page came over plain http, where others on the network could read it. Open its https link (run status prints it when Tailscale Serve gives one), or open the page on the machine the run is on.';
function giveHTML(n,o){const xs=needInputs(n);
  return xs.length?`<section><h3>What to enter</h3>${xs.map((x,j)=>{
    if(x.kind==='secret'&&!o.secure)return `<div class="give"><span>${E_(x.label)}</span><div class="small v-bad">${GIVE_HTTP}</div></div>`;
    const bad=o.field===x.key;
    return `<label class="give"><span>${E_(x.label)}</span><input class="fld" data-f="${E_(giveField(n.id,x))}" ${x.kind==='secret'?'type="password" autocomplete="new-password"':`type="text"${x.kind==='link'?' inputmode="url"':''} autocomplete="off"`} autocapitalize="off" autocorrect="off" spellcheck="false"${bad?` aria-invalid="true" aria-describedby="giveout${j}"`:''}>${bad?`<span class="small v-bad" id="giveout${j}" role="alert">${E_(o.out)}</span>`:''}</label>`}).join('')}${o.done||''}</section>`:''}
/* the popup's lists and pictures; url: a picture's address; give: its inputs' fields */
function needBody(n,url,give=''){const d=needD(n), more=d.step_more||[], list=(t,h,xs)=>xs.length?`<section><h3>${h}</h3><${t}>${xs.map((x,j)=>`<li>${askWords(x)}${t==='ol'?stepMore(more[j],j):''}</li>`).join('')}</${t}></section>`:'';
  return d.lead.map(x=>`<p>${askWords(x)}</p>`).join('')+list('ol','What to do',d.steps)+list('ul','What you should see',d.expect)+give
    +d.notes.filter(x=>!needInputs(n).length||!/^Reply (done once it is|yes\/no)$/i.test(x)).map(x=>`<p class="small">${askWords(x)}</p>`).join('')
    +(d.shots.length?`<section><h3>Pictures</h3><div class="shots">${d.shots.map((s,j)=>`<button class="shot" data-shot="${j}" aria-label="Open the picture: ${E_(s.caption||'no caption')}"><img src="${E_(url(s))}" alt="${E_(s.caption||'Picture')}" loading="lazy"></button>`).join('')}</div></section>`:'')}
/* a task's text as paragraphs: its fields, notes, block and numbered parts each on their own */
function taskParas(text){return String(text||'').split(/\n+|(?= \| )|(?= — )|(?= BLOCKED: )|(?=\s\(?\d\)\s)/).map(x=>x.trim()).filter(Boolean)}
/* whose reply box has a button of its own: nothing else answers it, or the answers take no words with them */
function needReplies(n){return n.label!=='TOOL'&&!needInputs(n).length&&(!answerOpts(n).length||['DECIDE','STUCK','PITCH'].includes(n.label))}
/* B138: an answered item stays off Needs you for a while (GONE_MS), so a snapshot taken before the answer landed
   does not bring a stale card back; gone maps an id to when it was answered */
const GONE_MS=30000;
function goneMark(gone,r,now){const g={...(gone||{})};if(r&&r.ok&&r.gone)g[r.gone]=now;return g}
function needsShown(needs,gone,now){return(needs||[]).filter(n=>!(gone&&gone[n.id]!=null&&now-gone[n.id]<GONE_MS))}
/* what the toast says once an answer button's command ran: the run's own words ('R13 ticked'), else the reply */
function answerSaid(r,id,v){return(r&&r.said)||(r&&r.gone?`${id}: ${v}`:`Sent to a new chat: ${id} ${v}`)}
/* F93: Talk's words: a session's feed entries as a conversation, yours {w:'u'} and the replies {w:'a'}; k, its entry's id */
function talkMsgs(entries){return(entries||[]).filter(e=>e.kind==='you'||e.kind==='say').map(e=>({w:e.kind==='you'?'u':'a',text:e.text,...(e.id?{k:e.id}:{})}))}
/* F114: what a chat or slot shows. o: stand (a chat still starting, '@cid'), starting (its first message went), info
   (/terminal/NAME's answer, null before it), chat (cN). 'session': the real one; the rest say why there is none */
