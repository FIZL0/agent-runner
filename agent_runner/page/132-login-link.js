/* --- F466c: #login-add?name=…&for=… opens the Tools page's Login form with its name and 'what it is for' filled in
   (login_code.form_link: the link an agent blocks with when the Login it needs does not exist) ------------------- */
function loginLinkGo(){
  const m=/^#login-add\?(.*)$/.exec(location.hash);if(HOME_PAGE||!m)return;
  if(!S.snap||!S.snap.at){setTimeout(loginLinkGo,300);return}
  const q=new URLSearchParams(m[1]);
  try{history.replaceState(null,'',location.pathname+location.search)}catch(e){}
  S.view='tools';S.thread=null;loadTools();formClick({dataset:{tool:'formlogin'}});
  S.f[toolField('name')]=q.get('name')||'';S.f[toolField('purpose')]=q.get('for')||'';render(true);
}
addEventListener('load',loginLinkGo);addEventListener('hashchange',loginLinkGo);
