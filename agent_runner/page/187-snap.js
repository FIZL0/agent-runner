/* F150: switching draws the project's last snapshot at once. One is kept per project, the last SNAPS of them, each up to
   SNAP_MAX characters (the rest of this browser's room is the outbox's) */
const SNAP='ar-snap:', SNAPS=6, SNAP_MAX=200000;
function snapKeep(){
  if(HOME_PAGE||!HKEY||!S.snap.at)return;
  const text=JSON.stringify(snapKept(S.snap));if(text.length>SNAP_MAX){store.set(SNAP+HKEY,'');return}
  let l;try{l=JSON.parse(store.get(SNAP+'@')||'[]')}catch(e){}
  l=[HKEY,...(Array.isArray(l)?l:[]).filter(k=>k!==HKEY)];
  for(const k of l.slice(SNAPS))store.set(SNAP+k,'');
  store.set(SNAP+'@',JSON.stringify(l.slice(0,SNAPS)));store.set(SNAP+HKEY,text);
}
function snapTake(){
  if(HOME_PAGE||!HKEY)return;
  let s;try{s=JSON.parse(store.get(SNAP+HKEY)||'null')}catch(e){}
  if(s&&typeof s==='object'&&['status','sessions','queue','needs','concepts','log'].every(k=>Array.isArray(s[k])))S.snap={...S.snap,...s};
}
addEventListener('pagehide',snapKeep);
document.addEventListener('visibilitychange',()=>{if(document.hidden)snapKeep()});
addEventListener('pagehide',finalDelete);  // F118: leaving the page makes a pending delete final

projectsKept();snapTake();H.tab=tabStore.get('ar-alltab');  // F150: what was last seen draws at once
takePlace();  // B177: before the first draw
takeTyped();  // F149
render(true);
if(HOME_PAGE){  // F134: Home's own page: no run behind it, only Home's projects and devices
  loadProjects();loadDevices();homeDrain();setInterval(loadProjects,HKEY?2500:5000);setInterval(loadDevices,30000);
}else{
connect();
placeLoad();  // B177
drain();  // F137: what a reload left in the outbox goes now (the run page runs each cid once)
if(HB){loadProjects();homeDrain();let tick=0;  // F134: every 5 s while All projects shows, else every 30 s
  setInterval(()=>{if(atAll()||++tick%6===0)loadProjects()},5000);
  setInterval(()=>{if(atAll())loadDevices()},30000);loadDevices()}
}
devLink()||devPlace(history.state);if(HB)setInterval(()=>{if(devOn())devLoad()},30000);  // B818a
/* B179: a concept's page in the Home Screen app, where a new tab would be iOS's browser over the app */
function conceptOpen(src,title){
  const el=$('cview');if(el._bye)el._bye();
  el.innerHTML=`<div class="top"><button class="icon" data-cviewclose aria-label="Back" title="Back">${I.back}</button><b class="ell">${esc(title)}</b></div><iframe src="${esc(src)}" sandbox="allow-scripts" title="${esc(title)}"></iframe>`;
  el.hidden=false;el.querySelector('button').focus({preventScroll:true});
  moAnim(el,[{transform:'translateX(100%)'},{transform:'none'}],{ease:'--spring-soft'});
}
/* F189b: it slides out, out of reach at once */
function conceptClose(){
  const el=$('cview'), a=moAnim(el,[{transform:'none'},{transform:'translateX(100%)'}],{ease:'--spring-soft',fill:'forwards'});
  const bye=el._bye=()=>{if(el._bye!==bye)return;el._bye=null;if(a)a.cancel();el.inert=false;el.hidden=true;el.innerHTML=''};
  if(!a){bye();return}
  el.inert=true;a.onfinish=bye;
}
document.addEventListener('click',e=>{
  if(e.target.closest('[data-cviewclose]')){conceptClose();return}
  const a=ON_HOME_SCREEN&&e.target.closest('a[target="_blank"]'), k=a?appLink(a.href,location.origin,ROOT):'';
  if(!k)return;
  e.preventDefault();
  if(k==='concept'){const q=a.closest('.card')&&a.closest('.card').querySelector('.q');conceptOpen(a.href,q?q.textContent:'Concept')}
  else location.href=a.href;
});
/* Esc closes the topmost thing only */
window.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('cview').hidden===false&&!$('cview').inert){e.preventDefault();e.stopImmediatePropagation();conceptClose()}},true);
