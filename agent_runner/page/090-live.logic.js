function obParse(text){let l;try{l=JSON.parse(text||'[]')}catch(e){return[]}
  return Array.isArray(l)?l.filter(x=>x&&typeof x==='object'&&typeof x.cid==='string'&&x.cid&&typeof x.name==='string'
    &&OB_STATES.includes(x.state)&&x.args&&typeof x.args==='object'&&!Array.isArray(x.args)):[]}
/* B164: the run is older than this page: its answer names an action or route it does not know */
const OLD_RUN='This run is older than this page. Restart it.', OLD_WAIT='Waiting: this run is older than this page. It goes once the run restarts.';
const oldSaid=t=>/^no such (action|page): /.test(String(t||''));
const oldRun=r=>!!r&&!r.ok&&oldSaid(r.out);
const plainOut=(r,other)=>oldRun(r)?OLD_RUN:String((r&&r.out)||other);
/* an item such a run refused: kept, and sent once the run restarts (snap.boot changes). x.boot: the run that refused
   it ('' for one that has none). The new cid is the same in every tab, so the run still runs it once */
const obRefused=x=>x.state==='failed'&&oldSaid(x.err);
/* one confirmed for that moment (a run control, a drop) never goes by itself: Retry */
const obOld=x=>obRefused(x)&&!x.ctl&&!(x.args&&x.args.confirm);
const obDue=(box,boot)=>boot?(box||[]).filter(x=>obOld(x)&&!obTo(x).startsWith('@')&&(x.boot||'')!==boot):[];
const obBootCid=(x,boot)=>x.cid.split('~')[0]+'~'+boot;
const obTo=x=>String((x&&x.args&&x.args.to)||'');
/* take an item in; a setting's own later save for everyone takes the place of one that did not go yet (`at`: the one going now) */
function obAdd(box,it,at){return(box||[]).filter(x=>!(it.name==='setting_project'&&it.set&&x.set&&x.set.id===it.set.id&&x.name===it.name&&x.state==='sending'&&x.cid!==at)).concat([it])}
/* the next item for tab `tab` to send: the first still sending, skipping messages to a chat that is not up yet and
   (B161) what a tab still there (`live`) has to send: x.by. B158: a message held for a starting chat (obHold) holds
   the next ones to that chat, not other items */
function obNext(box,tab,live,now){const t=now||Date.now(), held=[];
  for(const x of box||[]){if(x.state!=='sending'||obTo(x).startsWith('@'))continue;
    const mine=!x.by||x.by===tab||!(live||[]).includes(x.by);
    if(x.until>t||(x.heldAt&&!mine))held.push(obTo(x));
    else if(mine&&!(x.name==='chat_to'&&held.includes(obTo(x))))return x}
  return null;
}
/* B158: the run answered 'hold' to item cid (its chat does not take input yet): tried again in a moment, until
   OB_HOLD_MS, when it fails with the run's words, and the next ones to that chat with it, so none goes before it.
   A page that slept (no try for HOLD_GAP) counts anew */
const OB_HOLD_MS=120000, HOLD_STEP=1500, HOLD_GAP=90000;
function obHold(box,cid,r,now){
  const l=box||[], it=l.find(x=>x.cid===cid);if(!it)return l;
  const since=it.heldAt&&now-it.until<HOLD_GAP?it.heldAt:now;
  if(now-since>OB_HOLD_MS)return l.filter((x,i)=>i>=l.indexOf(it)&&x.state==='sending'&&x.name==='chat_to'&&obTo(x)===obTo(it)).reduce((b,x)=>obSettle(b,x.cid,{ok:false,out:r&&r.out}),l);
  return l.map(x=>x.cid===cid?{...x,heldAt:since,until:now+HOLD_STEP}:x);
}
/* a starting chat (placeholder '@cid') got its name: its messages go there */
function obName(box,ph,name){return(box||[]).map(x=>obTo(x)===ph?{...x,args:{...x.args,to:name}}:x)}
/* B182: the unsent attachments by message box ({box key: [...]}): a starting chat's go with it when its box gets another key */
function attsMove(all,from,to){const {[from]:a,...rest}=all||{};return a&&from!==to?{...rest,[to]:[...a,...(rest[to]||[])]}:all||{}}
/* the run answered item cid with r: ok drops it (and names its new chat's messages), else it fails and stays */
function obSettle(box,cid,r,boot){
  const l=box||[], it=l.find(x=>x.cid===cid);if(!it)return l;
  const ok=!!(r&&r.ok), ph='@'+cid;
  if(ok){const rest=l.filter(x=>x.cid!==cid);return it.newchat&&r.name?obName(rest,ph,r.name):rest}
  const err=String((r&&r.out)||`${it.name} did not work`).trim().split('\n')[0];
  return l.map(x=>x.cid===cid?{...x,state:'failed',err,...(oldSaid(err)?{boot:boot||''}:{})}:obTo(x)===ph?{...x,state:'failed',err:oldSaid(err)?err:'the new chat did not start'}:x);
}
/* Retry: sent again under a new cid (the run's answer to the old one is kept); a message waiting on a chat
   that did not start retries that chat. B161: `by`: the tab that sends it ('' any one) */
function obRetry(box,cid,fresh,by){
  const l=box||[], it=l.find(x=>x.cid===cid);if(!it)return l;
  const up=obTo(it).startsWith('@')&&l.find(x=>'@'+x.cid===obTo(it));
  if(up)return obRetry(l,up.cid,fresh,by);
  return l.map(x=>x.cid===cid?{...x,cid:fresh,by:by||'',state:'sending',err:'',heldAt:0,until:0}:obTo(x)==='@'+cid?{...x,args:{...x.args,to:'@'+fresh},state:'sending',err:''}:x);
}
/* Discard: the item goes, and with a new chat the messages waiting for it */
function obDrop(box,cid){return(box||[]).filter(x=>x.cid!==cid&&obTo(x)!=='@'+cid)}
function obCounts(box){const l=box||[];return{sending:l.filter(x=>x.state==='sending').length,failed:l.filter(x=>x.state==='failed').length}}
/* --- B154: sent messages: each stays shown, as pending, until its own text is in the chat's feed as 'you' -------
   One: {id, text, at (the run's clock, s, when it was typed), since (the page's clock, ms: when it went, or was last
   seen behind a working turn), state 'sent'|'failed', first (a new chat's ask), talk}. */
const LAND_MS=45000, FIRST_MS=150000, SLASH_MS=15000;
/* a message's lines as they compare: no paste wrap or Talk words, spaces as one, no empty lines */
const sentLines=t=>talkShown(String(t||'').replace(/<\/?pasted_content[^>]*>/g,'\n').trim()).split('\n').map(l=>l.replace(/\s+/g,' ').trim()).filter(Boolean);
/* the messages of `pending` the feed does not have yet: each takes its own whole lines of a 'you' entry not older
   than it (messages queued together come as one entry; an attached picture's path may become a mark) */
function sentLeft(pending,entries){
  const es=(entries||[]).filter(e=>e.kind==='you').map(e=>({at:e.at,lines:sentLines(e.text)}));
  return(pending||[]).filter(p=>{
    const all=sentLines(p.text), words=all.filter(l=>!l.startsWith('Attached: ')), want=words.length?words:all;
    for(const e of es){if(e.at&&p.at&&e.at<p.at)continue;
      for(let i=0;i+want.length<=e.lines.length;i++)if(want.every((l,k)=>e.lines[i+k]===l||(!words.length&&/^\[Image/.test(e.lines[i+k])))){e.lines.splice(i,want.length);return false}}
    return true});
}
/* `pending` after a look at the feed: without those that landed; one the chat has not got while it is idle, or gone
   (`live` false), is 'failed' (a slash command leaves no words in the feed: it just goes);
   one older than every 'you' of a `cut` feed is behind the cut, so it goes too */
function sentStep(pending,entries,now,live,cut){
  const busy=live&&working(entries), first=Math.min(...(entries||[]).filter(e=>e.kind==='you'&&e.at).map(e=>e.at));
  return sentLeft(pending,entries).filter(p=>!(cut&&p.at&&p.at<first&&first<Infinity)).map(p=>busy&&p.state==='sent'?{...p,since:now}:p)
    .filter(p=>!(/^(\/[a-z][\w:-]*(\s|$)|!)/.test(p.text)&&now-p.since>SLASH_MS))
    .map(p=>p.state==='sent'&&now-p.since>(p.first?FIRST_MS:LAND_MS)?{...p,state:'failed'}:p);
}
/* the kept sent messages after a reload, by chat */
function sentParse(text){let o;try{o=JSON.parse(text||'{}')}catch(e){return{}}
  const out={};if(!o||typeof o!=='object')return out;
  for(const [n,l] of Object.entries(o)){const ps=(Array.isArray(l)?l:[]).filter(p=>p&&typeof p==='object'&&typeof p.text==='string'&&typeof p.since==='number'&&['sent','failed'].includes(p.state));
    if(/^c\d+$/.test(n)&&ps.length)out[n]={at:0,len:0,pending:ps,start:ps.some(p=>p.first)}}
  return out}
/* the ids an item still sending stands in for (key 'need' or 'concept'): the page hides their cards meanwhile */
function obHidden(box,key){return(box||[]).filter(x=>x.state==='sending'&&x[key]).map(x=>x[key])}
/* the pill's words */
function obPill(c,offline){const p=[];if(c.sending)p.push(`${c.sending} ${offline?'waiting for the connection':'sending'}`);
  if(c.failed)p.push(`${c.failed} failed · tap to see`);return p}
/* --- F134: Runner Home in the run app ---------------------------------------------------------------------
   HOME_BASE: where Runner Home serves, from the page's own path ('' when the page is not reached through Home):
   its own page (homePage) at /, a run's app at /p/KEY/. The switcher lists Home's /projects and moves to /p/KEY/
   on the same Home address, with Home's token (the page's own: Home swaps it for the run's on every call). */
function homeBase(path,homePage){
  const m=String(path||'').match(/^(.*?\/)p\/[^/]+\//);if(m)return m[1];  // F150: Home's page for a project that is off is there too
  return homePage?String(path||'/').replace(/[^/]*$/,'')||'/':'';
}
function homeKey(path){const m=String(path||'').match(/^.*?\/p\/([^/]+)\//);try{return m?decodeURIComponent(m[1]):''}catch(e){return m[1]}}
const projectLink=(base,key,t)=>base+'p/'+encodeURIComponent(key)+'/?t='+encodeURIComponent(t||'');
/* F203: the link a switch to a project takes: its Home view, whatever was open there before */
const projectHome=(base,key,t)=>projectLink(base,key,t)+'#home';
const homeLink=(base,t)=>base+'?t='+encodeURIComponent(t||'');
/* B179: the Home Screen app's manifest, at the root every project is under: Home's, or a run's own address ('') */
const manifestLink=(base,key,t)=>(base||'./')+'manifest.webmanifest?'+(base&&key?'p='+encodeURIComponent(key)+'&':'')+'t='+encodeURIComponent(t||'');
/* B179: what a Home Screen app does with a link that asks for a new tab: 'concept' (shown in the app), 'go' (another
   page of this app, opened in place), '' (another site: outside) */
function appLink(href,origin,root){
  let u;try{u=new URL(href)}catch(e){return''}
  if(u.origin!==origin||!u.pathname.startsWith(root)||!u.searchParams.has('t'))return'';  // F136: an empty key on a trusted network
  return /\/concept\/[^/]+$/.test(u.pathname)?'concept':'go';
}
/* B153: Runner Home's link for the project name top-left: through Home, its own base; on the run's own page,
   Home's port and token (the snapshot's home) on the host the page came from, over http (Home serves http on
   every interface; its https port depends on Tailscale Serve, which the page cannot see); '' while Home is not
   installed */
function homeHref(base,t,home,loc){
  if(base)return homeLink(base,t);
  if(!home||!home.port||!home.t||!loc)return '';
  return `http://${loc.hostname}:${home.port}/?t=${encodeURIComponent(home.t)}`;
}
/* B153: the window title: the project's name first */
const pageTitle=project=>project?project+' · runner':'agent-runner';
/* a project's state in a word: off, starting…, stopping, paused, running or idle */
const projectState=p=>p.state==='off'||!p.state?(p.starting?'starting…':'off'):p.stopping?'stopping':p.paused?'paused':p.state;
/* F150: where a project stands, as home.row_group: running, up but idle or paused, off; by name in each */
const PGROUPS=[['running','Running'],['idle','Idle'],['off','Off']];
const projectGroup=p=>(p.state||'off')==='off'?'off':p.state==='running'&&!p.paused?'running':'idle';
const projectOrder=ps=>PGROUPS.flatMap(([g])=>(ps||[]).filter(p=>projectGroup(p)===g).sort((a,b)=>{const x=String(a.name||a.key).toLowerCase(), y=String(b.name||b.key).toLowerCase();return x<y?-1:x>y?1:0}));
/* F150: a project as the Home actions still on their way (hob) leave it: shown at once */
function projectNow(p,hob){
  let q={...p};
  for(const x of hob||[])if(x.state==='sending'&&x.args&&x.args.project===p.key)q=projectDid(q,x.name,x.args.arg);
  return q;
}
function projectDid(p,name,arg){
  if(name==='start')return p.state==='off'||!p.state?{...p,starting:true}:p;
  if(p.state==='off'||!p.state)return p;
  return name==='pause'?{...p,paused:true}:name==='resume'?{...p,paused:false}:name==='stop'?{...p,stopping:true}:name==='slots'&&/^\d+$/.test(arg)?{...p,slots:+arg}:p;
}
/* the list's rows: one per Home project in its order, with its link (to its Home view), its state and how many
   things need you */
function switcherRows(projects,key,base,t){
  return projectOrder(projects).map(p=>({key:p.key,name:p.name||p.key,state:p.state||'off',group:projectGroup(p),said:projectState(p),needs:p.needs||0,
    href:projectHome(base,p.key,t),on:p.key===key}));
}
/* F150: the All projects row is there once Home lists another project; its count is the others' */
const oneProject=ps=>!!ps&&ps.length<2;
const needsOf=(ps,but)=>(ps||[]).reduce((n,p)=>n+(p.key===but?0:p.needs||0),0);
/* what waits on the person, over all projects: [{key, name, id, what}] (Home's 'ID - what to do' lines) */
function projectAsks(ps){
  return projectOrder(ps).flatMap(p=>(p.asks||[]).map(a=>{const m=String(a).match(/^(\S+) - (.+)$/);
    const what=m?m[2]:String(a);return{key:p.key,name:p.name||p.key,id:m?m[1]:'',what:what.charAt(0).toUpperCase()+what.slice(1)}}));
}
/* the words under a project: its state when the group it stands in does not say it, its slots, its queue */
function projectWords(p){
  const w=[], s=projectState(p), n=(p.running||[]).length;
  if(!['running','idle','off'].includes(s))w.push(s);
  if(p.state&&p.state!=='off'&&p.slots!=null)w.push(`${n} of ${p.slots} slot${p.slots==1?'':'s'}`);
  if(p.left!=null)w.push(p.left?p.left+' queued':'nothing queued');
  return w.join(' · ');
}
/* a project's one main button, and what its … sheet holds: a: Home's /act name; sure: it asks first */
const projectMain=p=>p.state==='off'||!p.state?{label:p.starting?'Starting…':'Start run',a:'start',busy:!!p.starting}:p.page?{label:'Open',open:true}:null;
function projectMore(p){
  const up=!!p.state&&p.state!=='off';
  return[...(up?[p.paused?{label:'Go on',a:'resume'}:{label:'Pause',a:'pause'}]:[]),...(up&&p.slots!=null?[{label:'Slots',step:p.slots}]:[]),
    ...(up&&!p.stopping?[{label:'Stop',a:'stop',sure:`Stop ${p.name||p.key}? Its running tasks finish and nothing new starts.`}]:[]),
    {label:'Unlist',unlist:true,sure:`Unlist ${p.name||p.key}? Its run and files stay as they are.`}];
}
/* F150: the last snapshot as it is kept for the next time the project opens: what it shows, not what tells one run or
   one version from another, and no token */
function snapKept(s){const{home,boot,at,page,restart_needed,version,...keep}=s||{};return keep}
/* F149: the popup for an answer of the run (or Home): {kind: 'refresh', key}, the page it serves is not this one;
   {kind: 'restart', key}, newer code waits for a person to restart the run; else null. later: the keys put off. The
   page never reloads by itself. */
function pageNews(s,mine,later){
  const l=[];
  if(mine&&s.page&&s.page!==mine)l.push({kind:'refresh',key:'page:'+s.page});
  if(s.restart_needed)l.push({kind:'restart',key:'restart:'+s.restart_needed});
  return l.find(x=>!later.includes(x.key))||null;
}
/* why Refresh waits: o says what a refresh would lose. '' : nothing */
function refreshHold(o){return o.mic?'Stop the mic first, then refresh.':o.uploading?'Wait for the attachments to finish uploading.'
  :o.form?'Save or close the device form first. It is not kept over a refresh.'
  :o.secret?'Send or clear the secret first. It is not kept over a refresh.'
  :o.unkept?'This browser cannot keep what you wrote. Send or clear it first.':''}
if(typeof module!=='undefined')module.exports={keptPut,chatLast,standMsgs,WALK,walkStep,walkParse,walkMove,walkHTML,exampleOffer,sendForces,giveHTML,needInputs,stepMore,needTap,needBody,taskParas,needReplies,pageNews,refreshHold,boxEnter,feedFoot,feedHand,feedSpot,feedShare,feedBars,sessionChips,forWords,taskLines,FEED_MODES,talkMsgs,feedState,FEED_KEYS,feedBytes,feedWords,feedSteps,viewOf,placeOf,runPill,cardControls,controlGroups,needsReply,chatGroups,needChatAsk,TALK_SET,talkSetParse,pickVoice,runVoice,speechClips,silentWav,feedMark,feedAfter,atEnd,swipeTakes,swipeOpens,settingText,settingValue,pickValue,pickOptions,partsNow,partOptions,partSet,settingSays,settingSide,settingChanged,settingHit,settingShows,kindsModel,KINDS_ROWS,homeBase,homeKey,projectLink,homeLink,manifestLink,appLink,homeHref,pageTitle,projectState,projectGroup,projectOrder,projectNow,projectDid,oneProject,needsOf,projectAsks,switcherRows,projectWords,projectMain,projectMore,snapKept,chatMove,chatSort,chatPlaces,BOX_KEYS,keysLine,histPush,histEdge,histStep,slashMatches,slashPick,slashMove,SLASH_FALLBACK,chatPick,answerOpts,working,planWords,compose,sendReq,ctxKey,isNew,usageOf,logKind,plain,chatName,controlReq,controlClick,taskControlsOn,queueGroups,conceptButtons,planQueue,planReleases,NO_CONCEPT,newPh,NAV,talkSession,micProblem,dictProblem,dictButton,dictInsert,talkShown,talkReply,goneMark,needsShown,answerSaid,GONE_MS,obParse,obAdd,obNext,obName,obSettle,obRetry,obDrop,obCounts,obHidden,obPill,OLD_RUN,OLD_WAIT,oldRun,plainOut,obRefused,obOld,obDue,obBootCid,sentLeft,sentStep,sentParse};
