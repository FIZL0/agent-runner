/* F406c: a model provider's too (LG.p): its terminal (LG.name) runs `run login`; Copilot's sheet first asks where it is. */
/* --- F126b: Log in again: the terminal that renews the login, in a sheet. Its page is ttyd's; the link it prints and the
   code it asks for are the sheet's own, as a phone can press no link and paste nothing in a terminal. The frame and the
   lines under it are put there by script, so a redraw never takes them */
const LG={frame:null,up:false,ended:false,base:'',timer:0,url:'',turn:0,p:'',name:'login',at:{},code:'',done:false};
SHEETS.login=()=>LG.p&&!LG.name?`<h2>Log in to copilot</h2><div class="small">Where is your GitHub Copilot?</div><div class="btns"><button class="btn pri" data-loginhost>github.com</button></div>
  <div class="sec">GitHub Enterprise<span class="ln"></span></div><form data-loginghe class="loginghe"><label class="small">Your GitHub Enterprise domain<input class="fld" data-f="logindomain" placeholder="company.ghe.com" inputmode="url" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="go"></label><div class="btns"><button class="btn">Use this domain</button></div></form>`:`<h2>${LG.p?`Log in to ${esc(LG.p)}`:'Log in again'}</h2><div class="small" id="loginsay" role="status"></div><div class="btns" id="loginbtns"></div>
  <form data-logincode id="logincode" hidden><label class="small">${LG.p?'What the login asks for (goes only to its terminal)':'2. The code the sign-in page gives you'}<input class="fld" id="logininput"${LG.p?' type="password"':''} autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="send"></label><div class="btns"><button class="btn">${LG.p?'Send':'Send code'}</button></div></form>
  <div class="loginterm" id="loginterm" hidden></div>`;
function loginOpen(p=''){
  loginLeave();LG.p=p;LG.base=!p&&(HOME_PAGE||atAll())?HB:'';LG.ended=LG.done=false;LG.url=LG.code='';
  const going=p&&(S.logins||[]).some(l=>l.name===p&&l.login&&l.login.state==='running');
  LG.name=!p?'login':p!=='copilot'?`login-${p}`:going&&LG.at[p]||'';
  openSheet('login');if(LG.name)loginLoad();
}
/* Copilot's: on a GitHub Enterprise domain, or ('') on github.com */
function loginAt(domain){LG.name='login-copilot'+(domain?`~${domain}`:'');LG.at.copilot=LG.name;render(true);loginLoad()}
function loginLeave(){LG.turn++;clearTimeout(LG.timer);LG.up=false;if(LG.frame){LG.frame.remove();LG.frame=null}const i=$('logininput');if(i)i.value=''}
function loginSay(words){
  if(!$('loginsay'))return;
  setHTML($('loginsay'),esc(words));
  setHTML($('loginbtns'),LG.done?'<button class="btn pri" data-closesheet>Close</button>':LG.ended?`<button class="btn pri" ${LG.p?`data-plogin="${esc(LG.p)}"`:'data-login'}>Start again</button>`:LG.url?`<a class="btn pri" href="${esc(LG.url)}" target="_blank" rel="noopener">${LG.p?'':'1. '}Open the sign-in page ${I.ext}</a>`:'');
  $('logincode').hidden=LG.ended||(LG.p?!LG.up:!LG.url);$('loginterm').hidden=!LG.frame||LG.done;
}
async function loginLoad(){
  const turn=++LG.turn;clearTimeout(LG.timer);if(LG.frame)LG.frame.remove();LG.frame=null;LG.up=false;loginSay('Connecting…');
  let i;try{i=await (await fetch(tq(LG.base+'terminal/'+encodeURIComponent(LG.name)))).json()}catch(e){i=null}
  if(turn!==LG.turn||S.sheet!=='login')return;
  if(!i){loginSay('The page could not be reached. Trying again…');LG.timer=setTimeout(loginLoad,3000);return}
  if(!i.ok)LG.ended=!!LG.p;
  if(!i.ok)return loginSay(i.out||'The login could not be opened.');
  const f=document.createElement('iframe');f.title='Login';f.allow='clipboard-read; clipboard-write';f.src=LG.base+`t/${encodeURIComponent(T)}/${encodeURIComponent(LG.name)}/?fontSize=12`;
  LG.frame=f;$('loginterm').appendChild(f);loginSay('Connecting…');
}
/* the link it printed, off its screen: a line it wrapped is one again */
function loginLook(){
  let t;try{t=LG.frame.contentWindow.term}catch(e){}
  if(t){const b=t.buffer.active;let all='';
    for(let y=0;y<b.length;y++){const l=b.getLine(y);if(l)all+=(l.isWrapped?'':'\n')+l.translateToString(true)}
    if(LG.p){const a=loginAsks(all);LG.url=a.url||LG.url;LG.code=a.code||LG.code}else LG.url=loginLink(all)||LG.url}
  if(LG.p)return loginSay(LG.code?`Open the sign-in page and enter the code ${LG.code} there. This says when it is done.`:LG.url?'Open the sign-in page and finish there. Answer below what the login asks.':'Answer below what the login asks.');
  loginSay(LG.url?'Open the sign-in page, then paste its code here.':'Starting…');
}
const loginLink=s=>(String(s).match(/https:\/\/[^\s]+/)||[''])[0];
setInterval(()=>{if(S.sheet==='login'&&LG.up)loginLook()},700);
addEventListener('message',e=>{
  const d=e.data;if(e.origin!==location.origin||!d||!LG.frame||e.source!==LG.frame.contentWindow||d.session!==LG.name||!d.state)return;
  LG.up=d.state==='up';clearTimeout(LG.timer);
  if(LG.up){if(LG.p)loadLogins();return loginLook()}
  if(d.code===4001&&LG.p)return loginEnded();
  if(d.code===4001){LG.ended=true;loginSay('The login command has ended.');if(HB)loadProjects()}
  else LG.timer=setTimeout(loginLoad,1500);  // only the connection: the login waits (login_hold.py)
});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&S.sheet==='login'&&LG.name&&!LG.up&&!LG.ended)loginLoad()});
/* F406c: how a provider's login ended, as the run says it */
async function loginEnded(){
  const p=LG.p, turn=LG.turn;LG.ended=true;loginSay('The login has ended.');
  const got=await loadLogins();
  if(turn!==LG.turn||S.sheet!=='login')return;
  if(!got){loginSay('The page could not be reached. Trying again…');LG.timer=setTimeout(loginEnded,3000);return}
  const l=((S.logins||[]).find(x=>x.name===p)||{}).login;
  LG.done=!!l&&l.state==='done';
  loginSay(LG.done?`${l.said}${(l.reopened||[]).length?`. Starts again: ${l.reopened.join(', ')}`:''}`:l&&l.said?`The login failed: ${l.said}`:'The login has ended.');
}
document.addEventListener('click',e=>{
  const x=e.target.closest&&e.target.closest('[data-plogin]'), g=e.target.closest&&e.target.closest('[data-loginhost]');
  if(x)loginOpen(x.dataset.plogin);
  else if(g)loginAt('');
});
/* a login that goes on while its sheet is closed: its row says when it is done */
setInterval(()=>{if(!document.hidden&&S.view==='settings'&&!S.thread&&(S.logins||[]).some(l=>l.login&&l.login.state==='running'))loadLogins()},5000);
function loginCode(){
  const i=$('logininput'), c=i.value.trim();let t;try{t=LG.up&&LG.frame.contentWindow.term}catch(e){}
  if(!c)return;
  if(!t)return toast('The login is not connected yet',true);
  i.value='';t.input(c,true);setTimeout(()=>t.input('\r',true),150);
}
/* F150: a project's …, and + Project */
SHEETS.project=()=>{
  const p=projectOf(S.sheetArg);if(!p)return '<div class="small">Runner Home no longer lists it.</div>';
  const k=esc(p.key);
  return `<h2>${esc(p.name||p.key)}</h2><div class="small">${esc([projectState(p),projectWords(p)].filter(Boolean).join(' · '))}</div>${hobOf(p.key)}${projectMore(p).map(b=>{
    const at=b.unlist?`data-punlist data-pkey="${k}"`:`data-pact="${b.a}" data-pkey="${k}"`;
    if(b.step!=null)return `<div class="it setrow"><span>Slots</span><span class="step"><button class="btn" data-pact="slots" data-parg="${b.step-1}" data-pkey="${k}" aria-label="One slot less" ${b.step<2?'disabled':''}>−</button><b>${b.step}</b><button class="btn" data-pact="slots" data-parg="${b.step+1}" data-pkey="${k}" aria-label="One slot more" ${b.step>98?'disabled':''}>+</button></span></div>`;
    return S.sure===`proj:${b.label}:${p.key}`?sureHTML(b.sure,b.label.toLowerCase(),at):`<button class="it${b.sure?' bad':''}" ${at}>${b.label}${b.sure?'…':''}</button>`}).join('')}`;
};
/* B222b: no typed word is in its markup: keepFields() puts it back */
SHEETS.addproject=()=>`<h2>Add a project</h2><form data-padd style="display:grid;gap:var(--s3)"><label class="small">Its folder on ${esc(H.machine||'this machine')}<input class="fld" data-f="padd" placeholder="~/repos/myproject" autocomplete="off" autocapitalize="off" spellcheck="false"></label>${H.said?`<div class="small"><span class="v-bad">${esc(H.said)}</span></div>`:''}<div class="btns"><button class="btn pri${H.adding?' busy':''}">Add</button><button type="button" class="btn" data-closesheet>Cancel</button></div></form>`;
