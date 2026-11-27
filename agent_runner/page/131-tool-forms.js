/* --- F466b: the Tools page's Add… offers three forms: SSH machine (SHEETS.device), Login, Custom tool -------------- */
SHEETS.tooladd=()=>`<h2>Add</h2>
  <button class="it" data-tool="formssh"><b>SSH machine</b><div class="small">A machine or test rig agents reach over SSH</div></button>
  <button class="it" data-tool="formlogin"><b>Login</b><div class="small">A website or account login agents may use, without seeing its password</div></button>
  <button class="it" data-tool="formcustom"><b>Custom tool</b><div class="small">Reached another way: a command or address, described in your own words</div></button>
  <div class="btns"><button class="btn" data-closesheet>Cancel</button></div>`;
const loginOf=n=>((S.tools||{}).logins||[]).find(l=>l.name===n);
/* write-only: the sheet never holds a saved password, and the card shows only set or not set */
SHEETS.devlogin=()=>{
  const edit=S.sheetArg, lg=edit?loginOf(edit):null, off=S.tools&&S.tools.secure?'':'disabled', n=edit||'';
  if(edit&&!lg)return '<div class="small">That login is gone.</div>';
  return `<h2>${edit?`Replace ${esc(edit)}`:'Add a login'}</h2>${edit?'':devText('name','Name, as tasks name it',{hint:'apple-id-free'})}
    ${devText('purpose','What it is for (agents read this; no secrets here)',{area:3})}${devText('user','Username')}
    <label class="small">${edit?'New password (empty keeps the old one)':'Password'}<input type="password" class="fld" data-f="${toolField('password')}" autocomplete="new-password"></label>
    ${devText('twofa','2FA goes to, if it has one',{hint:'the iPhone 15'})}${devText('projects','Projects that may use it, by folder name, comma between (* for all)',{hint:'iFizBox'})}
    <div class="small">What is saved here is never shown again, here or in a chat.</div>
    ${toolSaid('login:'+n)}<div class="btns"><button class="btn pri${toolBusy('login_save','login:'+n)}" data-tool="loginsave" data-name="${esc(n)}" ${off}>Save</button><button class="btn" data-closesheet>Cancel</button></div>`;
};
function loginCard(l){
  const n=esc(l.name), off=S.tools.secure?'':'disabled';
  return card(`<b>${n}</b>${l.purpose?`<div class="tooltext">${esc(l.purpose)}</div>`:''}
    <div class="small tooltext">${l.user?`${esc(l.user)} · `:''}password ${l.set?`set${l.changed?`, updated ${esc(l.changed)}`:''}`:'not set'}${l.twofa?` · 2FA goes to ${esc(l.twofa)}`:''}</div>
    <div class="small">Projects: ${esc((l.projects||[]).join(', ')||'none')}</div>${toolSaid('login:'+l.name)}
    ${S.sure==='login:'+l.name?`<div class="small">Remove the login ${n}, its password too?</div><div class="btns"><button class="btn bad" data-tool="loginremove" data-name="${n}">Yes, remove</button><button class="btn" data-unsure>No</button></div>`
    :`<div class="btns"><button class="btn" data-tool="loginedit" data-name="${n}" ${off}>Replace…</button><button class="btn" data-tool="loginask" data-name="${n}" ${off}>Remove</button></div>`}`,'',`data-k="login:${n}"`);
}
const loginsHTML=()=>{const ls=(S.tools||{}).logins||[];return ls.length?`<div class="sec">Logins<span class="ln"></span></div>${ls.map(loginCard).join('')}`:''};
/* the Custom tool form is the device sheet's 'Another way' with Describe it under it (customDescribe(), 130-tools.js) */
async function formClick(x){
  const {tool,name}=x.dataset;
  if(tool==='formssh'){S.devCustom=false;return toolEdit(null)}
  if(tool==='formcustom'){toolEdit(null);S.devCustom=true;S.f[toolField('kind')]='other';render(true);return}
  if(tool==='formlogin'||tool==='loginedit'){toolForget();S.toolSaid={};
    const l=name?loginOf(name):null;for(const k of ['purpose','user','twofa'])S.f[toolField(k)]=l&&l[k]||'';
    S.f[toolField('projects')]=l?(l.projects||[]).join(', '):'';openSheet('devlogin',name||'');return}
  if(tool==='loginask'){S.sure='login:'+name;render(true);return}
  if(tool==='loginremove'){S.sure=null;return toolPost({op:'login_remove',name},'login:'+name)}
  if(tool==='loginsave'){
    const a={op:'login_save',name:name||toolVal('name').trim(),password:toolVal('password')};
    for(const k of ['purpose','user','twofa','projects'])a[k]=toolVal(k);
    delete S.f[toolField('password')];for(const el of document.querySelectorAll('#sheet input[type=password]'))el.value='';
    const j=await toolPost(a,'login:'+(name||''));if(j&&j.ok){closeSheet();toast(j.out)}return}
  if(tool==='customsave'){
    const a={op:'custom',name:toolVal('name').trim(),describe:toolVal('describe')};
    for(const k of ['description','reach','page','start','folder'])a[k]=toolVal(k);
    a.exclusive=toolVal('exclusive')==='true';
    a.buttons=S.devBtns.map(i=>Object.fromEntries(BTN_FIELDS.map(k=>[k,toolVal(btnField(i,k))])));
    const j=await toolPost(a,'');if(j&&j.ok){S.devCustom=false;closeSheet();toast(j.out)}return}
}
