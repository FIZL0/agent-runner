/* --- what the snapshot holds ------------------------------------------------------------------------------- */
/* F201: the pinned chats in the order the run keeps (F133), then the others, newest first */
const chatPins=()=>S.snap.chat_pins||[];
const chats=()=>chatSort(S.snap.sessions.filter(s=>/^c\d+$/.test(s.name)),chatPins());
const chatNames=()=>{const g=sideRows();return g.top.concat(g.quiet).filter(c=>!c.stand&&!c.response).map(c=>c.name)};
/* F133: keep the pins, in their order: shown at once, then sent to the run so every page shows the same list */
function savePins(pins){
  S.snap.chat_pins=pins;render(true);
  act('chat_order',{pins});
}
const slots=()=>S.snap.sessions.filter(s=>/^s\d+$/.test(s.name)||(!/^c\d+$/.test(s.name)&&s.task));
const working_=()=>slots().filter(s=>s.task);
const sessionOf=n=>S.snap.sessions.find(s=>s.name===n);
const isAgent=n=>!/^(c\d+|[@+].+)$/.test(n||'');  // F137: '@cid', a chat still starting, is a chat
/* F129: a chat's name, with a rename still on its way */
const chatTitle=s=>{const x=S.ob.filter(y=>y.ren===s.name&&y.state==='sending').pop();return x?x.args.title:chatName(s)};
/* B193: S.up, the open chat while it is in the top list, kept per tab: marking it seen does not drop it to Quiet.
   Looked at before each markSeen; an open quiet chat is in it only once it came up by itself */
const UP_KEY='ar-up:'+(HKEY||document.title);
S.up=tabStore.get(UP_KEY)||'';
function holdUp(){
  const n=S.thread||'', s=chats().find(x=>x.name===n);
  if(!S.seen||n&&!s&&S.up===n)return;  // a first visit takes all as read; a reload has no chats yet
  const up=s&&groupChats([s]).top.length?n:'';
  if(up!==S.up)tabStore.set(UP_KEY,S.up=up);
}
/* F128: when the person last opened each chat (its last activity then, per browser; B205: and project); the first visit takes all as read */
const SEEN_KEY='ar-seen'+(HKEY?':'+HKEY:'');
S.seen=(()=>{try{const o=JSON.parse(store.get(SEEN_KEY)||'null');return o&&typeof o==='object'?o:null}catch(e){return null}})();
function markSeen(){
  holdUp();  // B193
  if(!document.hidden)answerChatOpened(S.thread);  // F465
  const rows=(S.snap.sessions||[]).filter(x=>/^c\d+$/.test(x.name)), first=!S.seen;
  if(!rows.length||document.hidden)return;
  const open=S.thread||(S.view==='talk'?talkName():'');let moved=first;
  if(first)S.seen={};
  for(const x of rows)if((first||x.name===open)&&x.at&&S.seen[x.name]!==x.at){S.seen[x.name]=x.at;moved=true}
  if(moved)store.set(SEEN_KEY,JSON.stringify(S.seen));
}
/* F465: the chats a Needs you answer started, per browser and project: {name: 1 once opened, else 0} (answerQuiet) */
const ANSWER_CHATS_KEY='ar-answer-chats'+(HKEY?':'+HKEY:'');
const answerChatsGet=()=>{try{const o=JSON.parse(store.get(ANSWER_CHATS_KEY)||'{}');return o&&typeof o==='object'&&!Array.isArray(o)?o:{}}catch(e){return{}}};
S.answerChats=answerChatsGet();
function answerChatsPut(n,v){
  const o={...answerChatsGet(),...S.answerChats};if(o[n]===v)return;
  delete o[n];o[n]=v;const ks=Object.keys(o);for(const k of ks.slice(0,Math.max(0,ks.length-100)))delete o[k];
  store.set(ANSWER_CHATS_KEY,JSON.stringify(S.answerChats=o));
}
const answerChatCame=j=>{if(j&&j.ok&&/^c\d+$/.test(j.chat||''))answerChatsPut(j.chat,0)};
const answerChatOpened=n=>{if(n&&S.answerChats[n]===0)answerChatsPut(n,1)};
addEventListener('storage',e=>{if(e.key===ANSWER_CHATS_KEY){S.answerChats=answerChatsGet();render()}});
const replyDue=s=>needsReply(s,(S.seen||{})[s.name])&&!(S.thread===s.name&&!s.needs_reply);
const groupChats=rows=>chatGroups(rows,{pins:chatPins(),quiet:+S.snap.chat_quiet||0,now:Date.now()/1000,seen:S.seen||{},up:S.thread&&S.up});
const shownChats=()=>{const g=answerQuiet(groupChats(chats()),S.answerChats,s=>!!s.needs_reply,chatPins());return{top:g.top,quiet:quietRows(g.quiet,responseRows(S.snap.responses,S.ob,S.responseGone))}};  // F425b: the sent responses rest in Quiet
/* F425b: the sent responses with no chat yet; S.responseGone: those whose chat started, which an older snapshot may still list.
   S.responseSeen: those opened once (per browser and project, the latest) */
const responses=()=>responseRows(S.snap.responses,S.ob,S.responseGone);
const responseOf=n=>responses().find(x=>x.name===n);
const RESPONSE_SEEN_KEY='ar-seen-responses'+(HKEY?':'+HKEY:'');
const responseSeenGet=()=>{try{const l=JSON.parse(store.get(RESPONSE_SEEN_KEY)||'[]');return Array.isArray(l)?l:[]}catch(e){return[]}};
S.responseSeen=responseSeenGet();
function responseOpened(id){
  if(!S.responseSeen.includes(id))store.set(RESPONSE_SEEN_KEY,JSON.stringify(S.responseSeen=[...new Set([...S.responseSeen,...responseSeenGet(),id])].slice(-100)));
}
function responseOpen(n){const r=responseOf(n), id=n.slice('+response:'.length);S.ctx={kind:'response',id,label:r?r.label:'Sent response'};if(r)responseOpened(id)}
const responseNew=x=>S.responseSeen.includes(x.id)?'':'<span class="newlabel">new</span>';
addEventListener('storage',e=>{if(e.key===RESPONSE_SEEN_KEY){S.responseSeen=responseSeenGet();render()}});
const threadTitle=n=>{if(isNew(n))return S.ctx?S.ctx.label:'New chat';if(String(n||'')[0]==='@'){const x=S.ob.find(y=>'@'+y.cid===n);return x?x.say:(bornSay(n,S.came,S.ob)||'New chat')}const s=sessionOf(n);if(!s)return bornSay(n,S.came,S.ob)||n;return isAgent(n)?(s.title||s.task||n):chatTitle(s)};
const feedOf=n=>(S.feeds[n]||{}).entries||[];
function lastWords(n){const e=feedOf(n).filter(x=>x.kind==='say');return e.length?plain(e[e.length-1].text):''}
const busy=n=>working(feedOf(n))||!!(S.sent[n]&&Date.now()-S.sent[n].at<90000&&feedOf(n).length<=S.sent[n].len);

/* --- a little markdown for replies: code blocks, inline code, bold, links, lists, headings ------------------ */
function md(src){
  const parts=String(src||'').split(/```[^\n]*\n?/);let h='';
  parts.forEach((p,i)=>{
    if(i%2){h+=`<pre><code>${esc(p.replace(/\n$/,''))}</code></pre>`;return}
    const inline=s=>esc(s).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g,'$1<a href="$2" target="_blank" rel="noopener">$2</a>');
    for(const block of p.split(/\n{2,}/)){
      const b=block.trim();if(!b)continue;const ls=b.split('\n');
      if(ls.every(l=>/^\s*[-*] /.test(l)))h+='<ul>'+ls.map(l=>`<li>${inline(l.replace(/^\s*[-*] /,''))}</li>`).join('')+'</ul>';
      else if(ls.every(l=>/^\s*\d+[.)] /.test(l)))h+='<ol>'+ls.map(l=>`<li>${inline(l.replace(/^\s*\d+[.)] /,''))}</li>`).join('')+'</ol>';
      else if(/^#{1,4} /.test(b)&&ls.length===1)h+=`<h3>${inline(b.replace(/^#+ /,''))}</h3>`;
      else h+=`<p>${ls.map(inline).join('<br>')}</p>`;
    }
  });
  return taskLinks(h,taskIds());  // F482
}

const taskChip=id=>kindChip(id,S.snap.kinds);  // F195b
