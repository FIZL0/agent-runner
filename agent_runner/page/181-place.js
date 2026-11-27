/* B177: the open view and chat, per project and per tab (the title names the project on the run's own address) */
const PLACE_KEY='ar-place:'+(HKEY||document.title);
let placeWas='';
function keepPlace(){const p=JSON.stringify({v:S.view,t:S.thread||'',...(isNew(S.thread)?{c:S.ctx}:{})});if(!HOME_PAGE&&p!==placeWas){tabStore.set(PLACE_KEY,placeWas=p);if(S.view!=='projects')tabStore.set('ar-tab',S.thread?'':S.view)}}
/* before the first draw; the link's # goes from the address, so a later reload opens what was open then */
function takePlace(){
  if(HOME_PAGE)return;
  const p=placeOf(tabStore.get(PLACE_KEY),location.hash,!!HB,S.ob.filter(x=>x.newchat).map(x=>'@'+x.cid));
  S.view=p.v;S.thread=p.t||null;S.ctx=p.c||null;S.kept=p.t;S.quiet=p.t[0]==='@'?p.t:'';S.needGo=p.need||'';S.taskGo=p.task||'';
  if(p.link)try{history.replaceState(null,'',location.pathname+location.search)}catch(e){}
}
/* the chat a reload opened: true when the run has no such chat, and Home is open instead */
function keptCheck(){
  const n=S.kept, f=S.feeds[n];
  if(S.thread!==n||n[0]==='@'||isNew(n)||sessionOf(n)||f&&f.ok){S.kept='';return false}
  if(!S.snap.at||!f||f.name!==n||S.sent[n]&&(S.sent[n].pending||[]).length)return false;
  S.kept='';S.thread=null;S.ctx=null;S.view='home';return true;
}
/* a link to this page, followed in the tab that has it open */
addEventListener('hashchange',()=>{
  if(HOME_PAGE||!placeOf('',location.hash,!!HB).link)return;
  takePlace();if(S.ren)renameLeave(S.thread);S.drawer=false;S.sheet='';S.sure=null;render(true);placeLoad();if(S.needGo)needGo();
});
/* F150: a link to an item of Needs you: its sheet, once the run's word is there */
function needGo(){const id=S.needGo;if(!id||!S.snap.at)return;S.needGo='';if(needOf(id))needOpen(id)}
/* F482: a task named by a link or a chat: Work, with its sheet open */
function taskGo(id){if(!id)return;S.view='plan';S.thread=null;S.ctx=null;S.drawer=false;S.sheet='';S.sure=null;if(taskIsOpen('queue',id))render(true);else openTask(id)}
const taskIds=()=>(S.snap.queue||[]).concat(S.snap.shelved||[]).map(x=>x.id);
function placeLoad(){if(S.taskGo){const t=S.taskGo;S.taskGo='';taskGo(t)}if(S.thread)loadFeed(S.thread);if(S.view==='tools')loadTools();if(S.view==='settings')loadSettings()}

