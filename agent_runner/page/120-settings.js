/* --- F97: Settings ------------------------------------------------------------------------------------------- */
async function loadSettings(){
  // B164: only a whole answer is kept: an error (a run without this route) leaves the settings already there
  try{const r=await fetch(tq('settings')), j=await r.json();S.setOld=false;
    if(r.ok&&j&&Array.isArray(j.tables)){S.set=j;S.setErr=j.out||'';draftTidy()}
    else{S.setOld=oldRun(j);S.setErr=plainOut(j,'The settings could not be read.')}}
  catch(e){S.setOld=false;S.setErr='Could not reach the run page to read the settings.'}
  render(true);
  loadLogins();
}
/* F166: the Settings view: the everyday settings with their control on the row, the rest behind Advanced and Project
   file. A setting has one home: 'device' is runner.local.toml, 'everyone' runner.toml. `side` is where its row saves. F202b: a change
   goes to the draft, and the bar (122-settings.js) saves it. */
const settingId=k=>`${k.table}.${k.key}`;
const settingOf=id=>{const x=S.set&&S.set.tables&&S.set.tables.find(t=>t.table===id.split('.')[0]);return x&&x.keys.map(k=>({...k,table:x.table})).find(k=>settingId(k)===id)};
const settingsAll=d=>d.tables.flatMap(t=>t.keys.map(k=>({...k,table:t.table}))).sort((a,b)=>a.order-b.order);
const PLACE={device:'this device',project:'everyone',everyone:'everyone'};
/* a change of `id` on `side` that is on its way to the run */
const setGoing=(id,side)=>S.ob.filter(x=>x.setbar).flatMap(x=>x.args.changes).filter(c=>`${c.table}.${c.key}`===id&&c.side===side).pop();
/* the words in a setting's field on `side`: the change not saved yet or on its way, else what is kept */
function settingNow(k,side,field){
  const f=setField(settingId(k),side);
  if(setUnset(f))return settingText(resetValue(k,side));
  if(f in S.f)return S.f[f];
  const c=setGoing(settingId(k),side);if(c)return settingText(c.unset?resetValue(k,side):c.value);
  return k['has_'+side]?settingText(k[side]):field?settingText(k.value):'';
}
/* F406c: the providers' logins as they are now; refused without the key, then Settings shows the commands */
async function loadLogins(){
  let j;try{const r=await fetch(tq('logins'));j=await r.json();j=r.ok&&j&&j.ok&&Array.isArray(j.providers)?j.providers:[]}catch(e){return false}
  const was=JSON.stringify(S.logins||[]);S.logins=j;
  if(JSON.stringify(j)!==was)render(true);
  return true;
}
const loginBtn=p=>p.name==='claude'?p.terminal?'<button class="btn" data-login>Log in again</button>':''
  :p.terminal&&p.state!=='none'?`<button class="btn" data-plogin="${esc(p.name)}" aria-label="${p.run==='running'?'Show the login of':p.state==='in'?'Log in again to':'Log in to'} ${esc(p.name)}">${p.run==='running'?'Show the login':p.state==='in'?'Log in again':'Log in'}</button>`:'';
const loginGoing=p=>p.run==='running'?'<div class="small"><span class="livedot"></span> Login under way</div>':p.run==='failed'?`<div class="small v-bad">The login failed: ${esc(p.said)}</div>`:'';
/* beside a setting that names a provider: its login, and the way to it */
function loginNote(at,key,names){
  return loginsNow(S.set,S.logins).filter(p=>names.includes(p.name)&&['in','out'].includes(p.state)).map(p=>`<div class="row setlogin" data-k="slog:${esc(at)}:${esc(p.name)}"><div class="grow"><div class="small">${p.state==='in'?`${esc(p.name)}: Logged in`:`${esc(p.name)} is not logged in. ${loginLater(key)}${p.terminal?'':` Log in with <span class="setkey">${esc(p.cmd)}</span>`}`}</div>${p.state==='in'&&p.run==='failed'?'':loginGoing(p)}</div>${p.state==='in'&&p.run!=='running'?'':loginBtn(p)}</div>`).join('');
}
function settingLogins(k,side){
  if(k.table!=='models')return '';
  const names=(S.set.providers||[]).map(p=>p.name), vals=[draftValue(k,{text:settingNow(k,side,true)}),...['device','project'].filter(s=>s!==side).map(s=>(S.draft||{})[setField(settingId(k),s)]).filter(Boolean).map(d=>draftValue(k,d))];
  return loginNote(settingId(k),k.key,vals.filter(r=>!r.err).flatMap(r=>modelProviders(k.key,k.key==='kinds'?{...k.default,...r.v}:r.v,names)));
}
const setUnset=f=>!!((S.draft||{})[f]||{}).unset;
/* F174: its two controls; on its row a change goes to the draft */
function partsField(k,side,onRow){
  const t=settingNow(k,side,true), v=partsNow(t), p=k.parts, d=`data-id="${esc(settingId(k))}" data-side="${side}"${onRow?' data-now':''}`, at=esc(`, ${k.name}, ${PLACE[side]}`);
  return `<div class="setparts"><label>${esc(p.every.label)} <select class="fld" data-setpart="every" ${d} aria-label="${esc(p.every.label)}${at}">${partOptions(k,t).map(([n,l])=>`<option value="${n}" ${n===v.every?'selected':''}>${esc(l)}</option>`).join('')}</select></label>
    <label>${esc(p.idle.label)} <input type="checkbox" role="switch" class="sw" data-setpart="idle" ${d} aria-label="${esc(p.idle.label)}${at}" ${v.idle?'checked':''}></label></div>`;
}
function savePart(el){
  const {id,side,setpart}=el.dataset, k=settingOf(id);if(!k)return;
  S.f[setField(id,side)]=partSet(settingNow(k,side,true),setpart,setpart==='idle'?el.checked:Number(el.value));
  if(el.dataset.now!==undefined){draftSet(id,side,{text:S.f[setField(id,side)]});render(true)}
}
/* F405: the program a session runs: a pick of those found here; Other path… brings a field, kept in S.f (so a
   refused path stays) until it is what is saved */
const otherField=(id,side)=>`setother:${side}:${id}`;
function agentOther(k,side){
  const f=otherField(settingId(k),side);
  if(f in S.f&&k['has_'+side]&&S.f[f].trim()===settingText(k[side]))delete S.f[f];
  return f in S.f;
}
function agentField(k,side,onRow){
  const id=settingId(k), now=settingNow(k,side,true), other=agentOther(k,side), p=agentPick(k,now), d=`data-id="${esc(id)}"`;
  return `<select class="fld" data-setagent="${side}" ${d}${onRow?' data-now':''} aria-label="${esc(k.name)}, ${PLACE[side]}">${agentOptions(k,now).map(([v,l])=>`<option value="${esc(v)}" ${v===(other?AGENT_OTHER:now)?'selected':''}>${esc(l)}</option>`).join('')}</select>
    ${other?`<input class="fld" data-f="${esc(otherField(id,side))}" value="${esc(S.f[otherField(id,side)])}" aria-label="Path of the program, ${PLACE[side]}" placeholder="Path of the program" autocomplete="off" autocapitalize="off" spellcheck="false"${onRow?' data-now':''}>`
      :agentSays(p)?`<div class="small setpath${p.bad?' v-bad':''}">${esc(agentSays(p))}</div>`:''}`;
}
function pickAgent(el){
  const {id,setagent:side}=el.dataset, k=settingOf(id), f=otherField(id,side);if(!k)return;
  if(el.value===AGENT_OTHER){S.f[f]='';delete S.f[setField(id,side)];if(el.dataset.now!==undefined)draftDrop(setField(id,side));render(true);
    const at=[...document.querySelectorAll('[data-f]')].find(x=>x.dataset.f===f);if(at)kbFocus(at);return}
  delete S.f[f];S.f[setField(id,side)]=el.value;
  if(el.dataset.now!==undefined)draftSet(id,side,{text:el.value});
  render(true);
}
/* the providers stand beside the program, and their models are picked elsewhere */
function providersHTML(d){
  const ps=d&&d.providers||[];if(!ps.length)return '';
  return `<div class="sec">Providers<span class="ln"></span></div><div class="small">Models of other providers run in the harness loop. A provider is chosen per role in [models], not here.</div>
    ${loginsNow(d,S.logins).map(p=>`<div class="row setlogin" data-k="prov:${esc(p.name)}"><div class="grow"><div class="small setpath"><b>${esc(p.name)}</b> · ${p.state==='unchecked'?esc(p.says):esc(LOGIN_SAYS[p.state]||p.state)}${p.state==='out'?p.terminal?'':`: <span class="setkey">${esc(p.cmd)}</span>`:p.state==='in'?`: ${esc(p.says)}`:''}</div>${loginGoing(p)}</div>${loginBtn(p)}</div>`).join('')}
    <div class="btns"><button class="btn" data-setmodels>Show the model settings</button></div>`;
}
function setModels(){
  const was=document.querySelector('[data-f="setq"]');S.f.setq='[models]';S.setChanged=false;if(was)was.value='[models]';
  render(true);
  const el=document.querySelector('[data-f="setq"]');if(el)el.scrollIntoView({block:'nearest'});
}
function settingField(k,side,onRow){
  if(hasParts(k))return partsField(k,side,onRow);
  if(hasPicks(k))return agentField(k,side,onRow);
  const id=settingId(k), now=settingNow(k,side,true), d=`data-f="${esc(setField(id,side))}"${onRow?' data-now':''} aria-label="${esc(k.name)}, ${PLACE[side]}"`;
  if(k.type==='switch')return `<input type="checkbox" role="switch" class="sw" ${d} data-sw ${now==='true'?'checked':''}>`;
  const opts=pickOptions(k,now);
  if(opts)return `<select class="fld setpick" ${d}>${opts.map(([v,l])=>`<option value="${esc(v)}" ${v===now?'selected':''}>${esc(l)}</option>`).join('')}</select>`;
  if(k.type==='list'||k.type==='table'||now.length>40)return `<textarea class="fld" rows="3" ${d} placeholder="${k.type==='list'?'one per line':k.type==='table'?'{ key = value }':'not set'}">${esc(now)}</textarea>`;
  return `<input class="fld" ${k.type==='number'?'inputmode="decimal"':''} ${d} value="${esc(now)}" placeholder="not set" autocomplete="off" autocapitalize="off" spellcheck="false">`;
}
const onRow=k=>k.type==='switch'||hasParts(k)||hasPicks(k)||!!pickOptions(k,'');
/* what stands at the right of a folded row: its control, or its value when it is typed in the open row */
function settingControl(k,side,readonly){
  if(readonly)return `<span class="setval">${esc(settingSays(k,settingText(k.value)))}</span>`;
  if(settingId(k)==='run.slots'){const n=settingNow(k,side,true), id=esc(settingId(k));
    return `<span class="step" role="group" aria-label="${esc(k.name)}"><button class="btn" data-setstep="-1" data-id="${id}" aria-label="Fewer" ${Number(n)<2?'disabled':''}>−</button><b>${esc(n)}</b><button class="btn" data-setstep="1" data-id="${id}" aria-label="More">+</button></span>`}
  if(hasParts(k)||hasPicks(k))return '';  // its controls stand under its words
  if(onRow(k))return settingField(k,side,true);
  return `<span class="setval">${esc(settingSays(k,settingNow(k,side,true)))}</span>`;
}
/* this device's own value over the one everyone has, in words; '' for none */
const overSays=k=>k.has_device&&k.has_project?`This device overrides everyone's (${settingSays(k,settingText(k.project))})`:'';
function settingRow(k,o={}){
  const id=settingId(k), open=!!S.setOpen[id], side=settingSide(k), busy=settingBusy(id);
  const place=side==='device'?'device':'everyone', off=o.home&&place!==o.home, e=esc(id);
  const where=k.source==='default'?'the default':k.source==='device'?'this device':'everyone';
  return `<div class="srow" data-k="set:${e}"><div class="row setline"><button class="fold setname" data-setopen="${e}" aria-expanded="${open}"><span class="grow"><b>${esc(k.name)}</b><span class="small">${esc(k.desc)}</span></span></button>${settingControl(k,side,o.readonly)}</div>
    ${hasParts(k)&&!o.readonly?partsField(k,side,true):hasPicks(k)&&!o.readonly?agentField(k,side,true):''}
    ${busy}${notSaved(k,side)}${o.readonly?'':settingLogins(k,side)}
    ${overSays(k)?`<div class="small">${esc(overSays(k))}</div>`:off?`<div class="small">${place==='device'?'Saved on this device only':'Saved for everyone'}</div>`:''}
    ${open?foldIn('set:'+id,`<div class="small"><span class="setkey">[${esc(k.table)}] ${esc(k.key)}</span> · ${esc(settingSays(k,settingText(k.value)))}, from ${where}. Default: ${esc(settingSays(k,settingText(k.default)))}. ${k.applies==='now'?'A change applies now.':'A change applies when the run restarts.'}</div>
      ${o.readonly?`<div class="btns"><button class="btn" data-about="setting:${e}">Ask a chat to change it</button></div>`:`${onRow(k)||id==='run.slots'?'':settingField(k,side,true)}
      <div class="btns"><button class="btn" data-setmore="${e}">More…</button></div>`}`):''}
    ${hasPicks(k)?providersHTML(S.set):''}
    ${o.reset?`<div class="btns" data-k="reset:${e}">${resetBtn(k)}</div>`:''}</div>`;
}
const settingBusy=id=>S.ob.filter(x=>x.setbar&&x.args.changes.some(c=>`${c.table}.${c.key}`===id)).map(x=>`<div class="small">${x.setbar==='undo'?'Undo':'Save'}: ${esc(obState(x))}</div>`).join('');
/* F202b: the row's changes that are not saved yet, with where they go when that is not where the row saves */
function notSaved(k,side){
  return ['device','project'].map(s=>{
    const d=(S.draft||{})[setField(settingId(k),s)], where=s==='device'?'on this device':'for everyone';if(!d)return '';
    return `<div class="small setnew${d.err?' v-bad':''}">Not saved yet${d.unset?`: reset ${where}`:s===side?'':`: ${esc(settingSays(k,d.text))} ${where}`}${d.err?`. ${esc(d.err)}`:''}</div>`}).join('');
}
/* the settings with the changes of the draft and those on their way, to say which rows show */
const draftedAll=all=>all.map(k=>{const s=settingSide(k), d=(S.draft||{})[setField(settingId(k),s)], c=!d&&setGoing(settingId(k),s), r=d?draftValue(k,d):c&&{v:c.unset?resetValue(k,s):c.value};return r&&!r.err?{...k,value:r.v}:k});
const resetBtn=k=>(k.has_device?`<button class="btn" data-setreset="device" data-id="${esc(settingId(k))}">Reset on this device</button>`:'')+(k.has_project?`<button class="btn" data-setreset="project" data-id="${esc(settingId(k))}">Reset for everyone</button>`:'');
/* the two rows that pick the models of a few kinds at once: [models.kinds] */
function kindsValue(k){
  const side=settingSide(k), f=setField(settingId(k),side);
  if(setUnset(f))return resetValue(k,side);
  if(f in S.f){const r=settingValue(k,S.f[f]);if(r.v)return r.v}
  const c=setGoing('models.kinds',side);if(c)return c.unset?resetValue(k,side):c.value;
  return k['has_'+side]?k[side]:{};
}
function kindsRow(g,k){
  const open=!!S.setOpen['kinds:'+g.id], now=kindsModel(g.kinds,{...k.default,...kindsValue(k)}), ms=[...new Set(['opus','sonnet','haiku',...(now?[now]:[])])];
  return `<div class="srow" data-k="setkinds:${g.id}"><div class="row setline"><button class="fold setname" data-setopen="kinds:${g.id}" aria-expanded="${open}"><span class="grow"><b>${g.name}</b><span class="small">${g.desc}</span></span></button>
    <select class="fld setpick" data-kinds="${g.id}" aria-label="${g.name}">${now?'':'<option value="" selected>Mixed</option>'}${ms.map(m=>`<option ${m===now?'selected':''}>${esc(m)}</option>`).join('')}</select></div>
    ${settingBusy('models.kinds')}${kindsNote(g,k)}${loginNote('kinds:'+g.id,'kinds',g.kinds.flatMap(x=>modelProviders('kinds',[{...k.default,...kindsValue(k)}[x]],(S.set.providers||[]).map(p=>p.name))))}
    ${k.has_device?`<div class="small">${k.has_project?'This device overrides what everyone has':'Saved on this device only'}</div>`:''}
    ${open?foldIn('kinds:'+g.id,`<div class="small"><span class="setkey">[models] kinds</span> · ${g.kinds.join(', ')}. A change applies now.</div><div class="btns"><button class="btn" data-setmore="models.kinds">More…</button></div>`):''}</div>`;
}
function kindsNote(g,k){
  const ds=['device','project'].map(s=>(S.draft||{})[setField('models.kinds',s)]).filter(Boolean);
  return ds.filter(d=>d.unset||d.err||d.set||kindsDrafted(k,d).some(x=>x.id===g.id)).map(d=>`<div class="small setnew${d.err?' v-bad':''}">Not saved yet${d.side===settingSide(k)&&!d.unset?'':`: ${d.unset?'reset ':''}${d.side==='device'?'on this device':'for everyone'}`}${d.err?`. ${esc(d.err)}`:''}</div>`).join('');
}
function saveKinds(gid,model){
  const k=settingOf('models.kinds'), g=KINDS_ROWS.find(x=>x.id===gid);if(!k||!g||!model)return;
  const side=settingSide(k), v={...kindsValue(k)};for(const x of g.kinds)v[x]=model;
  S.f[setField('models.kinds',side)]=JSON.stringify(v);
  draftSet('models.kinds',side,{text:S.f[setField('models.kinds',side)]});render(true);
}
const setErrHTML=()=>S.setErr?`${S.setOld?oldRunHTML(S.setErr):`<div class="small v-bad">${esc(S.setErr)}</div>`}<div class="btns"><button class="btn" data-setload>Try again</button></div>`:'';
function setGroup(d,g,ks,o){
  const [id,head,where,home]=g, kinds=id==='models'&&(o||{}).kinds;
  if(!ks.length&&!kinds)return '';
  return `<div class="sec">${esc(head)}${where==='file'?'':` · ${PLACE[home]}`}<span class="ln"></span></div>${card((kinds||'')+ks.map(k=>settingRow(k,{...o,home:where==='file'?'':home,readonly:where==='file'})).join(''),'',`data-k="sett:${esc(id)}"`)}`;
}
function setFold(id,name,about,body){
  const open=!!S.setOpen['#'+id];
  return `${card(`<button class="fold setname" data-setopen="#${id}" aria-expanded="${open}"><span class="grow"><b>${name}</b><span class="small">${about}</span></span><span class="chev">${I.chev}</span></button>`,'',`data-k="setfold:${id}"`)}${open?foldIn('#'+id,body()):''}`;
}
function settingsHTML(){
  const d=S.set&&S.set.tables?S.set:null, q=String(S.f.setq||'').trim().toLowerCase();
  if(!d)return `<div class="col">${setErrHTML()||emptyCard('Loading…')}${obCards(x=>x.ctl==='restart:')}</div>`;
  const all=settingsListed(settingsAll(d)), rows=kindsRows(all), rc=controlOf('restart'), waits=(d.waits||[]).length, changed=all.filter(settingChanged);
  const kinds=all.find(k=>settingId(k)==='models.kinds'), kr=kinds?rows.map(g=>kindsRow(g,kinds)).join(''):'';
  const groups=(ks,o,w)=>d.groups.filter(g=>!w||g[2]===w).map(g=>setGroup(d,g,ks.filter(k=>k.group===g[0]),o)).join('');
  const seen=draftedAll(all), shown=all.filter(k=>settingShows(k,seen));
  let body;
  if(q||S.setChanged){
    const ks=(S.setChanged?changed:all).filter(k=>settingHit(k,q)), un=S.setChanged?d.unknown.filter(u=>!q||`${u.table} ${u.key} ${u.value}`.toLowerCase().includes(q)):[];
    const kh=S.setChanged||!kinds?'':rows.filter(g=>settingHit({...kinds,name:g.name,desc:g.desc},q)).map(g=>kindsRow(g,kinds)).join('');
    body=(groups(ks,{reset:S.setChanged,kinds:kh})||emptyCard(q?'No setting matches.':'Nothing is changed from its default.'))
      +(un.length?`<div class="sec">Ignored or moved<span class="ln"></span></div>${card(un.map(u=>`<div class="srow" data-k="unk:${esc(u.side+u.table+u.key)}"><div class="row"><span class="grow setkey">${u.table?`[${esc(u.table)}] `:''}${u.key?`${esc(u.key)} = `:''}${esc(u.value)}</span><span class="tag warn">ignored or moved</span></div><div class="small">${esc(u.file)}: ${esc(u.why)}</div></div>`).join(''))}`:'');
  }else body=d.groups.filter(g=>g[2]==='page').map(g=>setGroup(d,g,shown.filter(k=>k.group===g[0]),{kinds:g[0]==='models'?kr:''})).join('')
    +`<div class="sec">More<span class="ln"></span></div>${setFold('advanced','Advanced','disk, memory, merge tuning',()=>groups(shown,{},'advanced'))}${setFold('file','Project file','test command, paths, rules: read only here',()=>groups(shown,{},'file'))}`;
  return `<div class="col"><div class="row"><span class="setq grow"><input class="fld" type="search" data-f="setq" placeholder="Find a setting" aria-label="Find a setting"><button type="button" class="x" data-setqclear aria-label="Clear search"${S.f.setq?'':' hidden'}>${I.x}</button></span>${changed.length+d.unknown.length||S.setChanged?`<button class="btn${S.setChanged?' pri':''}" data-setchanged aria-pressed="${!!S.setChanged}">Changed ${changed.length}</button>`:''}</div>
    ${setErrHTML()}${obCards(x=>x.ctl==='restart:')}${body}
    ${waits&&S.snap.up!==false&&rc?card(`<div class="row"><span class="grow">${waits===1?'1 change waits':`${waits} changes wait`} for a restart</span>${S.sure==='restart'?'':'<button class="btn acc" data-ctl="restart">Restart the run</button>'}</div>${S.sure==='restart'?ctlSure(rc):''}`,'','data-k="setwait"'):''}</div>`;
}
/* F204a: the search field in use stays the same element while what is under it changes (as B222a); F202b: so does a field typed in */
function settingsDraw(el,h){
  if(el._h!==h&&el._gone)for(const g of el._gone)g.remove();  // leaving() puts them back
  const a=document.activeElement, f=a&&a.dataset&&a.dataset.f, text=f&&/^set(other)?:/.test(f)&&(a.tagName==='TEXTAREA'||a.tagName==='INPUT'&&a.type!=='checkbox');
  return fieldHTML(el,h,text?f:'setq');
}
/* the x in a search (Settings', and F212 the Plan view's): the full list, and focus in the field */
function setqClear(f='setq'){
  const at=()=>document.querySelector(`[data-f="${f}"]`), was=at();S.f[f]='';if(was)was.value='';
  render(true);
  const el=at();if(el&&document.activeElement!==el)kbFocus(el);
}
/* a row's More…: its words, its other home, and Reset for each place that sets it */
function settingSheet(){
  const k=settingOf(S.sheetArg||'');if(!k)return '<div class="small">That setting is gone.</div>';
  const id=settingId(k), side=settingSide(k), other=side==='device'?'project':'device';
  return `<h2>${esc(k.name)}</h2><div class="small">${esc(k.desc)}</div>
    <div class="sec">${other==='device'?'Only on this device':'For everyone'}<span class="ln"></span></div>
    <div class="small">${other==='device'?`Goes in ${esc(S.set.device)} when you save, and wins over everyone's.`:`Goes in ${esc(S.set.project)} when you save, and is committed.${k.has_device?' This device keeps its own.':''}`}</div>
    ${settingField(k,other)}<div class="btns"><button class="btn pri" data-setsave="${other}" data-id="${esc(id)}">${other==='device'?'Change on this device':'Change for everyone'}</button></div>
    ${k.has_device||k.has_project?`<div class="sec">Reset<span class="ln"></span></div><div class="btns">${k.has_device?`<button class="btn" data-setreset="device" data-id="${esc(id)}">Reset on this device</button>`:''}${k.has_project?`<button class="btn" data-setreset="project" data-id="${esc(id)}">Reset for everyone</button>`:''}</div>`:''}
    <div class="btns"><button class="btn" data-closesheet>Close</button></div>`;
}
SHEETS.setting=settingSheet;
/* More…'s Change button: its field goes to the draft */
function saveSetting(id,side){
  const k=settingOf(id);if(!k)return;
  const f=setField(id,side), el=[...document.querySelectorAll('[data-f]')].find(e=>e.dataset.f===f);
  const text=hasPicks(k)&&agentOther(k,side)?S.f[otherField(id,side)].trim():f in S.f&&!(el&&el.type!=='checkbox'&&el.tagName!=='SELECT')?S.f[f]:el?(el.type==='checkbox'?String(el.checked):el.value):settingNow(k,side,true);
  const r=pickOptions(k,text)?{v:pickValue(k,text)}:settingValue(k,text);if(r.err)return toast(r.err,true);
  S.f[f]=text;draftSet(id,side,{text,set:true});
  if(S.sheet==='setting')closeSheet();
  render(true);
}
function resetSetting(id,side){
  const k=settingOf(id);if(!k)return;
  delete S.f[otherField(id,side)];
  draftSet(id,side,{unset:true});
  if(S.sheet==='setting')closeSheet();
  render(true);
}
/* the stepper: what it shows moves at once, in the draft */
function stepSetting(id,by){
  const k=settingOf(id);if(!k)return;
  const side=settingSide(k), f=setField(id,side);
  S.f[f]=String(Math.max(1,Number(settingNow(k,side,true))+by));
  draftSet(id,side,{text:S.f[f]});render(true);
}
