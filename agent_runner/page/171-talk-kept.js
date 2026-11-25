const talkTyping=()=>!!micWhy()||tabStore.get(TM_KEY)==='type';
/* B802: coming to Talk, or back to its tab, ends typing mode: the mic shows, and the words stay the box's draft. The tab
   hidden for less than TYPE_STAYS (an app switch, a refresh of the page) is not left. Returns whether it ended */
const TA_KEY='ar-talkaway', TYPE_STAYS=60000;
function talkBack(){
  if(micWhy())return false;
  const t=document.activeElement;if(t&&t.matches&&t.matches('[data-in]'))t.blur();  // a chat's box too: the redraw would hand its focus on
  if(tabStore.get(TM_KEY)!=='type')return false;
  tabStore.set(TM_KEY,'');
  if(DK.rec&&DK.key==='talk'){DK.put=true;if(MIC.rec===DK.rec)DK.rec.stop();else{MIC.next=null;DK.rec=null}}  // its stop is in the box
  return true;
}
/* since when the tab is away, and from which project, kept over a reload. Back: true when that was too long, or another
   project's page was open since, or nothing says */
function talkLate(){const [at,...of]=tabStore.get(TA_KEY).split(' ');tabStore.set(TA_KEY,'');return !at||of.join(' ')!==TALK_FOR||Date.now()-at>=TYPE_STAYS}
const talkGone=()=>{if(!tabStore.get(TA_KEY))tabStore.set(TA_KEY,Date.now()+' '+TALK_FOR)};
const talkSeen=()=>{if(!tabStore.get(TA_KEY))return;if(talkLate()&&chatShown()&&talkBack())render(true)};
for(const [o,t] of [[document,'visibilitychange'],[window,'pagehide'],[window,'pageshow']])o.addEventListener(t,e=>{if(t==='pagehide'||document.hidden)talkGone();else if(t!=='pageshow'||e.persisted)talkSeen()});
function talkMode(m){tabStore.set(TM_KEY,m==='type'?'type':'');S.pin=true;if(chatShown())toEnd(true);render(true);const t=m==='type'&&document.querySelector('[data-in]');if(t)kbFocus(t)}
/* F157: the Talk chats left by New Talk chat, kept over a reload */
function talkOld(){try{const l=JSON.parse(store.get(TALK_OLD)||'[]');return Array.isArray(l)?l:[]}catch(e){return []}}
function talkLeave(names){store.set(TALK_OLD,JSON.stringify([...new Set(talkOld().concat(names))]))}
const talkTitled=()=>(S.snap.sessions||[]).filter(s=>s.title==='Talk').map(s=>s.name);
/* the sends still opening a chat, kept over a reload: gen -1 for those New Talk chat left */
function talkStarts(l){if(l.length===TK.starting.length&&l.every((w,i)=>w===TK.starting[i]))return;TK.starting=l;talkStartsKeep()}
const talkStartsKeep=()=>store.set(TALK_START,TK.starting.length?JSON.stringify(TK.starting.map(w=>({at:w.at,gen:w.gen===TK.gen?0:-1}))):'');
function talkStartsRead(){try{const l=JSON.parse(store.get(TALK_START)||'[]');return Array.isArray(l)?l.filter(w=>w&&typeof w.at==='number').map(w=>({at:w.at,gen:w.gen,kept:true})):[]}catch(e){return []}}
/* the live Talk session. A chat that was still starting when New Talk chat was pressed is old as soon as it shows */
function talkFind(remembered){
  talkStarts(TK.starting.filter(w=>{
    const t=w.gen===TK.gen&&!w.kept?'':talkSession(S.snap.sessions,'',talkOld());
    if(t&&w.gen!==TK.gen)talkLeave([t]);
    return !t&&Date.now()-w.at<90000}));
  if(remembered==='new'){const more=talkTitled().filter(n=>!talkOld().includes(n));if(more.length)talkLeave(more)}
  return talkSession(S.snap.sessions,remembered,talkOld());
}
/* F157: New Talk chat: whatever Talk is doing stops, and the next message opens a fresh Talk session. The old one
   stays in Chats; a message on its way still reaches it */
function newTalk(){
  const was=talkName(), known=(S.snap.sessions||[]).map(s=>s.name);
  if(known.length)store.set(TALK_OLD,JSON.stringify(talkOld().filter(n=>known.includes(n))));  // a chat that is gone: its name can come again
  talkLeave([...talkTitled(),was,talkKept()].filter(n=>n&&n!=='new'));
  talkKeep('new');TK.gen++;talkStartsKeep();
  const rec=TK.rec, spoke=talkReads();
  if(TK.ear)micLog('stop by New Talk chat');
  TK.ear=TK.rec=null;TK.hold=TK.again=false;TK.wait=null;
  TK.state=TK.heard=TK.kept=TK.said=TK.note=TK.report=TK.playing='';TK.turn=(TK.turn||0)+1;
  if(rec)rec.stop();
  TK.held='';TK.later=[];
  if(spoke)shush();
  S.drawer=false;S.pin=true;render(true);
}
function talkName(){
  const n=talkFind(talkKept());if(n)return n;
  const w=TK.wait;return w&&Date.now()-w.at<90000?w.n:'';  /* just opened: not in the snapshot yet */
}
/* B133: the session a Talk reply is awaited from ('' for none): a wait opened with no session name takes the live
   chat titled Talk once the snapshot lists it */
function talkWaitName(){
  const w=TK.wait;if(!w)return '';
  if(!w.n){const t=talkFind('');if(t){w.n=t;talkStarts(TK.starting.filter(x=>x!==w));talkKeep(t)}}
  return w.n;
}
