/* --- F126b: Log in again: the terminal that renews the login, in a sheet. Its page is ttyd's; the link it prints and the
   code it asks for are the sheet's own, as a phone can press no link and paste nothing in a terminal. The frame and the
   lines under it are put there by script, so a redraw never takes them */
const LG={frame:null,up:false,ended:false,base:'',timer:0,url:'',turn:0};
SHEETS.login=()=>`<h2>Log in again</h2><div class="small" id="loginsay" role="status"></div><div class="btns" id="loginbtns"></div>
  <form data-logincode id="logincode" hidden><label class="small">2. The code the sign-in page gives you<input class="fld" id="logininput" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="send"></label><div class="btns"><button class="btn">Send code</button></div></form>
  <div class="loginterm" id="loginterm" hidden></div>`;
function loginOpen(){LG.base=HOME_PAGE||atAll()?HB:'';LG.ended=false;LG.url='';openSheet('login');loginLoad()}
function loginLeave(){LG.turn++;clearTimeout(LG.timer);LG.up=false;if(LG.frame){LG.frame.remove();LG.frame=null}const i=$('logininput');if(i)i.value=''}
function loginSay(words){
  if(!$('loginsay'))return;
  setHTML($('loginsay'),esc(words));
  setHTML($('loginbtns'),LG.ended?'<button class="btn pri" data-login>Start again</button>':LG.url?`<a class="btn pri" href="${esc(LG.url)}" target="_blank" rel="noopener">1. Open the sign-in page ${I.ext}</a>`:'');
  $('logincode').hidden=LG.ended||!LG.url;$('loginterm').hidden=!LG.frame;
}
async function loginLoad(){
  const turn=++LG.turn;clearTimeout(LG.timer);if(LG.frame)LG.frame.remove();LG.frame=null;LG.up=false;loginSay('Connecting…');
  let i;try{i=await (await fetch(tq(LG.base+'terminal/login'))).json()}catch(e){i=null}
  if(turn!==LG.turn||S.sheet!=='login')return;
  if(!i){loginSay('The page could not be reached. Trying again…');LG.timer=setTimeout(loginLoad,3000);return}
  if(!i.ok)return loginSay(i.out||'The login could not be opened.');
  const f=document.createElement('iframe');f.title='Login';f.allow='clipboard-read; clipboard-write';f.src=LG.base+`t/${encodeURIComponent(T)}/login/?fontSize=12`;
  LG.frame=f;$('loginterm').appendChild(f);loginSay('Connecting…');
}
/* the link it printed, off its screen: a line it wrapped is one again */
function loginLook(){
  let t;try{t=LG.frame.contentWindow.term}catch(e){}
  if(t){const b=t.buffer.active;let all='';
    for(let y=0;y<b.length;y++){const l=b.getLine(y);if(l)all+=(l.isWrapped?'':'\n')+l.translateToString(true)}
    LG.url=loginLink(all)||LG.url}
  loginSay(LG.url?'Open the sign-in page, then paste its code here.':'Starting…');
}
const loginLink=s=>(String(s).match(/https:\/\/[^\s]+/)||[''])[0];
setInterval(()=>{if(S.sheet==='login'&&LG.up)loginLook()},700);
addEventListener('message',e=>{
  const d=e.data;if(e.origin!==location.origin||!d||!LG.frame||e.source!==LG.frame.contentWindow||d.session!=='login'||!d.state)return;
  LG.up=d.state==='up';clearTimeout(LG.timer);
  if(LG.up)return loginLook();
  if(d.code===4001){LG.ended=true;loginSay('The login command has ended.');if(HB)loadProjects()}
  else LG.timer=setTimeout(loginLoad,1500);  // only the connection: the login waits (login_hold.py)
});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&S.sheet==='login'&&!LG.up&&!LG.ended)loginLoad()});
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
