const card=(h,cls='',attr='')=>`<div class="card ${cls}" ${attr}>${h}</div>`;
function agentCard(s){
  if(!s.task)return card(`<div class="row"><div class="who">${esc(s.name)}</div><div class="grow"><b>Idle</b><div class="small">Nothing it can start right now</div></div></div>`);
  const w=lastWords(s.name);
  return card(`<div class="row"><div class="who">${esc(s.name)}</div><div class="grow"><b class="ell">${esc(s.title||s.task)}</b><span class="status"><span class="livedot"></span>${s.state==='merging'?'Landing':'Working'}${s.minutes!=null?` · ${s.minutes} min`:''}</span></div><span class="chev">${I.chev}</span></div>${w?`<div class="quote">${esc(w)}</div>`:''}`,'tap',`tabindex="0" data-thread="${esc(s.name)}" data-k="slot:${esc(s.name)}:${esc(s.task)}" data-v="${esc(s.state)}"`);
}
/* F82: the run controls, from the snapshot's one list (ui_model.RUN_CONTROLS); F124: the everyday ones on the Run card,
   the rest in the More… sheet; one with a confirm question asks in place first */
const controlsOf=w=>(S.snap.controls||[]).filter(c=>c.where===w);
const controlOf=k=>(S.snap.controls||[]).find(c=>c.key===k);
const ctlBusy=(k,tid)=>S.ob.some(x=>x.ctl===k+':'+(tid||'')&&x.state==='sending');
/* a confirm, asked where the control stands (docs/STYLE.md): attr, the Yes button's own data- attributes */
const sureHTML=(q,yes,attr)=>`<div class="sure" data-k="sure" role="group"><div class="small">${esc(q)}</div><div class="btns"><button class="btn bad" ${attr} data-sure>Yes, ${esc(yes)}</button><button class="btn" data-unsure>No</button></div></div>`;
/* what a control would cut off: each slot's task and how long it has run (stop now, suspend, shut down) */
function cutsOff(c){
  if(!['stop_now','suspend','shutdown'].includes(c.key)||c.key===(S.snap.run||{}).power)return '';
  const ws=working_();return ws.length?`Cuts off ${ws.map(w=>`${w.task} in ${w.name}${w.minutes!=null?` (${w.minutes} min in)`:''}`).join(', ')}. `:'';
}
const ctlSure=(c,tid)=>sureHTML(cutsOff(c)+((((S.snap.queue||[]).find(q=>tid&&q.id===tid)||{}).asks||{})[c.key]||c.confirm.split('{id}').join(tid||'')),c.label.charAt(0).toLowerCase()+c.label.slice(1),`data-ctl="${esc(c.key)}" data-tid="${esc(tid||'')}"`);
/* C34: a panel's row actions ('queue', 'release': ui_model.RUN_CONTROLS' `where`): the buttons for a row's `acts` (the
   keys ui_model allowed on it), each through the one data-ctl handler, and the confirm one asks in place */
const obActs=(x,where)=>!!x.ctl&&(controlOf(x.ctl.split(':')[0])||{}).where===where;
const obRun=x=>!!x.ctl&&!['queue','shelved','release','need','concept'].includes((controlOf(x.ctl.split(':')[0])||{}).where);
const actBtns=(acts,tid,labels={},pri='')=>(acts||[]).map(controlOf).filter(Boolean).map(c=>`<button class="btn${c.key===pri?' pri':''}${ctlBusy(c.key,tid)?' busy':''}" data-ctl="${esc(c.key)}" data-tid="${esc(tid)}">${esc(labels[c.key]||c.label)}</button>`).join('');
/* F180: a Needs you row's fixed answers among its actions (the first is the main button; a pitch draws only that one,
   Not this… has the rest), and its other actions */
const isAnswer=k=>!!(controlOf(k)||{}).answer;
/* F181c: what its answer buttons say ('Full (recommended)'); what is sent is the row's labels ('Full') */
const ansWords=(n,ks)=>Object.fromEntries(ks.map((k,j)=>[k,((n.answers||[])[j]||{}).label]).filter(x=>x[1]));
const ansBtns=n=>{const ks=(n.acts||[]).filter(isAnswer);return actBtns(n.label==='PITCH'?ks.slice(0,1):ks,n.id,{...n.labels,...ansWords(n,ks)},ks[0])};
const restBtns=n=>actBtns((n.acts||[]).filter(k=>!isAnswer(k)),n.id,n.labels);
const actSure=(acts,tid)=>(acts||[]).map(controlOf).filter(c=>c&&S.sure===c.key+':'+tid).map(c=>ctlSure(c,tid)).join('');
function slotRow(s){
  if(!s.task)return `<div class="srow" data-k="slot:${esc(s.name)}:"><div class="row"><div class="who">${esc(s.name)}</div><div class="grow small">Idle: nothing it can start right now</div></div></div>`;
  const w=lastWords(s.name), tc=taskControlsOn(s)?controlsOf('task'):[];
  return `<div class="srow" data-k="slot:${esc(s.name)}:${esc(s.task)}"><button class="fold" data-thread="${esc(s.name)}"><span class="who">${esc(s.name)}</span><span class="grow"><b class="ell">${esc(s.title||s.task)}</b><span class="status" data-k="st:${esc(s.name)}" data-v="${esc(s.state)}"><span class="livedot"></span>${s.state==='merging'?'Landing':'Working'}${s.minutes!=null?` · ${s.minutes} min`:''}</span></span><span class="chev">${I.chev}</span></button>${w?`<div class="quote">${esc(w)}</div>`:''}${tc.length?`<div class="btns">${tc.map(c=>`<button class="btn${ctlBusy(c.key,s.task)?' busy':''}" data-ctl="${esc(c.key)}" data-tid="${esc(s.task)}">${esc(c.label)}</button>`).join('')}</div>`:''}</div>`;
}
/* F168: the shared tools in words, the same as status says */
const toolsWords=ts=>'Tools: '+ts.map(t=>`${t.label}: ${t.words}`).join(' · ');
/* Run controls: the Run card */
function controlsCard(){
  const run=S.snap.run||{}, up=S.snap.up!==false, ss=slots();
  const said=!up?'No run is up.':[run.paused?'Paused: no new tasks start':'',run.stopping?'Stopping: the running tasks finish, nothing new starts':'',run.forced?'Usage caps off':'',run.power?`${run.power==='suspend'?'Suspends':'Shuts down'} once it stops`:''].filter(Boolean).join(' · ')||'Running';
  const b=cardControls(S.snap).map(k=>{const c=controlOf(k);return c?`<button class="btn ${k==='start'||k==='go_on'||k==='stop_undo'?'acc':''}${ctlBusy(k)?' busy':''}" data-ctl="${esc(k)}">${esc(k==='stop'?'Stop':c.label)}</button>`:''}).join('');
  return card(`<div class="row"><div class="grow"><b>Run</b><div class="small" data-k="runsaid" data-roll data-v="${esc(said)}">${esc(said)}</div></div>${up?(w=>`<span class="small" data-k="slotsof" data-roll data-v="${w}">${w}</span>`)(`${working_().length} of ${S.snap.slots||0} slot${S.snap.slots===1?'':'s'}`):''}</div>
    ${S.snap.no_settings?`<div class="small" data-k="nosettings"><span class="v-warn">${esc(S.snap.no_settings)}</span></div>`:''}
    ${S.snap.unpushed?`<div class="small" data-k="unpushed" data-v="${esc(S.snap.unpushed)}">${esc(S.snap.unpushed)}</div>`:''}
    ${(S.snap.tools||[]).length?`<div class="small" data-k="tools" data-v="${esc(toolsWords(S.snap.tools))}">${esc(toolsWords(S.snap.tools))}</div>`:''}
    ${ss.map(slotRow).join('')}
    ${obCards(obRun)}${controlsOf('run').length?`<div class="btns tight" role="group" aria-label="Run controls">${b}<button class="btn" data-sheet="run">More…</button></div>`:''}`,'','data-k="run"');
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
  if(n.label==='PITCH'){const on=!!(S.pitchOpen||{})[n.id];
    return `<div class="btns">${ansBtns(n)}<button class="btn" data-pitchopen="${i}" aria-expanded="${on}">Not this…</button>${more}${restBtns(n)}${open(n.url||(n.copy?tq('concept/'+encodeURIComponent(n.id)):''))}</div>${on?pitchNo(n,i):''}`}
  if(n.label==='TOOL')return '';  // F168: nothing to answer, it clears once the tool is back
  return `<div class="btns">${needInputs(n).length?'':ansBtns(n)}${more}${restBtns(n)}${open(n.url)}</div>${actSure(n.acts,n.id)}`;
}
const needCard=(n,i)=>card(needTap(n)+needBtns(n,i),'need',`data-k="need:${esc(n.id)}"`);
/* F162: the popup of one Needs you item: everything about it, its answers always on screen at the foot */
const needOf=id=>((S.snap&&S.snap.needs)||[]).find(n=>n.id===id);
const shotUrl=s=>tq('shot/'+s.src.split('/').map(encodeURIComponent).join('/'));
const askField=id=>'askre:'+id;
const askTask=id=>!/^(tool-|pitch)/.test(id);
function askFold(key,label,got){
  const on=!!S.askFold[key];
  return `<button class="fold" data-askfold="${key}" aria-expanded="${on}"><span class="grow"><b>${label}</b></span><span class="chev">${I.chev}</span></button>${on?`<div class="asktext">${!got?'<div class="small">Loading…</div>':got.err?`<div class="small v-bad">${esc(got.err)}</div><div class="btns"><button class="btn" data-askload>Retry</button></div>`:taskParas(got.text).map(p=>`<p>${esc(p)}</p>`).join('')||'<div class="small">There are no words of it.</div>'}</div>`:''}`;
}
/* F162a2: only when there are words of the agent */
function askWhyFold(id){const got=(S.askWhy||{})[id];return got&&got.text?askFold('why','Why it waits',got):''}
function needSheet(){
  const n=needOf(S.sheetArg);if(!n)return '';
  const i=S.snap.needs.indexOf(n), d=needD(n), big=d.shots[S.askShot], rep=needReplies(n), f=askField(n.id), said=S.giveSaid&&S.giveSaid.id===n.id?S.giveSaid:{}, secure=window.isSecureContext!==false;
  const body=big?`<button class="shotbig" data-shotclose aria-label="Back to the details"><img src="${esc(shotUrl(big))}" alt="${esc(big.caption||'Picture')}"></button>${big.caption?`<p class="small">${esc(big.caption)}</p>`:''}`
    :`${needBody(n,shotUrl,giveHTML(n,{secure,...said,done:giveDone(n,said,secure)}))}${n.url?`<a class="asklink" href="${esc(n.url)}" target="_blank" rel="noopener">Its page ${I.ext}</a>`:''}${askTask(n.id)?askWhyFold(n.id)+askFold('task','Full task',(S.askText||{})[n.id]):''}`;
  const foot=needInputs(n).length?`<div class="askfoot end">${needBtns(n,i)}</div>`:n.label==='TOOL'?'':`<div class="askfoot"><input class="fld" data-f="${esc(f)}" aria-label="${rep?'Your reply':'A note with your answer'}" placeholder="${rep?'Your reply':'Add a note (optional)'}" autocomplete="off" value="${esc(S.f[f]||'')}">${needBtns(n,i,rep?`<button class="btn ${answerOpts(n).length?'':'pri'}" data-reply="${esc(n.id)}">Reply</button>`:'')}</div>`;
  return `<div class="asktop"><h2>${esc(d.title)}</h2>${big?'<button class="btn" data-shotclose>Back</button>':'<button class="btn" data-closesheet>Close</button>'}</div>
    <div class="small"><span class="asklab">${esc(needLab(n))}</span>${n.age?` · ${esc(n.age)}`:''} · ${esc(n.id)}</div><div class="askbody">${body}</div>${foot}`;
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
  if(el){el.focus({preventScroll:true});kbReveal(el)}
}
async function askLoad(id){
  if(!askTask(id))return;
  const one=async(path,key)=>{let got;
    try{const j=await (await fetch(tq(path+encodeURIComponent(id)))).json();got=j.ok?{text:j.text}:{err:plainOut(j,'It could not be read')}}
    catch(e){got={err:'Could not reach the run page'}}
    S[key]={...(S[key]||{}),[id]:got};render(true)};
  await Promise.all([one('why/','askWhy'),one('task/','askText')]);
}
function needOpen(id){if(!needOf(id))return;S.askShot=-1;S.askFold={};S.giveSaid={};openSheet('need',id);askLoad(id)}
function needReply(id){
  const n=needOf(id), text=String(S.f[askField(id)]||'').trim();if(!n)return;
  if(!text)return toast('Write your reply first',true);
  outbox('answer',{tid:id,text},{need:id,say:`${id} · replied “${text}”`});
}
/* F85: a task's row: one line; a tap folds its whole text (plan ID) open in place */
function taskRow(q,title){
  const open=!!S.taskOpen[q.id], t=S.tasks[q.id];
  return `<button class="fold" data-task="${esc(q.id)}" aria-expanded="${open}"><span class="grow"><b class="ell">${esc(title)}</b><span class="small" data-k="state:${esc(q.id)}" data-v="${esc(q.state||'')}">${esc(q.id)} · ${esc(open&&q.release?(q.release.all||q.release.words)+(q.release.note||''):planWords(q,S.snap.sessions))}</span></span><span class="chev">${I.chev}</span></button>${open?(t&&t.text?`<pre class="tasktext" data-k="text:${esc(q.id)}">${esc(t.text)}</pre>`:t&&t.err?(t.old?oldRunHTML(t.err):`<div class="small v-bad">${esc(t.err)}</div>`):'<div class="small">Loading…</div>'):''}`;
}
async function openTask(id){
  S.taskOpen[id]=!S.taskOpen[id];render(true);
  if(!S.taskOpen[id])return;
  try{const j=await (await fetch(tq('task/'+encodeURIComponent(id)))).json();S.tasks[id]=j.ok?{text:j.text}:{err:plainOut(j,'It could not be read'),old:oldRun(j)}}
  catch(e){if(!S.tasks[id])S.tasks[id]={err:'Could not reach the run page: fold it and open it again'}}
  render(true);
}
/* F186: a release's Drop, there until it starts (ui_model's `acts`) */
const relDrop=q=>(q.acts||[]).filter(k=>k==='queue_drop');
const releaseCard=q=>planCard(q,true);
function planCard(q,rel){
  const drop=rel===true?relDrop(q):[];
  return card(`${taskRow(q,(q.release&&q.release.title)||q.title||q.id)}${S.taskOpen[q.id]?`<div class="btns"><button class="btn" data-about="plan:${esc(q.id)}">Chat</button>${actBtns(q.acts,q.id)}</div>${actSure(q.acts,q.id)}`:drop.length?`<div class="btns">${actBtns(drop,q.id)}</div>${actSure(drop,q.id)}`:''}`,'',`data-k="task:${esc(q.id)}"`);
}
function nextReleaseCard(r){  // F131, F185: a release that is no open task (the auto release's count, the last one released), dimmed
  return card(`<div class="row"><div class="grow"><b class="ell">${esc(r.title||'Next release')}</b><span class="small">${esc((r.id?r.id+' · ':'')+(r.words||''))}</span></div></div>`,'relph');
}
function parkedCard(q){  // B118: a parked task: Unpark (plan edit ID --pri normal) and the usual chat about it
  return card(`${taskRow(q,q.title||q.id)}
    <div class="btns">${actBtns(q.acts,q.id)}<button class="btn" data-about="plan:${esc(q.id)}">Chat</button></div>${actSure(q.acts,q.id)}`,'',`data-k="task:${esc(q.id)}"`);
}
function shelvedCard(q){  // F184: a shelved task: what it waits on the person for, Bring back (plan unshelve), Drop and the usual chat
  return card(`${taskRow(q,q.title||q.id)}${q.ask?`<span class="askdo">${esc(q.ask)}</span>`:''}
    <div class="btns">${actBtns(q.acts,q.id)}<button class="btn" data-about="plan:${esc(q.id)}">Chat</button></div>${actSure(q.acts,q.id)}`,'',`data-k="task:${esc(q.id)}"`);
}
function conceptCard(c,i){
  const os=c.options||[], view=c.copy?tq('concept/'+encodeURIComponent(c.concept||c.id)):c.url;
  const b=x=>x.pick!=null?`<button class="btn ${x.rec?'pri':''}" data-pick="${i}" data-o="${x.pick}">${esc(x.label)}</button>`
    :x.about?`<button class="btn" data-about="concept:${i}">Chat</button>`
    :`<a class="btn" href="${esc(view)}" target="_blank" rel="noopener">View ${I.ext}</a>`;
  return card(`<div class="q">${esc(c.title||c.concept)}</div><span class="small">${esc(c.concept||c.id)}${os.length?` · ${os.length} options${os.some(o=>o.rec)?` · recommends ${esc(optionName(os.find(o=>o.rec)))}`:''}`:''}</span>
    <div class="btns">${conceptButtons(c).map(b).join('')}${actBtns(c.acts,c.id)}</div>${actSure(c.acts,c.id)}`,'',`data-k="concept:${esc(c.id)}"`);
}
function box(ph,foot){
  const a=S.atts[boxKey()]||[], shownNow=shownSession(), real=!!S.thread&&!isNew(S.thread), busyNow=!!shownNow&&(real?sessWorks(shownNow):busy(shownNow));
  return `<form class="box" data-form>
    ${a.length?`<div class="atts">${a.map((f,i)=>`<span class="att ${f.path?'':f.err?'err':'up'}" title="${esc(f.err||f.path||'uploading…')}">${f.thumb?`<img src="${f.thumb}" alt="">`:`<span class="fi">${I.file}</span>`}<span class="nm">${esc(f.name)}</span><button type="button" class="x" data-unatt="${i}" aria-label="Remove">✕</button></span>`).join('')}</div>`:''}
    <div class="slash" data-slash role="listbox" aria-label="Commands" hidden></div>
    <div class="inrow"><span class="pr" aria-hidden="true">&gt;</span><textarea rows="1" data-in${enterHint()} placeholder="${esc(ph)}" aria-label="Message"></textarea></div>
    <div class="boxrow"><button type="button" class="tool" data-clip aria-label="Attach pictures or files" title="Attach pictures or files">${I.clip}</button>${S.view==='talk'&&!S.thread?`<button type="button" class="tool spkbox" id="spkbox" data-spk hidden aria-label="Stop speaking" title="Stop speaking">${I.stop}</button>`+(micWhy()?'':`<button type="button" class="tool" data-talkmode="mic" aria-label="Talk instead" title="Talk instead">${I.talk}</button>`):dictButton(dictWhy(),!!DK.rec,I.talk)}${S.thread&&!isNew(S.thread)?`<button type="button" class="tool keyb" data-feedkeys aria-expanded="${!!S.keys}" aria-label="Keys for the session" title="Keys for the session">${I.keys}</button>`:''}${real?'<button type="button" class="tool" data-slashopen aria-label="Commands" title="Commands">/</button>':''}${real&&busyNow?'':`<span class="to">${esc(isNew(S.thread)?'to a new chat':S.thread?S.thread:S.view==='talk'?'to Talk':'to a new chat')}</span>`}${real&&busyNow?`<button type="button" class="act halt" data-halt="${esc(shownNow)}">${I.stop}Stop</button>`:busyNow?`<button type="button" class="send stop" data-stop="${esc(shownNow)}" aria-label="Interrupt">${I.stop}</button>`:''}<button class="send" data-send aria-label="Send" title="Send">${I.send}</button></div></form>${foot?`<div class="foot">${foot}</div>`:''}`;
}
/* B177: a chat with a transcript that the run no longer lists (one just started is not listed yet: its message waits) */
const ended=n=>!!(S.snap.at&&S.feeds[n]&&S.feeds[n].ok&&!sessionOf(n)&&!(S.sent[n]&&(S.sent[n].pending||[]).length));
