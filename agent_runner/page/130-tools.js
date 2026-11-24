/* --- F169: Tools ---------------------------------------------------------------------------------------------- */
async function loadTools(){
  try{const r=await fetch(tq('tools')), j=await r.json();S.toolOld=false;
    if(r.ok&&j&&Array.isArray(j.tools)){S.tools=j;S.toolErr=''}
    else{S.toolOld=oldRun(j);S.toolErr=plainOut(j,'The tools could not be read.')}}
  catch(e){S.toolErr='Could not reach the run page to read the tools.'}
  if(S.view==='tools')render();
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
/* what is typed in a device's sheet goes when it closes, a secret first of all */
function toolForget(){for(const k of Object.keys(S.f))if(k.startsWith('dev:'))delete S.f[k];for(const el of $('sheet').querySelectorAll('[data-f^="dev:"]'))if(el.type!=='checkbox')el.value='';S.secretOpen=''}
const SECRET_NAME={key:'Private key',passphrase:'Key passphrase',password:'Password'};
const toolSaid=n=>{const s=(S.toolSaid||{})[n];return s?`<div class="small ${s.ok?'':'v-bad'}" role="status">${esc(s.out)}${s.https?` <a href="${esc(s.https)}">${esc(s.https.split('?')[0])}</a>`:''}</div>`:''};
const toolBusy=(op,n,what)=>S.toolBusy===`${op}:${n||''}:${what||''}`?' busy':'';
function toolAgo(at){const m=Math.max(0,Math.floor((Date.now()/1000-at)/60));return m<1?'just now':m<60?`${m} min ago`:m<1440?`${Math.floor(m/60)} h ago`:`${Math.floor(m/1440)} d ago`}
const toolWords=t=>(t.words||'not checked yet')+(t.at?` · checked ${toolAgo(t.at)}`:'');
const toolWhere=t=>t.source==='runner.toml'?`[run.tools.${t.name}] in runner.toml, edited there`:t.kind==='other'?t.reach:t.alias?`SSH, ${t.alias} in ~/.ssh/config`:`SSH, ${t.user?t.user+'@':''}${t.host}${t.port===22?'':':'+t.port}`;
function toolCard(t){
  const dev=t.source==='device', cls={free:'ok',busy:'warn',missing:'bad',unknown:'warn'}[t.state]||'', n=esc(t.name);
  return card(`<div class="row setline"><span class="grow"><b>${esc(t.label)}</b></span>${dev?`<label class="row small">Used here <input type="checkbox" role="switch" class="sw" data-tooluse="${n}" aria-label="This project uses ${n}" ${t.used?'checked':''} ${S.tools.secure?'':'disabled'}></label>`:''}</div>
    <div data-k="toolstate:${n}" data-v="${esc(t.state)}"><span class="${cls?'v-'+cls:'small'}">${esc(toolWords(t))}</span></div>
    ${t.description?`<div class="tooltext">${esc(t.description)}</div>`:''}
    <div class="small tooltext">${esc(toolWhere(t))}${dev&&t.exclusive?' · one task at a time':''}</div>
    ${dev?`${t.kind==='ssh'?toolHostKey(t):''}${toolSaid(t.name)}
    ${S.sure==='tool:'+t.name?`<div class="small">Remove ${n} for every project, its keys and password too?</div><div class="btns"><button class="btn bad" data-tool="remove" data-name="${n}">Yes, remove</button><button class="btn" data-unsure>No</button></div>`
    :`<div class="btns"><button class="btn${toolBusy('test',t.name)}" data-tool="test" data-name="${n}" ${S.tools.secure?'':'disabled'}>Test connection</button><button class="btn" data-tool="edit" data-name="${n}">Edit…</button>${t.kind==='ssh'&&!t.alias?`<button class="btn" data-tool="secrets" data-name="${n}">Keys and password…</button>`:''}<button class="btn" data-tool="ask" data-name="${n}" ${S.tools.secure?'':'disabled'}>Remove</button></div>`}`:''}`,'',`data-k="tool:${esc(t.source)}:${n}"`);
}
/* the fingerprint that waits for the person, else the accepted one */
function toolHostKey(t){
  const h=((S.toolSaid||{})[t.name]||{}).hostkey, n=esc(t.name);
  if(h)return `<div class="small tooltext">${h.was?`Accepted before: <span class="setkey">${esc(h.was)}</span><br>It shows now: `:'It shows: '}<span class="setkey">${esc(h.fp)}</span> (${esc(h.type)})</div><div class="btns"><button class="btn pri${toolBusy('accept',t.name)}" data-tool="accept" data-name="${n}" data-fp="${esc(h.fp)}">${h.was?'Accept the new fingerprint':'Accept this fingerprint'}</button></div>`;
  return t.hostkey?`<div class="small tooltext">Host key <span class="setkey">${esc(t.hostkey.fp)}</span>, accepted ${esc(t.hostkey.changed)}</div>`:'<div class="small">Its host key is not accepted yet: test the connection.</div>';
}
function toolsHTML(){
  const d=S.tools, err=S.toolErr?(S.toolOld?oldRunHTML(S.toolErr):`<div class="small v-bad">${esc(S.toolErr)}</div>`)+'<div class="btns"><button class="btn" data-tool="load">Try again</button></div>':'';
  if(!d)return `<div class="col">${err||emptyCard('Loading…')}</div>`;
  const toml=d.tools.filter(t=>t.source!=='device'), devs=d.tools.filter(t=>t.source==='device');
  return `<div class="col">${d.secure?'':card(`<b>Read only here</b><div class="small">Devices and secrets are saved only over https or on the machine itself.${d.https?'':' There is no https link yet: Tailscale Serve gives one.'}</div>${d.https?`<div class="btns"><a class="btn pri" href="${esc(d.https)}">Open the https link</a></div>`:''}`)}
    ${err}<div class="sec">Devices<span class="ln"></span></div>${devs.length?devs.map(toolCard).join(''):emptyCard('No device yet. Add a machine or test rig for agents to reach.')}
    ${toml.length?`<div class="sec">From runner.toml<span class="ln"></span></div>${toml.map(toolCard).join('')}`:''}
    <div class="small">Devices belong to this machine and its projects share them. Keys and passwords stay out of every chat, but agents run as the same user here, so this is no wall against an agent that goes looking.</div></div>`;
}
const devText=(k,label,o={})=>`<label class="small">${label}${o.area?`<textarea class="fld" rows="${o.area}" data-f="${toolField(k)}" ${o.hint?`placeholder="${o.hint}"`:''}>${esc(toolVal(k))}</textarea>`:`<input class="fld" data-f="${toolField(k)}" value="${esc(toolVal(k))}" ${o.num?'inputmode="numeric"':''} ${o.hint?`placeholder="${o.hint}"`:''} autocomplete="off" autocapitalize="off" spellcheck="false">`}</label>`;
const devPick=(k,label,opts)=>`<label class="small">${label}<select class="fld" data-f="${toolField(k)}">${opts.map(([v,l])=>`<option value="${esc(v)}" ${v===toolVal(k)?'selected':''}>${esc(l)}</option>`).join('')}</select></label>`;
SHEETS.device=()=>{
  const edit=S.sheetArg, d=S.tools||{aliases:[]}, ssh=toolVal('kind')!=='other', n=edit||'';
  return `<h2>${edit?`Edit ${esc(edit)}`:'Add a device'}</h2>${devText('name','Name, as tasks name it',{hint:'macmini'})}${edit&&toolVal('name')!==edit?'<div class="small">A task that needs it keeps the old name until it is edited.</div>':''}
    ${devText('description','What it is, what it is for, and its rules (agents read this; no secrets here)',{area:4})}
    ${devPick('kind','How agents reach it',[['ssh','SSH'],['other','Another way (a command or address)']])}
    ${ssh?`${d.aliases.length||toolVal('alias')?devPick('alias','Host',[['','Its own host, below'],...[...new Set([...(toolVal('alias')?[toolVal('alias')]:[]),...d.aliases])].map(a=>[a,`${a}, in ~/.ssh/config`])]):''}${toolVal('alias')?'<div class="small">Signs in as ~/.ssh/config says. No secret is copied.</div>':devText('host','Host name or address',{hint:'macmini.local'})+devText('user','User')+devText('port','Port',{num:true,hint:'22'})}`
    :devText('reach','The command or address it uses',{hint:'vnc://rig.local:5900'})}
    <label class="row setline"><span class="grow">Only one task may use it at a time</span><input type="checkbox" role="switch" class="sw" data-f="${toolField('exclusive')}" aria-label="Only one task may use it at a time" ${toolVal('exclusive')==='true'?'checked':''}></label>
    ${toolSaid(n)}<div class="btns"><button class="btn pri${toolBusy('save',n)}" data-tool="save" data-name="${esc(n)}">Save</button><button class="btn" data-closesheet>Cancel</button></div>`;
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
  for(const k of ['name','description','alias','host','user','reach'])S.f[toolField(k)]=t&&t[k]||'';
  S.f[toolField('kind')]=t?t.kind:'ssh';S.f[toolField('port')]=t&&t.port?String(t.port):'';S.f[toolField('exclusive')]=String(!!(t&&t.exclusive));
  openSheet('device',t?t.name:'');
}
async function toolClick(x){
  const {tool,name,what,fp}=x.dataset;
  if(tool==='load')return loadTools();
  if(tool==='add')return toolEdit(null);
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
    for(const k of ['description','kind','alias','host','user','port','reach'])a[k]=toolVal(k);
    a.exclusive=toolVal('exclusive')==='true';
    const j=await toolPost(a,name);if(j&&j.ok){closeSheet();toast(j.out)}return}
  if(tool==='secret'){
    const a={op:'secret',name,what,[what]:toolVal(what)};if(what==='key')a.passphrase=toolVal('passphrase');
    for(const f of SECRET_FIELDS)delete S.f[f];for(const el of document.querySelectorAll('#sheet [data-f^="dev:"]'))el.value='';
    const j=await toolPost(a,name);if(j&&j.ok){S.secretOpen='';render(true)}return}
  S.sure=null;
  toolPost({op:tool,name,...(what?{what}:{}),...(fp?{fp}:{})},name);
}
