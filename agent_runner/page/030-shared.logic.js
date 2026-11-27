const isNew=n=>String(n||'')[0]==='+';
/* the usage line of the status lines ('usage: session 40%, week 12%'), '' for none */
const usageOf=status=>((status||[]).find(l=>/^usage: /.test(l))||'').replace(/^usage: /,'');
/* a run log line's kind, for its icon in History */
function logKind(line){
  const l=String(line||'').toLowerCase();
  if(/\b(landed|merged|released|done)\b/.test(l))return 'ok';
  if(/\b(stuck|failed|error|blocked|refused)\b/.test(l))return 'bad';
  if(/\b(started|start|took|picked)\b/.test(l))return 'go';
  return '';
}
/* a reply as one plain line, for a card's quote: no markdown marks */
const plain=s=>String(s||'').replace(/```[\s\S]*?(```|$)/g,' ').replace(/\*\*([^*]+)\*\*/g,'$1').replace(/`([^`]+)`/g,'$1')
  .replace(/\[([^\]]+)\]\([^)]*\)/g,'$1').replace(/^\s*(?:[-*]|\d+[.)]|#+)\s+/gm,'').replace(/\s+/g,' ').trim();
const chatName=s=>s.title&&(s.renamed||s.title!=='control session')?s.title:`Chat ${s.name.slice(1)}`;
/* F82: a run control's request to /act (run_control, from the snapshot's one list of controls): o.n the slot
   count typed, o.tid the slot's task, o.sure only from the page's own confirm step (a control with a confirm
   question is refused without it) */
function controlReq(c,o){
  o=o||{};const args={key:c.key};
  if(c.needs==='n')args.n=String(o.n==null?'':o.n).trim();
  if(c.needs==='id'||(c.needs==='pick'&&o.tid))args.tid=o.tid||'';
  if(c.confirm&&o.sure===true)args.confirm=true;
  if(c.seen&&o.sure===true)args.text=c.seen;  // F186: the open releases the Yes was about
  if(c.answer){args.text=o.text||'';const note=String(o.note||'').trim();if(note)args.note=note}  // F180: the label pressed, the popup's reply box
  return {name:'run_control',args};
}
/* a control's button pressed: {ask:true} for one with a confirm question not yet answered in the page (its Yes
   button carries o.sure), else its request */
function controlClick(c,o){return c.confirm&&!(o&&o.sure===true)?{ask:true}:controlReq(c,o)}
/* a slot's task controls show while it works, not while it lands (merging) */
const taskControlsOn=s=>!!(s&&s.task_controls);  // C33: ui_model.task_controls_on, on the row
/* B118: the Queue's two groups: [the queue a run works through, the Parked tasks it never starts] */
const queueGroups=q=>[(q||[]).filter(x=>x.state!=='parked'),(q||[]).filter(x=>x.state==='parked')];
/* F402c1: with no run up, what is said of the tasks new in the queue since the last snapshot (was: the ids seen), '' for none */
function addedWaits(was,snap){
  const xs=snap&&snap.up===false&&was?((snap.queue)||[]).filter(q=>q.waits_run&&!was.includes(q.id)):[];
  return !xs.length?'':xs.length===1?`${xs[0].id} is queued: it waits for the run to start`:`${xs.length} tasks are queued: they wait for the run to start`;
}
/* F193: [run] releases; on from a run that does not say */
const releasesOn=snap=>!(snap&&snap.manage_releases===false);
/* F185: the releases, as Status and Home say them: each open release (its queue task, which carries its row as `release`), then the
   rows that are no task (the auto release's count, the last one released); and the Queue's tasks, without them. F195c: planRows, the
   Plan view's Queue: its tasks and releases in plan order, the auto release's count before the row its `before` names */
const planReleases=snap=>{const q=(snap&&snap.queue)||[];
  return ((snap&&snap.releases)||[]).map(r=>r.placeholder?r:q.find(x=>x.id===r.id)).filter(Boolean)};
const planQueue=snap=>queueGroups(snap&&snap.queue)[0].filter(q=>!q.release);
const planRows=snap=>{const qs=queueGroups(snap&&snap.queue)[0].slice();
  for(const r of (releasesOn(snap)&&snap&&snap.releases)||[])if(r.placeholder&&r.state!=='released'){const i=qs.findIndex(q=>r.before&&q.id===r.before);qs.splice(i<0?qs.length:i,0,r)}
  return qs};
/* F87: a concept card's buttons, in order: one per option (pick: its index, rec: the recommended one, named
   without its '(recommended)'), then Chat, and View when it has a local copy or a page */
const optionName=o=>o.name.replace(/\s*[(\[—–-]*\s*recommended\s*[)\]]?\s*$/i,'')||o.name;
function conceptButtons(c){
  const bs=(c.options||[]).map((o,j)=>({label:optionName(o),pick:j,rec:!!o.rec}));
  bs.push({label:'Chat',about:true});
  if(c.copy||c.url)bs.push({label:'View',view:true});
  return bs;
}
const NO_CONCEPT='No concept waits for a pick.';
/* F93: Talk. The sidebar's views, Talk first; its control session: the one this browser remembers while it is
   live, else a live chat titled Talk, else '' (the next send opens one) */
const NAV=[['talk','Talk'],['home','Home'],['plan','Work'],['concepts','Concepts'],['tools','Tools'],['settings','Settings']];
/* F124: Agents and Activity are one view now, Status */
const viewOf=v=>['agents','activity','status','history'].includes(v)?'plan':v;  // F476: Status and History are the Work page
/* B177: what a reload opens: {v: the view, t: the chat ('' for none), link: the link named it}. hash: the link's #,
   a view (#plan) or a chat or slot (#c3, #s1), which wins over text, the place this tab kept; projects: there is an
   All projects view; starting: the stand-ins ('@cid') of chats still starting. Anything else is Home */
function placeOf(text,hash,projects,starting){
  const known=v=>NAV.some(n=>n[0]===v)||!!projects&&v==='projects', h=String(hash||'').replace(/^#/,''), hv=viewOf(h);
  if(known(hv))return{v:hv,t:'',link:true};
  const nd=h.match(/^need-([A-Za-z0-9][\w.-]*)$/);if(nd)return{v:'home',t:'',link:true,need:nd[1]};  // F150: an item of Needs you
  if(/^[cs]\d+$/.test(h))return{v:'home',t:h,link:true};
  const tk=h.match(/^task-([A-Z]\d+[a-z0-9]*)$/);if(tk)return{v:'plan',t:'',link:true,task:tk[1]};  // F482: a task, its sheet open in Work
  let o;try{o=JSON.parse(text||'{}')}catch(e){}
  if(!o||typeof o!=='object')o={};
  const v=viewOf(o.v), t=typeof o.t==='string'?o.t:'';
  const c=isNew(t)&&o.c&&typeof o.c==='object'&&typeof o.c.label==='string'&&ctxKey(o.c)===t?o.c:null;  // F172
  const ok=!t||!!c||/^\w[\w.-]*$/.test(t)||(starting||[]).includes(t);  // a stand-in that went is a chat that is gone
  return{v:ok&&known(v)?v:'home',t:ok?t:'',link:false,...(c?{c}:{})};
}
/* F124: the state pill: the run's state (ui_model.run_state) and its colour */
function runPill(snap){
  const t=(snap&&snap.run&&snap.run.state)||(snap&&snap.up===false?'Not up':snap&&snap.run&&snap.run.stopping?'Stopping':snap&&snap.run&&snap.run.paused?'Paused':snap&&snap.up?'Running':'');
  return{text:t,cls:{Running:'ok',Paused:'warn','Caps forced':'warn',Stopping:'bad','Not up':''}[t]||''};
}
/* F124: the Run card's everyday buttons (control keys): Start the run while none is up */
function cardControls(snap){return(snap&&snap.card)||[]}  // C33: ui_model.controls_shown decides
/* F124: the More… sheet: [{group, items: [{c, label, choices}]}] from the snapshot's controls, in the list's order of
   groups; a Fix up control only while there is something to fix, with a count */
/* B763b: the group of the everyday controls that have none, and each run control's icon (a name in I) */
const SHEET_GROUP={stop:'Stop',stop_undo:'Stop',start:'Run',pause:'Run',go_on:'Run',slot_add:'Run',slot_remove:'Run'};
const SHEET_ICON={stop:'stop',stop_now:'x',stop_undo:'undo',suspend:'clock',shutdown:'alert',start:'play',pause:'pause',go_on:'play',
  slot_add:'plus',slot_remove:'minus',slots_set:'edit',force:'up',caps_on:'check',upgrade:'down',restart:'history',resume:'play',
  unclaim:'x',wip_show:'file',wip_restore:'undo',wip_drop:'trash'};
function controlGroups(snap){
  const run=(snap&&snap.run)||{}, out=[], shown=(snap&&snap.shown)||[];
  // B763b: of the pairs, the one that fits the run's state, as on the Run card
  const off=new Set([run.paused?'pause':'go_on',run.stopping?'stop':'stop_undo']);
  for(const g of ['Stop','Run','Fix up']){
    const items=[];
    for(const c of (snap&&snap.controls)||[]){
      if(c.where!=='run'||(c.group||SHEET_GROUP[c.key])!==g||!shown.includes(c.key)||off.has(c.key))continue;
      const choices=c.fix?((snap.fixups||{})[c.fix]||[]):[];
      items.push({c,icon:SHEET_ICON[c.key]||'dot',label:c.fix?`${c.label} (${choices.length})`:c.key==='suspend'&&run.power==='suspend'?'Take the suspend back':c.key==='shutdown'&&run.power==='shutdown'?'Take the shutdown back':c.label,choices});
    }
    if(items.length)out.push({group:g,items});
  }
  return out;
}
/* F128: does a chat wait for the person's reply: an open question, or the session spoke after they last opened it
   (seen: epoch s) */
const needsReply=(s,seen)=>!!s.needs_reply||(s.last==='claude'&&(s.at||0)>(seen||0));
/* F128: the Chats list in two: the chats, then the quiet ones (no reply needed, nothing said for `quiet` s). A
   pinned chat and one the person named stay up, and so does `up`, the open chat that was not quiet (B193). */
function chatGroups(rows,o){
  const top=[],quiet=[];
  for(const s of rows||[]){
    const q=s.closed||o.quiet>0&&!(o.pins||[]).includes(s.name)&&!s.renamed&&s.name!==o.up&&s.at>0
      &&o.now-s.at>o.quiet&&!needsReply(s,(o.seen||{})[s.name]);  // B859: one closed for being idle rests in Quiet
    (q?quiet:top).push(s);
  }
  return{top,quiet};
}
/* F425b: the Quiet group's rows: the quiet chats and the sent responses, newest first. responseRows: the kept responses as
   rows (name: what S.thread holds while one is open), without those whose chat starts (an outbox item) or has started (gone) */
const responseRows=(kept,ob,gone)=>(kept||[]).filter(r=>!(gone||[]).includes(r.id)&&!(ob||[]).some(x=>x.name==='response_chat'&&x.args.rid===r.id))
  .map(r=>({...r,response:true,name:ctxKey({kind:'response',id:r.id}),label:[r.item,r.title].filter(Boolean).join(' ')}));
const quietRows=(quiet,responses)=>(quiet||[]).concat(responses||[]).sort((a,b)=>(b.at||0)-(a.at||0));
/* F143: a Needs you card's Chat, as its first message shows while the run starts it (need_chat_text then replaces it) */
function needChatAsk(n){const os=needInputs(n).length?[]:((n&&n.answers)||[]).map(a=>a.label||a.value);
  return `This chat is about ${n.id}${n.title?` '${n.title}'`:''}, which needs me. What was put to me:\n\n${n.ask||n.what||''}${os.length?`\n\nPossible answers:\n${os.map(o=>'- '+o).join('\n')}`:''}`}
/* F124: Talk's settings, kept per browser: read (read replies aloud), voice ('' the run's default, else the system's own; F158: an id of a run voice, 'system', or a
   device voice's name), mic 'tap' or 'hold',
   auto (listen again once a reply was read), way: how speech becomes words, 'browser' or 'recorded' (F161b) */
const TALK_SET={read:true,voice:'',mic:'tap',auto:false,way:'browser'};
function talkSetParse(text){let o;try{o=JSON.parse(text||'{}')}catch(e){o={}}
  if(!o||typeof o!=='object')o={};
  return{read:o.read!==false,voice:typeof o.voice==='string'?o.voice:'',mic:o.mic==='hold'?'hold':'tap',auto:o.auto===true,way:o.way==='recorded'?'recorded':'browser'}}
/* F189b: what a fold shows, in one box that its button reveals; k: its key */
const foldIn=(k,h)=>`<div class="foldin" data-k="fold:${E_(k)}">${h}</div>`;
/* F195b: a task's id as a chip with its kind's word and colour: kinds, the snapshot's table (theme.kind_table); just the id
   when it is no task's (a tool, a pitch) */
function kindChip(id,kinds){
  const m=/^([A-Za-z]+)\d/.exec(id||'');if(!m)return E_(id||'');
  const k=(kinds||{})[m[1]]||{word:'',color:'gray'}, w=k.word?k.word.charAt(0).toUpperCase()+k.word.slice(1):'';
  return `<span class="kind k-${E_(k.color)}">${w?`<i>${E_(w)}</i> `:''}${E_(id)}</span>`;
}
/* F195b: what an icon-only control does: its label, '' when it has words of its own. A picture is no icon */
const iconWords=(label,title,text,drawn)=>(drawn||text.trim())&&!/[\p{L}\p{N}]/u.test(text)?String(label||title||'').trim():'';
/* where the hint stands: over its control r, under it with no room, inside the window (w, h the hint's size) */
function hintSpot(r,w,h,vw,vh){
  const gap=8, top=r.top-h-gap;
  return{left:Math.round(Math.max(gap,Math.min(vw-w-gap,(r.left+r.right-w)/2))),top:Math.round(top>=gap?top:Math.min(vh-h-gap,r.bottom+gap))};
}
