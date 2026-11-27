const card=(h,cls='',attr='')=>`<div class="card ${cls}" ${attr}>${h}</div>`;
/* F82: the run controls, from the snapshot's one list (ui_model.RUN_CONTROLS); F124: the everyday ones on the Run card,
   the rest in the More… sheet; one with a confirm question asks in place first */
const controlsOf=w=>(S.snap.controls||[]).filter(c=>c.where===w);
const controlOf=k=>(S.snap.controls||[]).find(c=>c.key===k);
const ctlBusy=(k,tid)=>S.ob.some(x=>x.ctl===k+':'+(tid||'')&&x.state==='sending');
/* a confirm, asked where the control stands (docs/STYLE.md): attr, the Yes button's own data- attributes */
const sureHTML=(q,yes,attr)=>`<div class="sure" data-k="sure" role="group"><div class="small">${esc(q)}</div><div class="btns"><button class="btn bad" ${attr} data-sure>Yes, ${esc(yes)}</button><button class="btn" data-unsure>No</button></div></div>`;
/* what a control would cut off: each slot's task and how long it has run (stop now, suspend, shut down; Cancel, its own task) */
function cutsOff(c,tid){
  if(c.key==='task_cancel'){const s=slots().find(s=>s.task===tid);return s&&s.minutes!=null?`${tid} has worked ${s.minutes} min in ${s.name}. `:''}  // F426d
  if(!['stop_now','suspend','shutdown'].includes(c.key)||c.key===(S.snap.run||{}).power)return '';
  const ws=working_();return ws.length?`Cuts off ${ws.map(w=>`${w.task} in ${w.name}${w.minutes!=null?` (${w.minutes} min in)`:''}`).join(', ')}. `:'';
}
const ctlSure=(c,tid)=>sureHTML(cutsOff(c,tid)+((((S.snap.queue||[]).find(q=>tid&&q.id===tid)||{}).asks||{})[c.key]||c.confirm.split('{id}').join(tid||'')),c.label.charAt(0).toLowerCase()+c.label.slice(1),`data-ctl="${esc(c.key)}" data-tid="${esc(tid||'')}"`);
/* C34: a panel's row actions ('queue', 'release': ui_model.RUN_CONTROLS' `where`): the buttons for a row's `acts` (the
   keys ui_model allowed on it), each through the one data-ctl handler, and the confirm one asks in place */
const obActs=(x,where)=>{const w=x.ctl?(controlOf(x.ctl.split(':')[0])||{}).where:'';return w==='queuemenu'?where==='queue'&&x.state==='failed':!!x.ctl&&w===where};  // F429b: the row itself shows a row menu's act
const obRun=x=>!!x.ctl&&!['queue','queuemenu','shelved','release','need','concept'].includes((controlOf(x.ctl.split(':')[0])||{}).where);
const actBtns=(acts,tid,labels={},pri='')=>(acts||[]).map(controlOf).filter(Boolean).map(c=>`<button class="btn${c.key===pri?' pri':''}${ctlBusy(c.key,tid)?' busy':''}" data-ctl="${esc(c.key)}" data-tid="${esc(tid)}">${esc(labels[c.key]||c.label)}</button>`).join('');
/* F180: a Needs you row's fixed answers among its actions (the first is the main button; a pitch draws only that one,
   Not this… has the rest), and its other actions */
const isAnswer=k=>!!(controlOf(k)||{}).answer;
/* F181c: what its answer buttons say ('Full (recommended)'); what is sent is the row's labels ('Full') */
const ansWords=(n,ks)=>Object.fromEntries(ks.map((k,j)=>[k,((n.answers||[])[j]||{}).label]).filter(x=>x[1]));
const ansBtns=n=>{const ks=(n.acts||[]).filter(isAnswer);return actBtns(n.label==='PITCH'?ks.slice(0,1):ks,n.id,{...n.labels,...ansWords(n,ks)},ks[0])};
const restBtns=n=>actBtns((n.acts||[]).filter(k=>!isAnswer(k)),n.id,n.labels);
const actSure=(acts,tid)=>(acts||[]).map(controlOf).filter(c=>c&&S.sure===c.key+':'+tid).map(c=>ctlSure(c,tid)).join('');
/* F168: the shared tools in words, the same as status says */
const toolsWords=ts=>'Tools: '+ts.map(t=>`${t.label}: ${t.words}`).join(' · ');
/* Run controls: the Run card; B763a: each with its icon; F426e: the slots' rows are in Working (076-status.js) (docs/STYLE.md, Run card) */
const CTL_ICON={start:'play',go_on:'play',pause:'pause',stop:'stop',stop_now:'stop',stop_undo:'undo',slot_add:'plus',slot_remove:'minus'};
function controlsCard(){
  const run=S.snap.run||{}, up=S.snap.up!==false;
  const said=!up?'No run is up.':[run.paused?'Paused: no new tasks start':'',run.stopping?'Stopping: the running tasks finish, nothing new starts':'',run.forced?'Usage caps off':'',run.power?`${run.power==='suspend'?'Suspends':'Shuts down'} once it stops`:''].filter(Boolean).join(' · ')||'Running';
  const mark=up&&run.mark?`<span class="small" data-k="heldmark"> · ${esc(run.mark)}</span>`:'', herr=S.heldErr?`<div class="small v-bad" data-k="heldErr">${esc(S.heldErr)}</div>`:'';  // B851a
  const b=cardControls(S.snap).map(k=>{const c=controlOf(k);return c?`<button class="btn ${k==='start'||k==='go_on'||k==='stop_undo'?'acc':''}${ctlBusy(k)?' busy':''}" data-ctl="${esc(k)}">${I[CTL_ICON[k]]||''}${esc(k==='stop'?'Stop':c.card_label||c.label)}</button>`:''}).join('');
  return card(`<div class="row"><div class="grow"><b>Run</b><div class="small" data-k="runsaid" data-roll data-v="${esc(said)}">${esc(said)}${mark}</div></div>${up?(w=>`<span class="small" data-k="slotsof" data-roll data-v="${w}">${w}</span>`)(`${working_().length} of ${S.snap.slots||0} slot${S.snap.slots===1?'':'s'}`):''}</div>
    ${S.snap.no_settings?`<div class="small" data-k="nosettings"><span class="v-warn">${esc(S.snap.no_settings)}</span></div>`:''}
    ${S.snap.usage_held?`<div class="small" data-k="usageheld"><span class="v-warn">${esc(S.snap.usage_held)}</span></div>`:''}
    ${S.snap.agent_problem?`<div class="small" data-k="agentproblem"><span class="v-warn">${esc(S.snap.agent_problem)}</span></div>`:''}
    ${S.snap.unpushed?`<div class="small" data-k="unpushed" data-v="${esc(S.snap.unpushed)}">${esc(S.snap.unpushed)}</div>`:''}
    ${S.snap.pr_limit?`<div class="small" data-k="prlimit" data-v="${esc(S.snap.pr_limit)}">${esc(S.snap.pr_limit)}</div>`:''}
    ${(S.snap.tools||[]).length?`<div class="small" data-k="tools" data-v="${esc(toolsWords(S.snap.tools))}">${esc(toolsWords(S.snap.tools))}</div>`:''}
    ${herr}${obCards(obRun)}${controlsOf('run').length?`<div class="btns tight" role="group" aria-label="Run controls">${b}<button class="btn" data-sheet="run">${I.dots}More…</button></div>`:''}`,'','data-k="run"');
}
/* F98: a pitch's Not this, folded open in place: all of it or one change, its task reopened or dropped */
function pitchNo(n,i){
  const xs=n.changes||[], sure=String(S.sure||'');
  const row=(tid,title)=>{const at=how=>`pitch:${n.id}:${how}:${tid}`;
    return `<div class="small ell">${esc(title)}</div><div class="btns">${['reopen','drop'].map(how=>`<button class="btn" data-pitchno="${i}" data-how="${how}" data-tid="${esc(tid)}">${how==='drop'?'Undo and drop':'Undo and reopen'}</button>`).join('')}</div>`
      +['reopen','drop'].map(how=>sure===at(how)?sureHTML(`Undo ${tid||'all of it'} here and ${how} ${tid?'its task':'the tasks'}?`,`undo and ${how}`,`data-pitchno="${i}" data-how="${how}" data-tid="${esc(tid)}"`):'').join('')};
  return (xs.length>1?row('','All of it'):'')+xs.map(x=>row(x.id,`${x.id} · ${x.title}`)).join('')}
/* F162: an item's buttons, the same on its card and in its popup: its answers, Later, Chat, Drop and Open */
function needBtns(n,i,more=''){
  const open=a=>a?`<a class="btn" href="${esc(a)}" target="_blank" rel="noopener">Open ${I.ext}</a>`:'';
  if(n.label==='PITCH'){const on=!!(S.pitchOpen||{})[n.id], ask=!!(S.reviewOpen||{})[n.id];  // F444c: Ask…
    return `<div class="btns">${ansBtns(n)}<button class="btn" data-pitchopen="${i}" aria-expanded="${on}">Not this…</button><button class="btn" data-reviewopen="${i}" aria-expanded="${ask}">Ask…</button>${more}${restBtns(n)}${open(n.url||(n.copy?tq('concept/'+encodeURIComponent(n.id)):''))}</div>${on?foldIn('pitch:'+n.id,pitchNo(n,i)):''}${ask?foldIn('review:'+n.id,reviewAskHTML(n,i,S.reviewAns,S.sure)):''}`}
  if(n.label==='PR')return `<div class="btns">${open(n.url)}</div>`;  // F420: a person merges it on GitHub, and then it clears
  if(n.label==='TOOL')return '';  // F168: nothing to answer, it clears once the tool is back
  return `<div class="btns">${needInputs(n).length?'':ansBtns(n)}${more}${restBtns(n)}${open(needPage(n))}${n.devices?needDevices(n):''}</div>${actSure(n.acts,n.id)}`;
}
/* F411: an item's page: its link, or the run page's own copy of a pick sheet with no claude.ai page */
const needPage=n=>n.url||(n.page?tq(n.page):'');
const needCard=(n,i)=>card(needTap(n,S.snap.kinds)+conceptFrame(n)+needBtns(n,i),'need',`data-k="need:${esc(n.id)}"`);
/* F162: the popup of one Needs you item: everything about it, its answers always on screen at the foot */
const needOf=id=>((S.snap&&S.snap.needs)||[]).find(n=>n.id===id);
const shotUrl=s=>tq('shot/'+s.src.split('/').map(encodeURIComponent).join('/'));
const askField=id=>'askre:'+id;
const askTask=id=>!/^(tool-|pr-|pitch)/.test(id);
function askFold(key,label,got){
  const on=!!S.askFold[key];
  return `<button class="fold" data-k="askfold:${key}" data-askfold="${key}" aria-expanded="${on}"><span class="grow"><b>${label}</b></span><span class="chev">${I.chev}</span></button>${on?foldIn('ask:'+key,`<div class="asktext">${!got?'<div class="small">Loading…</div>':got.err?`<div class="small v-bad">${esc(got.err)}</div><div class="btns"><button class="btn" data-askload>Retry</button></div>`:taskParas(got.text).map(p=>`<p>${esc(p)}</p>`).join('')||'<div class="small">There are no words of it.</div>'}</div>`):''}`;
}
/* F162a2: only when there are words of the agent */
function askWhyFold(id){const got=(S.askWhy||{})[id];return got&&got.text?askFold('why','Why it waits',got):''}
/* F189: a picture opens out of its thumbnail and goes back into it, and the sheet's edges, title and foot move with it.
   SHOT: what moves over or on the sheet now, and the scroll place Back returns to */
const SHOT={ghost:null,n:-1,clip:null,at:0}, SHOT_MO={ease:'--spring-soft'};
function shotEnd(){
  const {ghost,clip}=SHOT;SHOT.ghost=SHOT.clip=null;
  if(ghost)ghost.remove();
  if(clip){clip.onfinish=null;clip.cancel();$('sheet').style.paddingTop=$('sheet').style.paddingBottom=''}
}
/* where a thing is seen now: its box less its clip-path, so a new motion starts from there */
function shotSeen(el){
  const r=el.getBoundingClientRect(), m=/^inset\(([^)]*?)( round [^)]*)?\)$/.exec(getComputedStyle(el).clipPath||''), v=m?m[1].trim().split(/\s+/):['0px'];
  const k=el.offsetWidth?r.width/el.offsetWidth:1, side=i=>{const x=v[i]??v[i-2]??v[0];return Math.max(0,parseFloat(x)*(x.endsWith('%')?(i%2?r.width:r.height)/100:k))};
  return{left:r.left+side(3),top:r.top+side(0),right:r.right-side(1),bottom:r.bottom-side(2)};
}
/* the part of a box that the sheet shows: not what is under its foot */
function shotCut(b){
  const v=shotSeen($('sheet')), f=$('sheet').querySelector('.askfoot'), low=f?Math.min(v.bottom,f.getBoundingClientRect().top):v.bottom;
  const c={left:Math.max(b.left,v.left),top:Math.max(b.top,v.top),right:Math.min(b.right,v.right),bottom:Math.min(b.bottom,low)};
  return c.right>c.left&&c.bottom>c.top?c:null;
}
/* the frame that draws a whole picture laid out at box to as the box seen: as large as covers it, the rest clipped */
function shotFrame(to,seen,round){
  const W=to.right-to.left, H=to.bottom-to.top, w=seen.right-seen.left, h=seen.bottom-seen.top, s=Math.max(w/W,h/H);
  const cx=(W-w/s)/2, cy=(H-h/s)/2;
  return{transform:`translate(${(seen.left+seen.right-to.left-to.right)/2}px,${(seen.top+seen.bottom-to.top-to.bottom)/2}px) scale(${s})`,clipPath:`inset(${cy}px ${cx}px round ${round/s}px)`};
}
const shotThumb=i=>$('sheet').querySelector(`[data-shot="${i}"]`);
const shotBig=()=>$('sheet').querySelector('.shotbig img');
function shotGo(i){
  MO.folded=0;const sh=$('sheet');scrollStop(sh);
  const open=i>=0, old=S.askShot, go=()=>{
    if(open)SHOT.at=sh.scrollTop;
    S.askShot=i;render(true);sh.scrollTop=open?0:SHOT.at};
  if(calm()||!sh.animate){shotEnd();go();return}
  const parts=()=>[...sh.querySelectorAll('.asktop,.asktop+.small,.askfoot')].map(el=>[el,el.getBoundingClientRect()]);
  const box=shotSeen(sh), was=parts(), big0=!open&&shotBig(), from=open?SHOT.n===i&&SHOT.ghost||shotThumb(i):big0&&big0.complete&&big0.offsetHeight?big0:null;
  const seen=from&&(open&&from===SHOT.ghost?shotSeen(from):shotCut(shotSeen(from)));
  const round=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--r-m'))||0;
  const src=big0&&seen?big0.cloneNode():null, size=src&&[big0.offsetWidth,big0.offsetHeight];
  const pic=open&&from&&(from.naturalWidth?from:from.querySelector('img')), size0=pic&&pic.naturalWidth?[pic.naturalWidth,pic.naturalHeight]:null;
  shotEnd();go();
  const big=open&&shotBig();
  if(big&&!big.complete&&size0){  // not decoded yet: it takes its room at once, so the sheet is measured right
    Object.assign(big.style,{width:size0[0]+'px',aspectRatio:size0.join('/')});
    big.addEventListener('load',()=>{big.style.width=big.style.aspectRatio=''},{once:true})}
  const now=sh.getBoundingClientRect(), t=now.top-box.top, b=box.bottom-now.bottom;
  shotEdges(sh,t,b);
  parts().forEach(([el,r],j)=>{const w=was[j]&&was[j][1], y=w?w.top-r.top:0;if(w&&Math.abs(y)>=1&&w.bottom>box.top&&w.top<box.bottom)glideTo(el,0,y,SHOT_MO)});
  for(const el of sh.querySelectorAll('.askbody>:not(.shotbig)'))moAnim(el,[{opacity:0},{opacity:1}],{ease:'--ease',dur:'--dur'});
  if(!seen)return;
  if(open){
    const grow=()=>{
      if(!big.isConnected||!big.offsetHeight)return;
      const to=big.getBoundingClientRect();
      moAnim(big,[shotFrame(to,seen,round),{transform:'none',clipPath:`inset(0px round ${round}px)`}],SHOT_MO);
    };
    if(big)if(big.complete||size0)grow();else big.addEventListener('load',grow,{once:true});
    return;
  }
  const thumb=shotThumb(old), to=thumb&&shotCut(thumb.getBoundingClientRect());if(!to)return;
  /* a copy goes back, over the sheet: the thumbnail clips what is in it */
  src.className='shotfly';src.setAttribute('aria-hidden','true');src.alt='';
  const w=size[0], h=size[1], at={left:0,top:0,right:w,bottom:h};
  Object.assign(src.style,{width:w+'px',height:h+'px'});
  document.body.appendChild(src);
  const a=moAnim(src,[shotFrame(at,seen,round),shotFrame(at,to,round)],{...SHOT_MO,fill:'forwards'});
  if(!a){src.remove();return}
  SHOT.ghost=src;SHOT.n=old;a.onfinish=()=>{if(SHOT.ghost===src)SHOT.ghost=null;src.remove()};
  moAnim(thumb,[{opacity:0},{opacity:0}],SHOT_MO);
}
/* the sheet's box grew or shrank by t at its top and b at its foot: a clip goes over it, with room kept for what it lost */
function shotEdges(sh,t,b){
  if(Math.abs(t)<1&&Math.abs(b)<1)return;
  const cs=getComputedStyle(sh), px=n=>Math.max(0,n)+'px', round=cs.borderRadius||'0px';
  if(t>0)sh.style.paddingTop=parseFloat(cs.paddingTop)+t+'px';
  if(b>0)sh.style.paddingBottom=parseFloat(cs.paddingBottom)+b+'px';
  const a=moAnim(sh,[{clipPath:`inset(${px(-t)} 0px ${px(-b)} 0px round ${round})`},{clipPath:`inset(${px(t)} 0px ${px(b)} 0px round ${round})`}],SHOT_MO);
  SHOT.clip=a||{cancel(){}};
  if(a)a.onfinish=shotClip;else shotEnd();
}
function shotClip(){SHOT.clip=null;$('sheet').style.paddingTop=$('sheet').style.paddingBottom=''}
/* B222a: no typed word is in its markup: keepFields() and sheetDraw() put it back */
function needSheet(){
  const n=needOf(S.sheetArg);if(!n)return '';
  const i=S.snap.needs.indexOf(n), d=needD(n), big=d.shots[S.askShot], rep=needReplies(n), f=askField(n.id), said=S.giveSaid&&S.giveSaid.id===n.id?S.giveSaid:{}, secure=window.isSecureContext!==false;
  const body=big?`<button class="shotbig" data-shotclose aria-label="Back to the details"><img src="${esc(shotUrl(big))}" alt="${esc(big.caption||'Picture')}"></button>${big.caption?`<p class="small">${esc(big.caption)}</p>`:''}`
    :`${needBody(n,shotUrl,giveHTML(n,{secure,...said,done:giveDone(n,said,secure)}),S.askFold.text,I.chev)}${needPage(n)?`<a class="asklink" href="${esc(needPage(n))}" target="_blank" rel="noopener">Its page ${I.ext}</a>`:''}${askTask(n.id)?askWhyFold(n.id)+(needText(n)?'':askFold('task','Full task',(S.askText||{})[n.id])):''}`;
  const foot=needInputs(n).length?`<div class="askfoot end" data-k="askfoot">${needBtns(n,i)}</div>`:n.label==='TOOL'||n.label==='PR'?'':`<div class="askfoot" data-k="askfoot"><input class="fld" data-f="${esc(f)}" aria-label="${rep?'Your reply':'A note with your answer'}" placeholder="${rep?'Your reply':'Add a note (optional)'}" autocomplete="off">${needBtns(n,i,rep?`<button class="btn ${answerOpts(n).length?'':'pri'}" data-reply="${esc(n.id)}">Reply</button>`:'')}</div>`;
  return `<div class="asktop"><div class="grow"><h2>${needHead(n)}</h2>${needTitle(n)?`<div class="small">${esc(needTitle(n))}</div>`:''}</div>${big?'<button class="btn" data-shotclose>Back</button>':'<button class="btn" data-closesheet>Close</button>'}</div>
    <div class="small">${askChip(n,S.snap.kinds)?askChip(n,S.snap.kinds)+' ':''}<span class="asklab">${esc(needLab(n))}</span>${n.age?` · ${esc(n.age)}`:''}${askChip(n)?'':` · ${esc(n.id)}`}</div><div class="askbody">${body}</div>${foot}`;
}
/* F175a: Done on an item with inputs, under its fields. A field may be gone meanwhile (the item changed): its words show here */
function giveDone(n,said,secure){
  const xs=needInputs(n), off=!secure&&xs.some(x=>x.kind==='secret'), here=xs.some(x=>x.key===said.field&&(x.kind!=='secret'||secure));
  return `<div class="give">${said.out&&!here?`<div class="small v-bad" role="alert">${esc(said.out)}</div>`:''}${S.sure==='give:'+n.id&&said.confirm?sureHTML(said.confirm,'send it',`data-give="${esc(n.id)}"`):`<div class="btns"><button class="btn pri${S.giving===n.id?' busy':''}" data-give="${esc(n.id)}" ${off?'disabled':''}>Done</button></div>`}</div>`;
}
/* a secret typed for another item than `id` goes; `all`: every word typed for `id` goes, and its fields */
function giveForget(id,all){
  for(const k of Object.keys(S.f))if(all?k.startsWith(`give:${id}:`)||k.startsWith(`givesec:${id}:`):k.startsWith('givesec:')&&!(id&&k.startsWith(`givesec:${id}:`)))delete S.f[k];
  const el=$('sheet');
  for(const x of el.querySelectorAll('[data-f^="give"]')){
    const f=x.dataset.f;
    if(all?f.startsWith(`give:${id}:`)||f.startsWith(`givesec:${id}:`):f.startsWith('givesec:')&&!(id&&f.startsWith(`givesec:${id}:`))){x.value='';if(all){x.remove();el._h=''}}
  }
}
/* straight to the run, never through the outbox, which a browser keeps */
async function giveSend(id,confirm){
  const n=needOf(id);if(!n||S.giving)return;
  const values=Object.fromEntries(needInputs(n).map(x=>[x.key,S.f[giveField(id,x)]||'']));
  S.giving=id;S.giveSaid={};S.sure=null;render(true);
  let j;
  try{const r=await fetch(tq('give'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tid:id,values,confirm})});j=await r.json()}
  catch(e){j={ok:false,out:'Could not reach the run page. Nothing is known to be sent; try again.'}}
  S.giving='';
  const open=S.sheet==='need'&&S.sheetArg===id;
  if(j.ok){
    S.gone=goneMark(S.gone,j,Date.now());S.snap.needs=S.snap.needs.filter(x=>x.id!==id);
    if(open)closeSheet();
    giveForget(id,true);toast(answerSaid(j,id,'sent'));render(true);return}
  if(!open){if(!j.confirm)toast(plainOut(j,`${id} was not sent`),true);render(true);return}
  if(j.confirm){S.giveSaid={id,confirm:j.confirm};S.sure='give:'+id}
  else S.giveSaid={id,field:j.field||'',out:plainOut(j,'That was not sent.')};
  render(true);
  const el=j.confirm?$('sheet').querySelector('[data-give][data-sure]'):[...$('sheet').querySelectorAll('[aria-invalid]')][0];
  if(el){kbReveal(el,true);el.focus({preventScroll:true})}
}
async function askLoad(id){
  if(!askTask(id))return;
  const one=async(path,key)=>{let got;
    try{const j=await (await fetch(tq(path+encodeURIComponent(id)))).json();got=j.ok?{text:j.text}:{err:plainOut(j,'It could not be read')}}
    catch(e){got={err:'Could not reach the run page'}}
    S[key]={...(S[key]||{}),[id]:got};if(S.sheet==='need'&&S.sheetArg===id&&S.askFold[key==='askWhy'?'why':'task'])MO.folded=Date.now();render(true)};
  await Promise.all([one('why/','askWhy'),one('task/','askText')]);
}
function needOpen(id){if(!needOf(id))return;shotEnd();S.askShot=-1;S.askFold={};S.giveSaid={};openSheet('need',id);askLoad(id)}
function needReply(id){
  const n=needOf(id), text=String(S.f[askField(id)]||'').trim();if(!n)return;
  if(!text)return toast('Write your reply first',true);
  outbox('answer',{tid:id,text},{need:id,say:`${id} · replied “${text}”`});
}
/* F85: a task's row: one line; a tap folds its whole text (plan ID) open in place, or `lead` in the text's place. F426b: one
   row of a `list` is open (S.taskOpen[list], its id); a row inside another ('wait:V1') has keys of its own */
const taskIsOpen=(list,id)=>S.taskOpen[list]===id;
function taskRow(q,title,more='',list='queue',lead=''){
  const open=taskIsOpen(list,q.id), t=S.tasks[q.id], k=list.startsWith('wait:')?list+':'+q.id:q.id;
  const text=()=>t&&t.text?`<pre class="tasktext" data-k="text:${esc(k)}">${esc(t.text)}</pre>`:t&&t.err?(t.old?oldRunHTML(t.err):`<div class="small v-bad">${esc(t.err)}</div>`):'<div class="small">Loading…</div>';
  const words=q.release?(open?relWaits:relWords)(q.release):planWords(q,S.snap.sessions);
  // B846: the words that name the chat that took it open that chat: a button of their own, under the head
  const way=q.way&&q.way.chat&&words===q.way.words?`<button class="waychat small" data-way="1" data-thread="${esc(q.way.chat)}" data-k="state:${esc(k)}"><span class="ell">${esc(words)}</span>${I.chev}</button>`:'';
  return `<button class="fold" data-task="${esc(q.id)}" data-list="${esc(list)}" aria-expanded="${open}">${taskChip(q.id)}<span class="grow"><b class="ell">${esc(title)}</b>${way?'':`<span class="small" data-k="state:${esc(k)}" data-v="${esc(q.state||'')}">${esc(words)}</span>`}</span><span class="chev">${I.chev}</span></button>${way}${open?foldIn(k,(lead||text())+more):''}`;
}
async function openTask(id,list='queue'){
  const on=!taskIsOpen(list,id);
  delete S.taskOpen['wait:'+(S.taskOpen[list]||'')];  // a release that shuts shuts its tasks
  for(const l of Object.keys(S.taskOpen))if(taskIsOpen(l,id))delete S.taskOpen[l];  // a task is open in one list: its question is asked once
  if(on)S.taskOpen[list]=id;else delete S.taskOpen[list];
  if(String(S.readTask||'').startsWith(list+':'))S.readTask='';
  render(true);
  if(!on)return;
  taskInView(id,list);
  if(/^s\d+$/.test(id))return;  // F426e: an idle slot's row, which is no task
  try{const j=await (await fetch(tq('task/'+encodeURIComponent(id)))).json();S.tasks[id]=j.ok?{text:j.text,writeup:j.writeup||''}:{err:plainOut(j,'It could not be read'),old:oldRun(j)}}
  catch(e){if(!S.tasks[id])S.tasks[id]={err:'Could not reach the run page: fold it and open it again'}}
  if(taskIsOpen(list,id))MO.folded=Date.now();  // what the press opened goes on to its words
  render(true);
}
/* F426b: the row that closed above may have taken the opened one up out of view, or under the search */
function taskInView(id,list){
  const b=$('body'), el=[...b.querySelectorAll('[data-task]')].find(x=>x.dataset.task===id&&x.dataset.list===list), bar=b.querySelector('.planq');
  if(!el)return;
  const d=el.getBoundingClientRect().top-flying(el)-b.getBoundingClientRect().top-(bar?bar.offsetHeight:0)-22;  // its card's top too
  if(d<0)scrollGlide(b,b.scrollTop+d);
}
/* a task's options: Chat is the last (F426b) */
const chatBtn=q=>`<button class="btn" data-about="plan:${esc(q.id)}">Chat</button>`;
const taskBtns=(q,acts=q.acts)=>`<div class="btns" data-k="acts:${esc(q.id)}">${actBtns(acts,q.id)}${chatBtn(q)}</div>${actSure(acts,q.id)}`;
/* F186: a release's Drop, there until it starts (ui_model's `acts`) */
const relDrop=q=>(q.acts||[]).filter(k=>k==='queue_drop');
const planCard=(q,list='queue')=>card(taskRow(q,q.title||q.id,taskBtns(q),list)+rowMenu(q,list)+rowGrip(q,list),'',`data-k="task:${esc(q.id)}"`);
/* F426b: an open release: it opens to the tasks it waits for, each a row that opens too; one that waits for none, to its text */
const relWaits=r=>((r.waits||[]).length?`waits for ${r.waits.length}`:r.words)+(r.note||'');
/* B825: shut, its row never names them: on a phone they took seven lines */
const WAITS_ALL='Waits for everything above';
const relWords=r=>{const n=(r.waits||[]).length;return !n?r.words:r.everything?WAITS_ALL:`Waits for ${n} ${n===1?'task':'tasks'}`};
function releaseRow(q,list='queue'){
  const r=q.release, in_='wait:'+q.id;
  const one=w=>{const t=(S.snap.queue||[]).concat(S.snap.shelved||[]).find(x=>x.id===w.id);
    return `<div class="srow" data-k="${esc(in_)}:${esc(w.id)}">${taskRow(t||{...w,state:'open'},(t||w).title||w.id,t?taskBtns(t).replace('data-k="acts:',`data-k="acts:${esc(in_)}:`):'',in_)}</div>`};
  return taskRow(q,r.title||q.title||q.id,taskBtns(q,relDrop(q)),list,(r.waits||[]).length?`<div class="waits">${r.waits.map(one).join('')}</div>`:'');
}
const releaseCard=(q,list)=>card(releaseRow(q,list)+rowMenu(q,list)+rowGrip(q,list),'',`data-k="task:${esc(q.id)}"`);
/* F131: the auto release's count, which is no open task, dimmed; F195c: in the Queue */
const nextReleaseRow=r=>`<div class="row"><div class="grow"><b class="ell">${esc(r.title||'Next release')}</b><span class="small">${esc((r.id?r.id+' · ':'')+(r.words||''))}</span></div></div>`;
const nextReleaseCard=r=>card(nextReleaseRow(r)+rowMenu(r)+rowGrip(r),'relph','data-k="rel:next"');
const queueCard=q=>q.removed?removedCard(q):typeof partCard==='function'&&(q.partOf||partsOf(q).length)?partCard(q):q.placeholder?nextReleaseCard(q):q.release?releaseCard(q):planCard(q);
function parkedCard(q,list='parked'){  // B118: a parked task: Unpark (plan edit ID --pri normal) and the usual chat about it
  return card(taskRow(q,q.title||q.id,'',list)+taskBtns(q),'',`data-k="task:${esc(q.id)}"`);
}
function shelvedCard(q,list='parked'){  // F184: a shelved task: what it waits on the person for, Bring back (plan unshelve), Drop and the usual chat
  return card(`${taskRow(q,q.title||q.id,'',list)}${q.ask?`<span class="askdo" data-k="askdo:${esc(q.id)}">${esc(q.ask)}</span>`:''}
    ${taskBtns(q)}`,'',`data-k="task:${esc(q.id)}"`);
}
/* F197b: a concept with a Needs you item draws as that item's Home card (same buttons, same posted actions), with its New/Updated badge */
function conceptNeedCard(c){
  const ns=S.snap.needs||[], j=ns.findIndex(n=>n.id===c.id);if(j<0)return '';
  const b=c.news_words?`<span class="small cnews" data-k="cnews:${esc(c.id)}">${esc(c.news_words)}</span>`:'';
  return card(b+needTap(ns[j],S.snap.kinds)+conceptFrame(ns[j])+needBtns(ns[j],j),'need',`data-k="concept:${esc(c.id)}"`);
}
function conceptCard(c,i){  // B219a: its one Chat is the new chat view; concept_chat, which starts a session at once, is the TUI's
  const nc=conceptNeedCard(c);if(nc)return nc;
  const os=c.options||[], acts=(c.acts||[]).filter(k=>k!=='concept_chat'), view=c.copy?tq('concept/'+encodeURIComponent(c.concept||c.id)):c.url;
  const b=x=>x.pick!=null?`<button class="btn ${x.rec?'pri':''}" data-pick="${i}" data-o="${x.pick}">${esc(x.label)}</button>`
    :x.about?`<button class="btn" data-about="concept:${i}">Chat</button>`
    :`<a class="btn" href="${esc(view)}" target="_blank" rel="noopener">View ${I.ext}</a>`;
  return card(`<div class="q">${esc(c.title||c.concept)}</div><span class="small">${taskChip(c.concept||c.id)}${os.length?` · ${os.length} options${os.some(o=>o.rec)?` · recommends ${esc(optionName(os.find(o=>o.rec)))}`:''}`:''}${c.page&&c.waits?' · also waits in Needs you':''}</span>
    <div class="btns">${conceptButtons(c).map(b).join('')}${actBtns(acts,c.id)}</div>${actSure(acts,c.id)}`,'',`data-k="concept:${esc(c.id)}"`);
}
function box(ph,foot){
  const a=S.atts[boxKey()]||[], shownNow=shownSession(), real=!!S.thread&&!isNew(S.thread), busyNow=!!shownNow&&(real?sessWorks(shownNow):busy(shownNow));
  return `<form class="box" data-form>
    ${a.length?`<div class="atts">${a.map((f,i)=>`<span class="att ${f.path?'':f.err?'err':'up'}" title="${esc(f.err||f.path||'uploading…')}">${f.thumb?`<img src="${f.thumb}" alt="">`:`<span class="fi">${I.file}</span>`}<span class="nm">${esc(f.name)}</span><button type="button" class="x" data-unatt="${i}" aria-label="Remove">✕</button></span>`).join('')}</div>`:''}
    <div class="slash" data-slash role="listbox" aria-label="Commands" hidden></div>
    <div class="inrow"><span class="pr" aria-hidden="true">&gt;</span><textarea rows="1" data-in${enterHint()} placeholder="${esc(ph)}" aria-label="Message"></textarea></div>
    <div class="boxrow"><button type="button" class="tool" data-clip aria-label="Attach pictures or files" title="Attach pictures or files">${I.clip}</button>${S.view==='talk'&&!S.thread?`<button type="button" class="tool spkbox" id="spkbox" data-spk hidden aria-label="Stop speaking" title="Stop speaking">${I.stop}</button>`+(micWhy()?'':`<button type="button" class="tool" data-talkmode="mic" aria-label="Talk instead" title="Talk instead">${I.talk}</button>`):S.view==='home'&&!S.thread?'':dictButton(dictWhy(),!!DK.rec,I.talk)}${S.thread&&!isNew(S.thread)?`<button type="button" class="tool keyb" data-feedkeys aria-expanded="${keysShown()}" aria-label="Keys for the session" title="Keys for the session">${I.keys}</button>`:''}${real&&!modelOf(S.thread)?'<button type="button" class="tool" data-slashopen aria-label="Commands" title="Commands">/</button>':''}${real&&busyNow?'':`<span class="to">${esc(isNew(S.thread)?'to a new chat':S.thread?S.thread:S.view==='talk'?'to Talk':'to a new chat')}</span>`}${real&&busyNow?`<button type="button" class="act halt" data-halt="${esc(shownNow)}">${I.stop}Stop</button>`:busyNow?`<button type="button" class="send stop" data-stop="${esc(shownNow)}" aria-label="Interrupt">${I.stop}</button>`:''}<button class="send" data-send aria-label="Send" title="Send">${I.send}</button></div></form>${foot?`<div class="foot">${foot}</div>`:''}`;
}
/* B177: a chat with a transcript that the run no longer lists (one just started is not listed yet: its message waits) */
const ended=n=>!!(S.snap.at&&S.feeds[n]&&S.feeds[n].ok&&!sessionOf(n)&&!(S.sent[n]&&(S.sent[n].pending||[]).length));
