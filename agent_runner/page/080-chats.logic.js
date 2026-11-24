function chatMove(names,pins,name,to){
  names=names||[];const rest=names.filter(n=>n!==name),p=new Set(pins||[]);
  if(names.includes(name))rest.splice(Math.max(0,Math.min(+to||0,rest.length)),0,name);
  return rest.filter(n=>p.has(n)).concat(rest.filter(n=>!p.has(n)));
}
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
/* B208: is Send a Force send? Only while the session works, with words or an attachment (uploaded, as send() takes it) */
const sendForces=(works,words,atts)=>!!works&&(!!String(words||'').trim()||(atts||[]).some(a=>a.path));
const keysLine=()=>'<span class="keysl">'+BOX_KEYS.map(([k,d])=>`${k} ${d}`).join(' · ')+'</span>';
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
