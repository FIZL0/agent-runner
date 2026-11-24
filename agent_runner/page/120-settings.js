/* --- F97: Settings ------------------------------------------------------------------------------------------- */
async function loadSettings(){
  // B164: only a whole answer is kept: an error (a run without this route) leaves the settings already there
  try{const r=await fetch(tq('settings')), j=await r.json();S.setOld=false;
    if(r.ok&&j&&Array.isArray(j.tables)){S.set=j;S.setErr=j.out||''}
    else{S.setOld=oldRun(j);S.setErr=plainOut(j,'The settings could not be read.')}}
  catch(e){S.setOld=false;S.setErr='Could not reach the run page to read the settings.'}
  render(true);
}
/* F166: the Settings view: the everyday settings with their control on the row, the rest behind Advanced and Project
   file. A setting has one home: 'device' saves in runner.local.toml, 'everyone' in runner.toml, both at once. `side` is where its row saves. */
const settingId=k=>`${k.table}.${k.key}`;
const settingOf=id=>{const x=S.set&&S.set.tables&&S.set.tables.find(t=>t.table===id.split('.')[0]);return x&&x.keys.map(k=>({...k,table:x.table})).find(k=>settingId(k)===id)};
const settingsAll=d=>d.tables.flatMap(t=>t.keys.map(k=>({...k,table:t.table}))).sort((a,b)=>a.order-b.order);
const PLACE={device:'this device',project:'everyone',everyone:'everyone'};
const setField=(id,side)=>`set:${side}:${id}`;
/* the words in a setting's field on `side`: what is typed, else what is kept */
function settingNow(k,side,field){
  const f=setField(settingId(k),side);
  if(f in S.f)return S.f[f];
  return k['has_'+side]?settingText(k[side]):field?settingText(k.value):'';
}
/* F174: its two controls; on its row a change saves at once */
function partsField(k,side,onRow){
  const t=settingNow(k,side,true), v=partsNow(t), p=k.parts, d=`data-id="${esc(settingId(k))}" data-side="${side}"${onRow?' data-now':''}`, at=esc(`, ${k.name}, ${PLACE[side]}`);
  return `<div class="setparts"><label>${esc(p.every.label)} <select class="fld" data-setpart="every" ${d} aria-label="${esc(p.every.label)}${at}">${partOptions(k,t).map(([n,l])=>`<option value="${n}" ${n===v.every?'selected':''}>${esc(l)}</option>`).join('')}</select></label>
    <label>${esc(p.idle.label)} <input type="checkbox" role="switch" class="sw" data-setpart="idle" ${d} aria-label="${esc(p.idle.label)}${at}" ${v.idle?'checked':''}></label></div>`;
}
function savePart(el){
  const {id,side,setpart}=el.dataset, k=settingOf(id);if(!k)return;
  S.f[setField(id,side)]=partSet(settingNow(k,side,true),setpart,setpart==='idle'?el.checked:Number(el.value));
  if(el.dataset.now!==undefined)saveSetting(id,side);
}
function settingField(k,side,onRow){
  if(hasParts(k))return partsField(k,side,onRow);
  const id=settingId(k), now=settingNow(k,side,true), d=`data-f="${esc(setField(id,side))}"${onRow?' data-now':''} aria-label="${esc(k.name)}, ${PLACE[side]}"`;
  if(k.type==='switch')return `<input type="checkbox" role="switch" class="sw" ${d} data-sw ${now==='true'?'checked':''}>`;
  const opts=pickOptions(k,now);
  if(opts)return `<select class="fld setpick" ${d}>${opts.map(([v,l])=>`<option value="${esc(v)}" ${v===now?'selected':''}>${esc(l)}</option>`).join('')}</select>`;
  if(k.type==='list'||k.type==='table'||now.length>40)return `<textarea class="fld" rows="3" ${d} placeholder="${k.type==='list'?'one per line':k.type==='table'?'{ key = value }':'not set'}">${esc(now)}</textarea>`;
  return `<input class="fld" ${k.type==='number'?'inputmode="decimal"':''} ${d} value="${esc(now)}" placeholder="not set" autocomplete="off" autocapitalize="off" spellcheck="false">`;
}
const onRow=k=>k.type==='switch'||hasParts(k)||!!pickOptions(k,'');
/* what stands at the right of a folded row: its control, or its value when it is typed in the open row */
function settingControl(k,side,readonly){
  if(readonly)return `<span class="setval">${esc(settingSays(k,settingText(k.value)))}</span>`;
  if(settingId(k)==='run.slots'){const n=settingNow(k,side,true), id=esc(settingId(k));
    return `<span class="step" role="group" aria-label="${esc(k.name)}"><button class="btn" data-setstep="-1" data-id="${id}" aria-label="Fewer" ${Number(n)<2?'disabled':''}>−</button><b>${esc(n)}</b><button class="btn" data-setstep="1" data-id="${id}" aria-label="More">+</button></span>`}
  if(hasParts(k))return '';  // two controls stand under its words
  if(onRow(k))return settingField(k,side,true);
  return `<span class="setval">${esc(settingSays(k,settingNow(k,side,true)))}</span>`;
}
/* this device's own value over the one everyone has, in words; '' for none */
const overSays=k=>k.has_device&&k.has_project?`This device overrides everyone's (${settingSays(k,settingText(k.project))})`:'';
function settingRow(k,o={}){
  const id=settingId(k), open=!!S.setOpen[id], side=settingSide(k), busy=S.ob.filter(x=>x.set&&x.set.id===id&&!x.set.part);
  const place=side==='device'?'device':'everyone', off=o.home&&place!==o.home, e=esc(id);
  const where=k.source==='default'?'the default':k.source==='device'?'this device':'everyone';
  return `<div class="srow" data-k="set:${e}"><div class="row setline"><button class="fold setname" data-setopen="${e}" aria-expanded="${open}"><span class="grow"><b>${esc(k.name)}</b><span class="small">${esc(k.desc)}</span></span></button>${settingControl(k,side,o.readonly)}</div>
    ${hasParts(k)&&!o.readonly?partsField(k,side,true):''}
    ${busy.map(x=>`<div class="small">${esc(x.say)}: ${esc(obState(x))}</div>`).join('')}
    ${overSays(k)?`<div class="small">${esc(overSays(k))}</div>`:off?`<div class="small">${place==='device'?'Saved on this device only':'Saved for everyone'}</div>`:''}
    ${open?`<div class="small"><span class="setkey">[${esc(k.table)}] ${esc(k.key)}</span> · ${esc(settingSays(k,settingText(k.value)))}, from ${where}. Default: ${esc(settingSays(k,settingText(k.default)))}. ${k.applies==='now'?'A change applies now.':'A change applies when the run restarts.'}</div>
      ${o.readonly?`<div class="btns"><button class="btn" data-about="setting:${e}">Ask a chat to change it</button></div>`:`${onRow(k)||id==='run.slots'?'':settingField(k,side)}
      <div class="btns">${onRow(k)||id==='run.slots'?'':`<button class="btn pri" data-setsave="${side}" data-id="${e}">${side==='device'?'Save on this device':'Save for everyone'}</button>`}<button class="btn" data-setmore="${e}">More…</button></div>`}`:''}
    ${o.reset?`<div class="btns">${resetBtn(k)}</div>`:''}</div>`;
}
const resetBtn=k=>(k.has_device?`<button class="btn" data-setreset="device" data-id="${esc(settingId(k))}">Reset on this device</button>`:'')+(k.has_project?`<button class="btn" data-setreset="project" data-id="${esc(settingId(k))}">Reset for everyone</button>`:'');
/* the two rows that pick the models of a few kinds at once: [models.kinds] */
function kindsValue(k){
  const side=settingSide(k), f=setField(settingId(k),side);
  if(f in S.f){const r=settingValue(k,S.f[f]);if(r.v)return r.v}
  return k['has_'+side]?k[side]:{};
}
function kindsRow(g,k){
  const open=!!S.setOpen['kinds:'+g.id], now=kindsModel(g.kinds,{...k.default,...kindsValue(k)}), ms=[...new Set(['opus','sonnet','haiku',...(now?[now]:[])])];
  return `<div class="srow" data-k="setkinds:${g.id}"><div class="row setline"><button class="fold setname" data-setopen="kinds:${g.id}" aria-expanded="${open}"><span class="grow"><b>${g.name}</b><span class="small">${g.desc}</span></span></button>
    <select class="fld setpick" data-kinds="${g.id}" aria-label="${g.name}">${now?'':'<option value="" selected>Mixed</option>'}${ms.map(m=>`<option ${m===now?'selected':''}>${esc(m)}</option>`).join('')}</select></div>
    ${S.ob.filter(x=>x.set&&x.set.part===g.id).map(x=>`<div class="small">${esc(x.say)}: ${esc(obState(x))}</div>`).join('')}
    ${k.has_device?`<div class="small">${k.has_project?'This device overrides what everyone has':'Saved on this device only'}</div>`:''}
    ${open?`<div class="small"><span class="setkey">[models] kinds</span> · ${g.kinds.join(', ')}. A change applies when the run restarts.</div><div class="btns"><button class="btn" data-setmore="models.kinds">More…</button></div>`:''}</div>`;
}
function saveKinds(gid,model){
  const k=settingOf('models.kinds'), g=KINDS_ROWS.find(x=>x.id===gid);if(!k||!g||!model)return;
  const side=settingSide(k), v={...kindsValue(k)};for(const x of g.kinds)v[x]=model;
  S.f[setField('models.kinds',side)]=JSON.stringify(v);
  outbox(side==='device'?'setting_device':'setting_project',{table:'models',key:'kinds',value:v},{set:{id:'models.kinds',applies:k.applies,part:gid},say:`Save ${g.name} on ${model}`});
}
const setErrHTML=()=>S.setErr?`${S.setOld?oldRunHTML(S.setErr):`<div class="small v-bad">${esc(S.setErr)}</div>`}<div class="btns"><button class="btn" data-setload>Try again</button></div>`:'';
function setGroup(d,g,ks,o){
  const [id,head,where,home]=g, kinds=id==='models'&&(o||{}).kinds;
  if(!ks.length&&!kinds)return '';
  return `<div class="sec">${esc(head)}${where==='file'?'':` · ${PLACE[home]}`}<span class="ln"></span></div>${card((kinds||'')+ks.map(k=>settingRow(k,{...o,home:where==='file'?'':home,readonly:where==='file'})).join(''),'',`data-k="sett:${esc(id)}"`)}`;
}
function setFold(id,name,about,body){
  const open=!!S.setOpen['#'+id];
  return `${card(`<button class="fold setname" data-setopen="#${id}" aria-expanded="${open}"><span class="grow"><b>${name}</b><span class="small">${about}</span></span><span class="chev">${I.chev}</span></button>`,'',`data-k="setfold:${id}"`)}${open?body():''}`;
}
function settingsHTML(){
  const d=S.set&&S.set.tables?S.set:null, q=String(S.f.setq||'').trim().toLowerCase();
  if(!d)return `<div class="col">${setErrHTML()||emptyCard('Loading…')}${obCards(x=>x.ctl==='restart:')}</div>`;
  const all=settingsAll(d), rc=controlOf('restart'), waits=(d.waits||[]).length, changed=all.filter(settingChanged);
  const kinds=all.find(k=>settingId(k)==='models.kinds'), kr=kinds?KINDS_ROWS.map(g=>kindsRow(g,kinds)).join(''):'';
  const groups=(ks,o,w)=>d.groups.filter(g=>!w||g[2]===w).map(g=>setGroup(d,g,ks.filter(k=>k.group===g[0]),o)).join('');
  const shown=all.filter(k=>settingShows(k,all));
  let body;
  if(q||S.setChanged){
    const ks=(S.setChanged?changed:all).filter(k=>settingHit(k,q)), un=S.setChanged?d.unknown.filter(u=>!q||`${u.table} ${u.key} ${u.value}`.toLowerCase().includes(q)):[];
    const kh=S.setChanged||!kinds?'':KINDS_ROWS.filter(g=>settingHit({...kinds,name:g.name,desc:g.desc},q)).map(g=>kindsRow(g,kinds)).join('');
    body=(groups(ks,{reset:S.setChanged,kinds:kh})||emptyCard(q?'No setting matches.':'Nothing is changed from its default.'))
      +(un.length?`<div class="sec">Ignored or moved<span class="ln"></span></div>${card(un.map(u=>`<div class="srow" data-k="unk:${esc(u.side+u.table+u.key)}"><div class="row"><span class="grow setkey">${u.table?`[${esc(u.table)}] `:''}${u.key?`${esc(u.key)} = `:''}${esc(u.value)}</span><span class="tag warn">ignored or moved</span></div><div class="small">${esc(u.file)}: ${esc(u.why)}</div></div>`).join(''))}`:'');
  }else body=d.groups.filter(g=>g[2]==='page').map(g=>setGroup(d,g,shown.filter(k=>k.group===g[0]),{kinds:g[0]==='models'?kr:''})).join('')
    +`<div class="sec">More<span class="ln"></span></div>${setFold('advanced','Advanced','disk, memory, merge tuning',()=>groups(shown,{},'advanced'))}${setFold('file','Project file','test command, paths, rules: read only here',()=>groups(shown,{},'file'))}`;
  return `<div class="col"><div class="row"><input class="fld grow" type="search" data-f="setq" placeholder="Find a setting" aria-label="Find a setting">${changed.length+d.unknown.length||S.setChanged?`<button class="btn${S.setChanged?' pri':''}" data-setchanged aria-pressed="${!!S.setChanged}">Changed ${changed.length}</button>`:''}</div>
    ${setErrHTML()}${obCards(x=>x.ctl==='restart:')}${body}
    ${waits&&S.snap.up!==false&&rc?card(`<div class="row"><span class="grow">${waits===1?'1 change waits':`${waits} changes wait`} for a restart</span>${S.sure==='restart'?'':'<button class="btn acc" data-ctl="restart">Restart the run</button>'}</div>${S.sure==='restart'?ctlSure(rc):''}`,'','data-k="setwait"'):''}</div>`;
}
/* a row's More…: its words, its other home, and Reset for each place that sets it */
function settingSheet(){
  const k=settingOf(S.sheetArg||'');if(!k)return '<div class="small">That setting is gone.</div>';
  const id=settingId(k), side=settingSide(k), other=side==='device'?'project':'device';
  return `<h2>${esc(k.name)}</h2><div class="small">${esc(k.desc)}</div>
    <div class="sec">${other==='device'?'Only on this device':'For everyone'}<span class="ln"></span></div>
    <div class="small">${other==='device'?`Saved at once in ${esc(S.set.device)}, and wins over everyone's.`:`Saved at once in ${esc(S.set.project)}, and committed.${k.has_device?' This device keeps its own.':''}`}</div>
    ${settingField(k,other)}<div class="btns"><button class="btn pri" data-setsave="${other}" data-id="${esc(id)}">${other==='device'?'Save on this device':'Save for everyone'}</button></div>
    ${k.has_device||k.has_project?`<div class="sec">Reset<span class="ln"></span></div><div class="btns">${k.has_device?`<button class="btn" data-setreset="device" data-id="${esc(id)}">Reset on this device</button>`:''}${k.has_project?`<button class="btn" data-setreset="project" data-id="${esc(id)}">Reset for everyone</button>`:''}</div>`:''}
    <div class="btns"><button class="btn" data-closesheet>Close</button></div>`;
}
SHEETS.setting=settingSheet;
function saveSetting(id,side){
  const k=settingOf(id);if(!k)return;
  const f=setField(id,side), el=[...document.querySelectorAll('[data-f]')].find(e=>e.dataset.f===f);
  const text=f in S.f&&!(el&&el.type!=='checkbox'&&el.tagName!=='SELECT')?S.f[f]:el?(el.type==='checkbox'?String(el.checked):el.value):settingNow(k,side,true);
  const r=pickOptions(k,text)?{v:pickValue(k,text)}:settingValue(k,text);if(r.err)return toast(r.err,true);
  outbox(side==='device'?'setting_device':'setting_project',{table:k.table,key:k.key,value:r.v},{set:{id,applies:k.applies},say:`Save ${k.name}: ${settingSays(k,text)}`});
}
function resetSetting(id,side){
  const k=settingOf(id);if(!k)return;
  if(side==='device')outbox('setting_reset',{table:k.table,key:k.key},{set:{id,applies:k.applies},say:`Reset ${k.name}`});
  else outbox('setting_project',{table:k.table,key:k.key,unset:true},{set:{id,applies:k.applies},say:`Reset ${k.name} for everyone`});
}
/* the stepper: what it shows moves at once; one save goes once the taps stop */
let stepWait={};
function stepSetting(id,by){
  const k=settingOf(id);if(!k)return;
  const side=settingSide(k), f=setField(id,side);
  S.f[f]=String(Math.max(1,Number(settingNow(k,side,true))+by));render(true);
  clearTimeout(stepWait[id]);stepWait[id]=setTimeout(()=>{delete stepWait[id];saveSetting(id,side)},700);
}
