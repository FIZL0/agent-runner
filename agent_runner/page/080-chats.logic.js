function chatMove(pins,name,to){
  pins=pins||[];const rest=pins.filter(n=>n!==name);
  if(pins.includes(name))rest.splice(Math.max(0,Math.min(+to||0,rest.length)),0,name);
  return rest;
}
/* F201: the chats as the sidebar lists them: the pinned ones in their own order, then newest to oldest by last activity
   (at; with none yet it just came up: first), the highest number first when that is the same */
function chatSort(rows,pins){
  const p=pins||[], pin=s=>{const i=p.indexOf(s.name);return i<0?p.length:i}, no=s=>+s.name.slice(1), at=s=>s.at>0?s.at:Infinity;
  return(rows||[]).slice().sort((a,b)=>pin(a)-pin(b)||(at(a)===at(b)?no(b)-no(a):at(b)>at(a)?1:-1));
}
/* F201: the sidebar's two lists of rows with the chats still starting (stand, the newest last) first under the pins.
   was: {top, quiet}, the names as last drawn; held: the name of a row that must not move: the rows keep their places (one that got its name, was '@cid', too),
   and what is new goes last in that row's list */
function chatPlaces(g,stand,pins,was,held){
  const pinned=g.top.filter(s=>(pins||[]).includes(s.name)), up=(stand||[]).slice().reverse();
  const now={top:pinned.concat(up,g.top.filter(s=>!pinned.includes(s))),quiet:g.quiet};
  if(!held||!was||!was.top.concat(was.quiet).includes(held))return now;
  const all=now.top.concat(now.quiet), keep=l=>l.map(n=>all.find(s=>s.name===n||s.was===n)).filter(Boolean);
  const fresh=all.filter(s=>![s.name,s.was].some(n=>n&&was.top.concat(was.quiet).includes(n))), low=was.quiet.includes(held);
  return{top:keep(was.top).concat(low?[]:fresh),quiet:keep(was.quiet).concat(low?fresh:[])};
}
/* F206: the kept screens, the last KEPT_MAX chats' (a Map, the newest last) */
const KEPT_MAX=12;
function keptPut(kept,n,x){kept.delete(n);kept.set(n,x);while(kept.size>KEPT_MAX)kept.delete(kept.keys().next().value);return[...kept.keys()]}
/* a chat's last line, from its feed: the last line the agent said, your own words, or, while it works, its tool step */
function chatLast(entries,works){
  for(const e of (entries||[]).slice().reverse()){
    const l=String(e.text||'').split('\n').map(x=>x.trim()).filter(Boolean);if(!l.length)continue;
    if(e.kind==='say')return l[l.length-1];
    if(e.kind==='you')return'You: '+l[0];
    if(e.kind==='tool'&&works)return'Working: '+l[0];
  }
  return'';
}
/* what stands in for a screen not seen yet: the latest messages, oldest first */
function standMsgs(entries){return(entries||[]).filter(e=>(e.kind==='say'||e.kind==='you')&&String(e.text||'').trim()).slice(-8).map(e=>({w:e.kind==='you'?'u':'a',text:e.text}))}
/* B119: the message box's slash command menu. SLASH_FALLBACK, the commands it offers when the run page cannot
   give the session's own list (/commands) */
const SLASH_FALLBACK=[['run',"The run's status"],['since','What the run did since the last look'],['follow','Follow the run live'],
  ['control','Open another control session'],['pause','Pause the run, or go on'],['stop','Stop the run'],
  ['slots','More or fewer agents'],['clear','Start the conversation over'],['compact','Summarise the conversation so far to free context']]
  .map(([name,desc])=>({name,desc}));
/* the commands that match the box: only while it holds one word that starts with '/', names that start with what
   follows first, then names that hold it; [] closes the menu */
function slashMatches(cmds,text){
  const m=/^\/(\S*)$/.exec(String(text||''));if(!m)return[];
  const q=m[1].toLowerCase(), cs=cmds&&cmds.length?cmds:SLASH_FALLBACK, nm=c=>String(c.name).toLowerCase();
  return cs.filter(c=>nm(c).startsWith(q)).concat(cs.filter(c=>!nm(c).startsWith(q)&&nm(c).includes(q)));
}
/* the box's words once a command is picked */
const slashPick=c=>`/${c.name} `;
/* the highlighted row after ArrowDown / ArrowUp, wrapping round the n rows */
const slashMove=(i,n,key)=>n?(key==='ArrowUp'?(i-1+n)%n:(i+1)%n):0;
/* B120: the message box's keys, as in the agent CLI's own input, listed here once (the box's foot shows them) */
const BOX_KEYS=[['Enter','sends'],['Shift+Enter','new line'],['↑ ↓','earlier messages'],['/','commands'],
  ['Esc','closes the menu, then interrupts'],['Ctrl+C','interrupts'],['Paste','attaches pictures or files']];
/* B181: what a key does in a message box: 'send', 'line' (Enter left to the box: a new line) or '' (not Enter, or an
   input method still composing, which Safari ends with keyCode 229). On touch only Ctrl/Cmd+Enter sends */
const composing=e=>!!e.isComposing||e.keyCode===229;
const boxEnter=(e,touch)=>e.key!=='Enter'||composing(e)?'':(touch?e.ctrlKey||e.metaKey:!e.shiftKey)?'send':'line';
/* F205: is there something to send (words or an uploaded attachment), and is an attachment still uploading? */
const sendHas=(words,atts)=>!!String(words||'').trim()||(atts||[]).some(a=>a.path);
const sendWaits=atts=>(atts||[]).some(a=>!a.path&&!a.err);
/* F406g: noSlash: a chat that takes no commands */
const keysLine=noSlash=>'<span class="keysl">'+BOX_KEYS.filter(([k])=>!noSlash||k!=='/').map(([k,d])=>`${k} ${d}`).join(' · ')+'</span>';
/* B120: the chat's message history (kept per chat): HIST_MAX the most it keeps; histPush the list once `text` is
   sent (not twice in a row); histEdge whether ArrowUp / ArrowDown leaves the box's text for history (the caret on
   its first / last line, nothing selected); histStep the place after the key, n meaning the unsent draft */
const HIST_MAX=100;
function histPush(list,text){
  const t=String(text||'').trim(), l=(Array.isArray(list)?list:[]).filter(x=>typeof x==='string');
  if(!t||l[l.length-1]===t)return l;
  return l.concat([t]).slice(-HIST_MAX);
}
function histEdge(value,start,end,key){
  const v=String(value||'');if(start!==end)return false;
  return key==='ArrowUp'?!v.slice(0,start).includes('\n'):!v.slice(end).includes('\n');
}
function histStep(n,i,key){
  if(typeof i!=='number'||i<0||i>n)i=n;
  return key==='ArrowUp'?Math.max(0,i-1):Math.min(n,i+1);
}
/* F137: the outbox: every action the page takes is drawn at once and kept here (localStorage) until the run
   answers, then sent in order; a dropped connection or a reload sends it again with the same client id (cid),
   which the run page runs only once. An item: {cid, name, args, state 'sending'|'failed', err, say (its words in
   the page), and what it stands in for: newchat, need (a Needs you id), concept (a concept's id), text and key (a
   message's words and box)}. A message to a chat still starting has args.to '@' + that new chat's cid. */
const OB_STATES=['sending','failed'];
