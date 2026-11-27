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
const needSame=s=>String(s||'').replace(/[`.]+(?=\s|$)|`/g,'').trim().toLowerCase();  // a title has no quote marks or full stop
const needTitle=n=>{const d=needD(n);if(needText(n)&&needWho(n))return needWho(n);return d.title!==n.id&&needSame(d.title)!==needSame(needAsk(n))?d.title:''};
/* B809c: a control session's question has the message that explains it (detail.text): card and popup say it, and the
   session's name and project stand where the title does. An item without one has none of this */
const needText=n=>needD(n).text||'';
const needWho=n=>{const d=needD(n);return [d.session,d.project].filter(Boolean).join(' · ')};
/* its blocks: {k: 'p' | 'h' | 'li' | 'pre' | 'table', s: words, deep, n: an ordered item's number}. Pictures are shown below it, so
   their markup is only its caption (a web one's a link); a link that is no web address is only its words */
function explainBlocks(src){
  const out=[];let code=null,gap=true;
  const say=s=>s.replace(/!\[([^\]]*)\]\((https?:[^)]*)\)/gi,(_,w,u)=>`[${w||'Picture'}](${u})`).replace(/!\[([^\]]*)\]\([^)]*\)/g,'$1').replace(/\[([^\]]+)\]\((?!https?:\/\/)[^)]*\)/gi,'$1');
  for(const raw of String(src||'').replace(/\t/g,'  ').split('\n')){
    const l=raw.trim().replace(/^>\s?/,''), last=out[out.length-1];let m;
    if(code!==null){if(/^(```|~~~)/.test(l)){out.push({k:'pre',s:code.join('\n')});code=null;gap=true}else code.push(raw);continue}
    if(/^(```|~~~)/.test(l)){code=[];continue}
    if(!l||/^([-*_])(\s*\1){2,}$/.test(l)){gap=true;continue}
    const deep=Math.min(2,Math.floor((raw.length-raw.trimStart().length)/2)), inList=last&&last.k==='li';
    if(/^\|.*\|$/.test(l)){if(last&&last.k==='table'&&!gap)last.s+='\n'+l;else out.push({k:'table',s:l})}
    else if(m=/^#{1,6}\s+(.*)$/.exec(l))out.push({k:'h',s:say(m[1])});
    else if(m=/^(?:[-*+•]|(\d{1,3})[.)])\s+(.*)$/.exec(l))out.push({k:'li',n:m[1]?+m[1]:0,deep,s:say(m[2])});
    else if(last&&(!gap&&/^(p|li)$/.test(last.k)||inList&&deep))last.s+=(last.k==='li'?' ':'\n')+say(l);
    else if(say(l))out.push({k:'p',s:say(l)});
    gap=false;
  }
  if(code)out.push({k:'pre',s:code.join('\n')});
  return out.filter(b=>b.s.trim());
}
/* a line's marks: `code`, web links, bold and italic. What is done is held aside, so nothing in it is read again */
function explainInline(s){
  const held=[], hold=h=>`\u0001${held.push(h)-1}\u0002`, back=h=>{for(let i=0;i<4&&/\u0001/.test(h);i++)h=h.replace(/\u0001(\d+)\u0002/g,(_,j)=>held[j]);return h};
  const link=(u,w)=>hold(`<a href="${E_(u)}" target="_blank" rel="noopener noreferrer">${w}</a>`);
  const marks=t=>t.replace(/\*\*(\S(?:.*?\S)?)\*\*/g,'<b>$1</b>').replace(/(^|[\s(])\*(\S(?:[^*]*\S)?)\*(?![\w*])/g,'$1<i>$2</i>').replace(/(^|[\s(])_(\S(?:[^_]*\S)?)_(?!\w)/g,'$1<i>$2</i>');
  const t=String(s).replace(/[\u0001\u0002]/g,'').replace(/(`+)(.+?)\1(?!`)/g,(_,q,c)=>hold(`<code>${E_(c.trim())}</code>`))
    .replace(/\[([^\]]+)\]\(<?(https?:\/\/(?:[^\s()<>]|\([^\s()]*\))+)>?(?:\s+"[^"]*")?\)/gi,(_,w,u)=>link(u,marks(E_(w))))
    .replace(/https?:\/\/[^\s<>"`\u0001\u0002]+/gi,u=>{const end=/(?:[.,;:!?'*_\]]|\*\*)+$/.exec(u);let v=end?u.slice(0,end.index):u;
      while(v.endsWith(')')&&v.split('(').length<v.split(')').length)v=v.slice(0,-1).replace(/[.,;:!?]+$/,'');
      return link(v,E_(v))+u.slice(v.length)});
  return back(marks(E_(t))).replace(/\n/g,'<br>');
}
function explainTable(s){
  const rows=s.split('\n').map(r=>r.slice(1,-1).split(/(?<!\\)\|/).map(c=>c.trim().replace(/\\\|/g,'|'))), head=rows[1]&&rows[1].every(c=>/^:?-+:?$/.test(c));
  return `<div class="explaintab"><table>${rows.map((r,i)=>head&&i===1?'':`<tr>${r.map(c=>head&&!i?`<th>${explainInline(c)}</th>`:`<td>${explainInline(c)}</td>`).join('')}</tr>`).join('')}</table></div>`;
}
function explainHTML(blocks){
  let h='',open='';const shut=()=>{if(open)h+=`</${open}>`;open=''};
  for(const b of blocks){
    if(b.k!=='li')shut();
    if(b.k==='li'){const t=b.n?'ol':'ul';if(open!==t){shut();h+=`<${t}>`;open=t}
      h+=`<li${b.n?` value="${b.n}"`:''}${b.deep?` class="deep${b.deep}"`:''}>${explainInline(b.s)}</li>`}
    else h+=b.k==='pre'?`<pre><code>${E_(b.s)}</code></pre>`:b.k==='table'?explainTable(b.s):`<${b.k==='h'?'h3':'p'}>${explainInline(b.s)}</${b.k==='h'?'h3':'p'}>`;
  }
  shut();return h;
}
/* where a sentence ends: not inside a mark, a link's address or after an abbreviation */
function explainEnds(s){
  const out=[];
  for(const m of s.matchAll(/[.!?]["'”’)*_]*(?=\s+\S)|\n/g)){
    const a=s.slice(0,m.index+m[0].length);
    if(/\b(?:e\.g|i\.e|vs|etc|approx|no)\.$/i.test(a)||/(?:^|\s)\d{1,3}\.$/.test(a)||a.split('`').length%2===0||a.split('**').length%2===0||/\[[^\]]*$/.test(a)||/\]\([^)]*$/.test(a))continue;
    if(m[0]==='\n'||/^\s+[^a-z\s]/.test(s.slice(a.length)))out.push(a.length);
  }
  return out;
}
/* its first sentence, for the card: of the first words that are no heading */
function explainFirst(src){
  const bs=explainBlocks(src), b=bs.find(x=>x.k==='p'||x.k==='li')||bs.find(x=>x.k==='h');if(!b)return '';
  return b.s.slice(0,explainEnds(b.s)[0]??b.s.length).replace(/\[([^\]]+)\]\(https?:[^)]*\)+/gi,'$1').replace(/\*\*(\S(?:.*?\S)?)\*\*/g,'$1').replace(/(^|[\s(])[*_](\S(?:[^*_]*\S)?)[*_](?!\w)/g,'$1$2').trim();
}
/* [what is always shown, the rest, folded]: a text longer than EXPLAIN_LONG characters, at a block, else a sentence */
const EXPLAIN_LONG=600, EXPLAIN_HEAD=320;
function explainCut(src){
  const bs=explainBlocks(src), size=b=>b.s.length;
  if(bs.reduce((n,b)=>n+size(b),0)<=EXPLAIN_LONG)return[bs,[]];
  let n=0,i=0;while(i<bs.length&&n+size(bs[i])<=EXPLAIN_HEAD){n+=size(bs[i]);i++}
  const head=bs.slice(0,i), rest=bs.slice(i), b=rest[0];
  if(head.every(x=>x.k==='h')){  // no words yet: the next block's first part
    const [a,z]=explainSplit(b);
    return[[...head,a],z?[z,...rest.slice(1)]:rest.slice(1)];
  }
  while(head.length>1&&head[head.length-1].k==='h')rest.unshift(head.pop());  // a heading stays with its words
  return[head,rest];
}
/* a long block in two: code and a table at a line (a table's head on both), words at a sentence, else a space; [b] when it cannot be */
function explainSplit(b){
  if(b.s.length<=EXPLAIN_LONG)return[b];
  if(b.k==='pre'||b.k==='table'){
    const ls=b.s.split('\n'), top=b.k==='table'&&/^\|[\s:|-]+\|$/.test(ls[1]||'')?2:0;let k=top,n=0;
    while(k<ls.length&&(k===top||n+ls[k].length<=EXPLAIN_HEAD))n+=ls[k++].length;
    return k<ls.length?[{...b,s:ls.slice(0,k).join('\n')},{...b,s:[...ls.slice(0,top),...ls.slice(k)].join('\n')}]:[b];
  }
  const ends=explainEnds(b.s).filter(e=>e<=EXPLAIN_LONG), whole=a=>a.split('`').length%2&&a.split('**').length%2&&!/\[[^\]]*$|\]\([^)]*$/.test(a);
  let at=ends.filter(e=>e<=EXPLAIN_HEAD).pop()||ends[0]||0;
  if(!at)for(const m of b.s.slice(0,EXPLAIN_LONG).matchAll(/\s/g))if(whole(b.s.slice(0,m.index)))at=m.index;
  return at&&b.s.slice(at).trim()?[{...b,s:b.s.slice(0,at)},{...b,k:'p',s:b.s.slice(at).trim()}]:[b];
}
/* on: the rest is open */
function needExplain(n,on,chev=''){
  if(!needText(n))return '';
  const [head,rest]=explainCut(needText(n));
  return `<div class="explain">${explainHTML(head)}</div>`+(rest.length?`<button class="fold" data-k="askfold:text" data-askfold="text" aria-expanded="${!!on}"><span class="grow"><b>The rest of the explanation</b></span><span class="chev">${chev}</span></button>${on?foldIn('ask:text',`<div class="explain">${explainHTML(rest)}</div>`):''}`:'');
}
const needHead=n=>askWords(needAsk(n));
/* the card's words, one button that opens the popup: what is wanted and where, what is asked, the title, a
   DECIDE's background; nothing of it is cut */
const askChip=(n,kinds)=>/^[A-Za-z]+\d/.test(n.id)?kindChip(n.id,kinds):'';  // F195b: a tool or a pitch has no kind
function needTap(n,kinds){const d=needD(n), k=d.steps.length, t=needTitle(n), say=[d.question?d.lead.join(' '):'',explainFirst(d.text)].filter(Boolean);
  return `<button class="asktap" data-needopen="${E_(n.id)}" aria-haspopup="dialog"><span class="askkind">${askChip(n,kinds)}<span class="asklab">${E_(needLab(n))}</span></span><b class="q">${needHead(n)}</b>${t?`<span class="small">${E_(t)}</span>`:''}${say.map(x=>`<span class="askdo">${askWords(x)}</span>`).join('')}<span class="small">${['Press for details',k>1?`${k} steps`:'',askChip(n,kinds)?'':E_(n.id),E_(n.age||'')].filter(Boolean).join(' · ')}</span></button>`}
/* F197b3: what a Needs you item's details popup tells the run when it opens on a concept that is New or Updated
   ({concept, version} for concept_opened), else null: only the popup clears them, never View */
function conceptSeen(id,concepts){const c=(concepts||[]).find(x=>x.id===id||(x.concept||'')===id);
  return c&&c.news&&c.version?{concept:c.concept||c.id,version:c.version}:null}
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
/* the popup's lists and pictures; url: a picture's address; give: its inputs' fields; on: the explanation's fold is open */
function needBody(n,url,give='',on=false,chev=''){const d=needD(n), more=d.step_more||[], list=(t,h,xs)=>xs.length?`<section><h3>${h}</h3><${t}>${xs.map((x,j)=>`<li>${askWords(x)}${t==='ol'?stepMore(more[j],j):''}</li>`).join('')}</${t}></section>`:'';
  const why=(d.why||[]).filter(x=>needSame(x)!==needSame(needAsk(n)));  // B794: why a BLOCKED stopped; a run without it has none
  return needExplain(n,on,chev)+(why.length?`<section><h3>Why</h3>${why.map(x=>`<p>${askWords(x)}</p>`).join('')}</section>`:'')+d.lead.map(x=>`<p>${askWords(x)}</p>`).join('')+list('ol','What to do',d.steps)+list('ul','What you should see',d.expect)+give
    +d.notes.filter(x=>!needInputs(n).length||!/^Reply (done once it is|yes\/no)$/i.test(x)).map(x=>`<p class="small">${askWords(x)}</p>`).join('')
    +needVideos(d.shots,url)
    +(d.shots.some(s=>!s.video)?`<section><h3>Pictures</h3><div class="shots">${d.shots.map((s,j)=>s.video?'':`<button class="shot" data-shot="${j}" aria-label="Open the picture: ${E_(s.caption||'no caption')}"><img src="${E_(url(s))}" alt="${E_(s.caption||'Picture')}" loading="lazy"></button>`).join('')}</div></section>`:'')}
/* F445a: an item's videos, each in place with its caption. #t: an iPhone draws no first frame without it */
function needVideos(shots,url){const vs=shots.filter(s=>s.video);
  return vs.length?`<section><h3>${vs.length>1?'Videos':'Video'}</h3>${vs.map(s=>`<video class="shotvideo" data-video controls playsinline preload="metadata" src="${E_(url(s))}#t=0.001" aria-label="${E_(s.caption||'Video')}"></video>${s.caption?`<p class="small">${E_(s.caption)}</p>`:''}`).join('')}</section>`:''}
/* a task's text as paragraphs: its fields, notes, block and numbered parts each on their own */
function taskParas(text){return String(text||'').split(/\n+|(?= \| )|(?= — )|(?= BLOCKED: )|(?=\s\(?\d\)\s)/).map(x=>x.trim()).filter(Boolean)}
/* whose reply box has a button of its own: nothing else answers it, or the answers take no words with them */
function needReplies(n){return !['TOOL','PR'].includes(n.label)&&!needInputs(n).length&&(!answerOpts(n).length||['DECIDE','STUCK','PITCH'].includes(n.label))}
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
