/* --- F169: Tools ---------------------------------------------------------------------------------------------- */
async function loadTools(){
  try{const r=await fetch(tq('tools')), j=await r.json();S.toolOld=false;
    if(r.ok&&j&&Array.isArray(j.tools)){S.tools=j;S.toolErr=''}
    else{S.toolOld=oldRun(j);S.toolErr=plainOut(j,'The tools could not be read.')}}
  catch(e){S.toolErr='Could not reach the run page to read the tools.'}
  if(S.view==='tools')render();
  toolSpot();
}
setInterval(()=>{if(S.view==='tools'&&!S.thread&&!document.hidden&&!HOME_PAGE)loadTools()},10000);
/* a change to a device: straight to the run, never through the outbox, which a browser keeps. A secret's field is
   emptied whatever the answer; nothing here stores one. */
async function toolPost(body,name){
  if(S.toolBusy)return null;
  S.toolBusy=`${body.op}:${name||''}:${body.what||''}`;S.toolSaid={};render(true);
  let j;
  try{const r=await fetch(tq('tools'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});j=await r.json()}
  catch(e){j={ok:false,out:'Could not reach the run page. Nothing is known to be saved; try again.'}}
  S.toolBusy='';S.toolSaid={[name||'']:{ok:!!j.ok,out:plainOut(j,'That failed.'),https:j.https||'',hostkey:j.hostkey||null}};
  await loadTools();render(true);return j;
}
const toolOf=n=>S.tools&&S.tools.tools.find(t=>t.name===n&&t.source==='device');
const toolField=k=>`dev:${k}`, toolVal=k=>S.f[toolField(k)]||'';
const SECRET_FIELDS=['key','passphrase','password'].map(k=>'dev:'+k);
/* what is typed in a device's sheet goes when it closes, a secret first of all; emptied fields are drawn again (B222b) */
function toolForget(){for(const k of Object.keys(S.f))if(k.startsWith('dev:'))delete S.f[k];for(const el of $('sheet').querySelectorAll('[data-f^="dev:"]')){if(el.type!=='checkbox')el.value='';$('sheet')._h=''}S.secretOpen=''}
const SECRET_NAME={key:'Private key',passphrase:'Key passphrase',password:'Password'};
const toolSaid=n=>{const s=(S.toolSaid||{})[n];return s?`<div class="small ${s.ok?'':'v-bad'}" role="status">${esc(s.out)}${s.https?` <a href="${esc(s.https)}">${esc(s.https.split('?')[0])}</a>`:''}</div>`:''};
const toolBusy=(op,n,what)=>S.toolBusy===`${op}:${n||''}:${what||''}`?' busy':'';
const toolWords=t=>(t.words||'not checked yet')+(t.at?` · checked ${agoWords(t.at*1000,' ago')}`:'');
const toolWhere=t=>t.source==='runner.toml'?`[run.tools.${t.name}] in runner.toml, edited there`:t.kind==='other'?t.reach:t.alias?`SSH, ${t.alias} in ~/.ssh/config`:`SSH, ${t.user?t.user+'@':''}${t.host}${t.port===22?'':':'+t.port}`;
function toolCard(t){
  const dev=t.source==='device', cls={free:'ok',busy:'warn',missing:'bad',unknown:'warn'}[t.state]||'', n=esc(t.name);
  return card(`<div class="row setline"><span class="grow"><b>${esc(t.label)}</b></span>${dev?`<label class="row small">Used here <input type="checkbox" role="switch" class="sw" data-tooluse="${n}" aria-label="This project uses ${n}" ${t.used?'checked':''} ${S.tools.secure?'':'disabled'}></label>`:''}</div>
    <div data-k="toolstate:${n}" data-v="${esc(t.state)}"><span class="${cls?'v-'+cls:'small'}">${esc(toolWords(t))}</span></div>
    ${t.description?`<div class="tooltext">${esc(t.description)}</div>`:''}
    <div class="small tooltext">${esc(toolWhere(t))}${dev&&t.exclusive?' · one task at a time':''}</div>
    ${dev?`${t.kind==='ssh'?toolHostKey(t):''}${toolPage(t)}${pressHTML(t)}${toolSaid(t.name)}
    ${S.sure==='tool:'+t.name?`<div class="small">Remove ${n} for every project, its keys and password too?</div><div class="btns"><button class="btn bad" data-tool="remove" data-name="${n}">Yes, remove</button><button class="btn" data-unsure>No</button></div>`
    :`<div class="btns"><button class="btn${toolBusy('test',t.name)}" data-tool="test" data-name="${n}" ${S.tools.secure?'':'disabled'}>Test connection</button><button class="btn" data-tool="edit" data-name="${n}">Edit…</button>${t.kind==='ssh'&&!t.alias?`<button class="btn" data-tool="secrets" data-name="${n}">Keys and password…</button>`:''}<button class="btn" data-tool="ask" data-name="${n}" ${S.tools.secure?'':'disabled'}>Remove</button></div>`}`:toolPage(t)+pressHTML(t)+(t.page?toolSaid(toolKey(t)):'')}${pressSaid(t)}`,'',`data-k="tool:${esc(t.source)}:${n}"`);
}
/* F428b: a device's name, or a runner.toml tool's with its source: the two may have one name, and a device's has no ':' */
const toolKey=t=>t.source==='device'?t.name:`${t.source}:${t.name}`;
/* a page of ':PORT' is on this machine: at the host this page was opened on (a file copy has none) */
const pageAt=page=>/^:\d+$/.test(page||'')?(location.hostname?`http://${location.hostname}${page}`:''):page||'';
/* F408, F428b: the web page of a device or a runner.toml tool: its state in words, what a failed start command printed last, and its buttons */
const useLink=(page,label,cls='')=>/^https?:\/\//i.test(pageAt(page))?`<a class="btn${cls}" href="${esc(pageAt(page))}" target="_blank" rel="noopener noreferrer">${esc(label)} ${I.ext}</a>`:'';
function toolPage(t){
  if(!t.page)return '';
  const s=t.run&&t.run.state, k=toolKey(t), n=esc(t.name), off=S.tools.secure?'':'disabled', lines=s==='failed'?t.run.lines||[]:[];
  const b=(op,label,cls)=>`<button class="btn${cls}${toolBusy(op,k)}" data-tool="${op}" data-name="${n}" data-source="${esc(t.source)}" ${off}>${label}</button>`;
  return `<div class="small tooltext" data-k="pagestate:${esc(k)}" data-v="${esc(s||'')}">Web page ${esc(pageAt(t.page)||t.page)}${s?` · <span class="${{running:'v-ok',failed:'v-bad'}[s]||''}">${esc(s)}</span>`:''}</div>
    ${lines.length?`<pre class="tasktext">${esc(lines.join('\n'))}</pre>`:''}
    <div class="btns">${s&&s!=='running'?b('start','Start',' pri'):useLink(t.page,'Use',' pri')+(s?b('stop','Stop',''):'')}</div>`;
}
/* F428d: a tool's own buttons (GLOSSARY: tool button). S.press[toolKey]: {busy: the label that is sent, ask: the question
   in the buttons' place, said: what the last press answered}; its own, as one tool's press may take a while */
const pressOf=t=>(S.press||{})[toolKey(t)]||{};
function pressHTML(t){
  const bs=t.buttons||[], p=pressOf(t), n=esc(t.name), at=`data-name="${n}" data-source="${esc(t.source)}"`, k=esc(toolKey(t)), off=S.tools.secure?'':'disabled';
  if(!bs.length)return '';
  if(p.ask&&bs.some(b=>b.label===p.ask.label))return `<div class="sure toolbtns" data-k="pressask:${k}" role="group"><div class="small tooltext" role="status">${esc(p.ask.q)}</div><div class="btns"><button class="btn bad" data-tool="pressyes" ${at} ${off}>${p.ask.busy?'Use it anyway':`Yes, ${esc(p.ask.label)}`}</button><button class="btn" data-tool="pressno" ${at}>No</button></div></div>`;
  return `<div class="btns toolbtns" data-k="press:${k}">${bs.map(b=>`<button class="btn${p.busy===b.label?' busy':''}" data-tool="press" ${at} data-label="${esc(b.label)}" ${off||(p.busy&&p.busy!==b.label?'disabled':'')}>${esc(b.label)}</button>`).join('')}</div>`;
}
function pressSaid(t){
  const s=pressOf(t).said;
  return s?`<div class="pressed" data-k="pressed:${esc(toolKey(t))}" role="status"><div class="small tooltext${s.ok?'':' v-bad'}">${esc(s.out)}${s.https?` <a href="${esc(s.https)}">${esc(s.https.split('?')[0])}</a>`:''}</div>${s.lines.length?`<pre class="tasktext">${esc(s.lines.join('\n'))}</pre>`:''}</div>`:'';
}
/* the web pages of the devices and tools a Needs you item's task needs: Use, or the way to the card while it is not running */
function needDevices(n){
  return (n.devices||[]).map(d=>d.state&&d.state!=='running'?`<button class="btn" data-tool="show" data-name="${esc(d.name)}"${d.source?` data-source="${esc(d.source)}"`:''}>Open ${esc(d.label||d.name)} in Tools</button>`:useLink(d.page,`Use ${d.label||d.name}`)).join('');
}
/* S.toolGo: the device or tool (its `toolKey`) whose card a press asked for, brought on screen once it is drawn (a press or a motion may hold a draw) */
function toolSpot(tries=20){
  if(!S.toolGo)return;
  if(S.view!=='tools'||S.thread){S.toolGo='';return}
  const body=$('body'), el=S.tools&&[...body.querySelectorAll('[data-k]')].find(x=>x.dataset.k===(S.toolGo.includes(':')?'tool:':'tool:device:')+S.toolGo);
  if(el){body.scrollTop+=el.getBoundingClientRect().top-body.getBoundingClientRect().top-12;S.toolGo=''}
  else if(tries)setTimeout(()=>toolSpot(tries-1),100);
  else S.toolGo='';
}
/* the fingerprint that waits for the person, else the accepted one */
function toolHostKey(t){
  const h=((S.toolSaid||{})[t.name]||{}).hostkey, n=esc(t.name);
  if(h)return `<div class="small tooltext">${h.was?`Accepted before: <span class="setkey">${esc(h.was)}</span><br>It shows now: `:'It shows: '}<span class="setkey">${esc(h.fp)}</span> (${esc(h.type)})</div><div class="btns"><button class="btn pri${toolBusy('accept',t.name)}" data-tool="accept" data-name="${n}" data-fp="${esc(h.fp)}">${h.was?'Accept the new fingerprint':'Accept this fingerprint'}</button></div>`;
  return t.hostkey?`<div class="small tooltext">Host key <span class="setkey">${esc(t.hostkey.fp)}</span>, accepted ${esc(t.hostkey.changed)}</div>`:'<div class="small">Its host key is not accepted yet: test the connection.</div>';
}
/* F427d: each check a blocked task waits on (`--until`), from the snapshot: its last result and when, the tasks
   that wait, and Check now; nothing when none waits. The run adds and drops them, never this page. */
const UNTIL_STATE={'passed':'v-ok','cannot run':'v-bad'};
function untilsHTML(rows){
  if(!rows||!rows.length)return '';
  return `<div class="sec">Tasks wait on<span class="ln"></span></div>${rows.map(r=>{
    const busy=S.untilBusy===r.check, ago=r.at?agoWords(r.at,' ago'):'';
    return card(`<b>${esc(r.label)}</b>
    <div class="small tooltext" data-k="untilstate:${esc(r.check)}">${r.state?`<span class="${UNTIL_STATE[r.state]||''}">${esc(r.state[0].toUpperCase()+r.state.slice(1))}</span>${ago?` · ${esc(ago)}`:''}${r.said?`: ${esc(r.said)}`:''}`:'Not checked yet'}</div>
    <ul class="untiltasks small">${r.tasks.map(t=>`<li><b>${esc(t.id)}</b> ${esc(t.title)}</li>`).join('')}</ul>
    <div class="btns"><button class="btn${busy?' busy':''}" data-tool="untilcheck" data-check="${esc(r.check)}" ${S.untilBusy?'disabled':''}>Check now</button></div>`,'',`data-k="until:${esc(r.check)}"`)}).join('')}`;
}
async function untilCheck(check){
  if(S.untilBusy)return;
  S.untilBusy=check;render(true);
  const j=await act('until_check',{check});
  S.untilBusy='';if(j&&j.ok)toast(j.out);render(true);
}
function toolsHTML(){
  const d=S.tools, err=S.toolErr?(S.toolOld?oldRunHTML(S.toolErr):`<div class="small v-bad">${esc(S.toolErr)}</div>`)+'<div class="btns"><button class="btn" data-tool="load">Try again</button></div>':'';
  if(!d)return `<div class="col">${err||emptyCard('Loading…')}</div>`;
  const toml=d.tools.filter(t=>t.source!=='device'), devs=d.tools.filter(t=>t.source==='device');
  return `<div class="col">${d.secure?'':card(`<b>Read only here</b><div class="small">Devices and secrets are saved only over https or on the machine itself.${d.https?'':' There is no https link yet: Tailscale Serve gives one.'}</div>${d.https?`<div class="btns"><a class="btn pri" href="${esc(d.https)}">Open the https link</a></div>`:''}`)}
    ${err}${untilsHTML((S.snap||{}).untils)}<div class="sec">Devices<span class="ln"></span></div>${devs.length?devs.map(toolCard).join(''):emptyCard('No device yet. Add a machine or test rig for agents to reach.')}${loginsHTML()}
    ${toml.length?`<div class="sec">From runner.toml<span class="ln"></span></div>${toml.map(toolCard).join('')}`:''}
    <div class="small">Devices belong to this machine and its projects share them. Keys and passwords stay out of every chat, but agents run as the same user here, so this is no wall against an agent that goes looking.</div></div>`;
}
/* B222b: no typed word is in a device sheet's markup: keepFields() puts it back */
const devText=(k,label,o={})=>`<label class="small">${label}${o.area?`<textarea class="fld" rows="${o.area}" data-f="${toolField(k)}" ${o.hint?`placeholder="${o.hint}"`:''}></textarea>`:`<input class="fld" data-f="${toolField(k)}" ${o.num?'inputmode="numeric"':''} ${o.hint?`placeholder="${o.hint}"`:''} autocomplete="off" autocapitalize="off" spellcheck="false">`}</label>`;
const devPick=(k,label,opts)=>`<label class="small">${label}<select class="fld" data-f="${toolField(k)}">${opts.map(([v,l])=>`<option value="${esc(v)}" ${v===toolVal(k)?'selected':''}>${esc(l)}</option>`).join('')}</select></label>`;
/* F428d: the buttons in a device's sheet: S.devBtns has a key for each, whose fields are dev:b<key>-label, -cmd, -confirm */
const BTN_FIELDS=['label','cmd','confirm'], btnField=(i,k)=>`b${i}-${k}`;
const devButtons=()=>`<div class="sec">Buttons<span class="ln"></span></div><div class="small">Each runs its command once on this machine, 30 s at most.</div>
    ${(S.devBtns||[]).map((i,at)=>`<div class="devbtn" data-k="devbtn:${i}" role="group" aria-label="Button ${at+1}"><div class="row setline"><b class="grow">Button ${at+1}</b><button class="btn" data-tool="btndel" data-i="${i}" aria-label="Remove button ${at+1}">Remove</button></div>${devText(btnField(i,'label'),'Label',{hint:'Restart'})}${devText(btnField(i,'cmd'),'Command (no secrets here)')}${devText(btnField(i,'confirm'),'Question asked first, if it needs one')}</div>`).join('')}
    <div class="btns"><button class="btn" data-tool="btnadd">Add a button</button></div>`;
SHEETS.device=()=>{
  const edit=S.sheetArg, d=S.tools||{aliases:[]}, ssh=toolVal('kind')!=='other', n=edit||'';
  return `<h2>${edit?`Edit ${esc(edit)}`:'Add a device'}</h2>${devText('name','Name, as tasks name it',{hint:'macmini'})}${edit?'<div class="small">If you rename it, a task that needs it keeps the old name until it is edited.</div>':''}
    ${devText('description','What it is, what it is for, and its rules (agents read this; no secrets here)',{area:4})}
    ${S.devCustom&&!edit?'':devPick('kind','How agents reach it',[['ssh','SSH'],['other','Another way (a command or address)']])}
    ${ssh?`${d.aliases.length||toolVal('alias')?devPick('alias','Host',[['','Its own host, below'],...[...new Set([...(toolVal('alias')?[toolVal('alias')]:[]),...d.aliases])].map(a=>[a,`${a}, in ~/.ssh/config`])]):''}${toolVal('alias')?'<div class="small">Signs in as ~/.ssh/config says. No secret is copied.</div>':devText('host','Host name or address',{hint:'macmini.local'})+devText('user','User')+devText('port','Port',{num:true,hint:'22'})}`
    :devText('reach','The command or address it uses',{hint:'vnc://rig.local:5900'})+devText('page','Web page to open, if it has one',{hint:'http://rig.local:8080'})+devText('start','Command that starts the page, if it needs one',{hint:'npm start'})+devText('folder','Working directory of that command',{hint:'~/repos/rig'})+(edit?'':customDescribe())}
    <label class="row setline"><span class="grow">Only one task may use it at a time</span><input type="checkbox" role="switch" class="sw" data-f="${toolField('exclusive')}" aria-label="Only one task may use it at a time" ${toolVal('exclusive')==='true'?'checked':''}></label>
    ${devButtons()}
    ${toolSaid(n)}<div class="btns">${S.devCustom&&!edit?`<button class="btn pri${toolBusy('custom','')}" data-tool="customsave">Save</button>`:`<button class="btn pri${toolBusy('save',n)}" data-tool="save" data-name="${esc(n)}">Save</button>`}<button class="btn" data-closesheet>Cancel</button></div>`;
};
SHEETS.devsecrets=()=>{
  const t=toolOf(S.sheetArg);if(!t)return '<div class="small">That device is gone.</div>';
  const n=esc(t.name), open=S.secretOpen||'', off=S.tools.secure?'':'disabled';
  const row=what=>{const s=t.secrets[what], name=SECRET_NAME[what];
    if(what==='passphrase'&&!t.secrets.key)return '';
    return `<div class="sec">${name}<span class="ln"></span></div><div class="small">${s?`set, changed ${esc(s.changed)}`:'not set'}</div>
      ${s&&s.fp?`<div class="small tooltext"><span class="setkey">${esc(s.fp)}</span></div>`:''}
      ${s&&s.pub?`<div class="small">Public key, for ~/.ssh/authorized_keys on the device</div><pre class="out" data-pub>${esc(s.pub)}</pre>`:''}
      ${open===what?`${what==='key'?`<label class="small">Paste the private key<textarea class="fld masked" rows="5" data-f="${toolField('key')}" autocomplete="off" autocapitalize="off" spellcheck="false"></textarea></label><label class="small">Its passphrase, if it has one<input type="password" class="fld" data-f="${toolField('passphrase')}" autocomplete="new-password"></label>`
        :`<label class="small">${name}<input type="password" class="fld" data-f="${toolField(what)}" autocomplete="new-password"></label>`}
        <div class="btns"><button class="btn pri${toolBusy('secret',t.name,what)}" data-tool="secret" data-what="${what}" data-name="${n}">Save</button><button class="btn" data-tool="secretopen" data-what="">Cancel</button></div>`
      :S.sure===`secret:${what}`||S.sure===`pair`&&what==='key'?`<div class="small">${S.sure==='pair'?'Make a new key pair in place of this key?':`Remove the ${name.toLowerCase()}?`}</div><div class="btns"><button class="btn bad" data-tool="${S.sure==='pair'?'keypair':'unsecret'}" data-what="${what}" data-name="${n}">Yes</button><button class="btn" data-unsure>No</button></div>`
      :`<div class="btns"><button class="btn" data-tool="secretopen" data-what="${what}" ${off}>${s?'Replace':'Set'}</button>${what==='key'?`<button class="btn${toolBusy('keypair',t.name,'key')}" data-tool="keypair" data-what="key" data-name="${n}" ${s?'data-asks':''} ${off}>Make a key pair here</button>`:''}${s&&s.pub?'<button class="btn" data-tool="copypub">Copy the public key</button>':''}${s?`<button class="btn" data-tool="unsecretask" data-what="${what}" ${off}>Remove</button>`:''}</div>`}`};
  return `<h2>${n}</h2><div class="small">What is saved here is never shown again, here or in a chat.</div>${['key','passphrase','password'].map(row).join('')}${toolSaid(t.name)}<div class="btns"><button class="btn" data-closesheet>Close</button></div>`;
};
function toolEdit(t){
  toolForget();S.toolSaid={};
  for(const k of ['name','description','alias','host','user','reach','page','start','folder'])S.f[toolField(k)]=t&&t[k]||'';
  S.f[toolField('kind')]=t?t.kind:'ssh';S.f[toolField('port')]=t&&t.port?String(t.port):'';S.f[toolField('exclusive')]=String(!!(t&&t.exclusive));
  S.devBtns=(t&&t.buttons||[]).map((b,i)=>{for(const k of BTN_FIELDS)S.f[toolField(btnField(i,k))]=b[k]||'';return i});
  openSheet('device',t?t.name:'');
}
/* one of a tool's own buttons, straight to the run as toolPost() does. `a`: what the person answered, the question as it
   was asked and the key of the holder they were told of; the run asks again when either is another one now */
async function toolPress(name,source,label,a={}){
  const key=toolKey({source,name}), all=S.press=S.press||{};
  if((all[key]||{}).busy)return;
  const mine=all[key]={busy:label};render(true);
  let j;
  try{const r=await fetch(tq('tools'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({op:'press',name,button:label,source,...a})});j=await r.json()}
  catch(e){j={ok:false,out:'Could not reach the run page. The command may have run; check before you press again.'}}
  if(all[key]!==mine)return;  // the device was removed or renamed meanwhile
  const t=S.tools&&S.tools.tools.find(t=>t.name===name&&t.source===source), ask=o=>({ask:{...a,label,at:Date.now(),...o}});
  all[key]=j.ask?ask({q:j.ask,confirm:j.ask}):j.busy?ask({q:`${t?t.label:name} is held by ${j.busy.holder}.`,holder:j.busy.key,busy:true})
    :{said:{ok:!!j.ok,out:plainOut(j,'That failed.'),lines:j.lines||[],https:j.https||''}};
  render(true);await loadTools();
}
function pressClick(tool,name,source,label){
  const key=toolKey({source,name}), all=S.press=S.press||{}, {ask}=all[key]||{};
  if(tool==='pressno'){delete all[key];render(true);return}
  if(tool==='pressyes'){  // not by the second tap of the press that asked
    if(ask&&Date.now()-ask.at>=QUESTION_AGAIN)return toolPress(name,source,ask.label,{...(ask.confirm?{confirm:ask.confirm}:{}),...(ask.holder?{holder:ask.holder}:{})});
    return}
  const t=S.tools.tools.find(t=>t.name===name&&t.source===source), b=t&&(t.buttons||[]).find(b=>b.label===label);
  if(b&&b.confirm&&!(all[key]||{}).busy){all[key]={ask:{label,q:b.confirm,confirm:b.confirm,at:Date.now()}};render(true);return}
  return toolPress(name,source,label);
}
/* what a device's last press said goes when it is changed or removed: another one may take its name */
function pressForget(name,same){const p=(S.press||{})[name];if(p&&!(same&&p.busy))delete S.press[name]}
/* a button more or less in a device's sheet; saved with it */
function btnClick(x){
  if(x.dataset.tool==='btnadd'){
    const i=Math.max(-1,...S.devBtns)+1;S.devBtns=[...S.devBtns,i];for(const k of BTN_FIELDS)S.f[toolField(btnField(i,k))]='';
    render(true);const el=$('sheet').querySelector(`[data-f="${toolField(btnField(i,'label'))}"]`);if(el)el.focus();return}
  const i=+x.dataset.i;S.devBtns=S.devBtns.filter(b=>b!==i);for(const k of BTN_FIELDS)delete S.f[toolField(btnField(i,k))];
  render(true);const el=$('sheet').querySelector('[data-tool="btnadd"]');if(el)el.focus({preventScroll:true});
}
async function toolClick(x){
  const {tool,name,what,fp,source}=x.dataset, key=source?toolKey({source,name}):name;
  if(tool==='load')return loadTools();
  if(tool==='untilcheck')return untilCheck(x.dataset.check);
  if(tool==='show'){if(S.sheet)closeSheet();viewGo(()=>{S.toolGo=key;goView('tools')},S.thread);return}
  if(tool.startsWith('press'))return pressClick(tool,name,source,x.dataset.label);
  if(tool==='btnadd'||tool==='btndel')return btnClick(x);
  if(tool==='add'){S.devCustom=false;openSheet('tooladd');return}  // F466b
  if(/^(form|login|customsave)/.test(tool))return formClick(x);
  if(tool==='edit'){const t=toolOf(name);if(t)toolEdit(t);return}
  if(tool==='secrets'){toolForget();S.toolSaid={};openSheet('devsecrets',name);return}
  if(tool==='ask'){S.sure='tool:'+name;render(true);return}
  if(tool==='secretopen'){toolForget();S.secretOpen=what;S.sure=null;S.toolSaid={};render(true);return}
  if(tool==='unsecretask'){S.sure='secret:'+what;render(true);return}
  if(tool==='keypair'&&x.dataset.asks!==undefined){S.sure='pair';render(true);return}
  if(tool==='copypub'){const pre=$('sheet').querySelector('[data-pub]');if(!pre)return;
    try{await navigator.clipboard.writeText(pre.textContent);toast('Copied')}catch(e){const r=document.createRange();r.selectNodeContents(pre);const g=getSelection();g.removeAllRanges();g.addRange(r);toast('Selected: copy it with your own Copy')}return}
  if(tool==='save'){
    const a={op:'save',name:toolVal('name').trim(),...(name?{edit:name}:{})};
    for(const k of ['description','kind','alias','host','user','port','reach','page','start','folder'])a[k]=toolVal(k);
    a.exclusive=toolVal('exclusive')==='true';
    a.buttons=S.devBtns.map(i=>Object.fromEntries(BTN_FIELDS.map(k=>[k,toolVal(btnField(i,k))])));
    const j=await toolPost(a,name);if(j&&j.ok){pressForget(name,a.name===name);closeSheet();toast(j.out)}return}
  if(tool==='secret'){
    const a={op:'secret',name,what,[what]:toolVal(what)};if(what==='key')a.passphrase=toolVal('passphrase');
    for(const f of SECRET_FIELDS)delete S.f[f];for(const el of document.querySelectorAll('#sheet [data-f^="dev:"]'))el.value='';
    const j=await toolPost(a,name);if(j&&j.ok){S.secretOpen='';render(true)}return}
  S.sure=null;
  if(tool==='start'||tool==='stop'){const j=await toolPost({op:tool,name,...(source?{source}:{})},key);
    if(j&&j.state&&(j.ok||j.state==='failed')){S.toolSaid={};render(true)}return}  // the card's state says it, and stays true
  if(tool==='remove'){const j=await toolPost({op:tool,name},name);if(j&&j.ok)pressForget(name);return}
  toolPost({op:tool,name,...(what?{what}:{}),...(fp?{fp}:{})},name);
}
