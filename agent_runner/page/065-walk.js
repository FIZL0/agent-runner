/* --- F194b: the example project's walkthrough (walkStep and the rest in the logic script), and Home's offer of it. Only
   where the server says the project is the example one. Where the person is, or that they skipped it, is kept per browser */
const walkKey=key=>'ar-walk:'+key, EX={busy:false,err:''};
let WK={key:null,st:null};
const walkIn=()=>HOME_PAGE?!!HKEY&&!!(projectOf(HKEY)||{}).example:S.snap.example===true;
function walkState(){
  const key=HKEY||S.snap.project||'';
  if(WK.key!==key)WK={key,st:walkParse(store.get(walkKey(key)))};
  return WK.st;
}
function walkSet(st){walkState();WK.st=st;store.set(walkKey(WK.key),JSON.stringify(st))}
function walkCtx(){
  const p=HOME_PAGE&&projectOf(HKEY)||{};
  return{off:HOME_PAGE,up:HOME_PAGE?!!p.starting||(p.state||'off')!=='off':S.snap.up!==false,working:HOME_PAGE?0:working_().length,
    needs:HOME_PAGE?p.needs||0:S.snap.needs.length,landed:(HOME_PAGE?p.landed||[]:S.snap.lately||[]).length,home:!!HB};
}
/* the step to draw, or null: never in another project or in a chat; in All projects only the one about adding a project */
function walkNow(){
  if(!walkIn()||S.thread||S.view==='talk')return null;
  const st=walkState();
  return st.off||atAll()&&st.at!=='own'?null:walkStep(st.at,walkCtx());
}
const walkThere=s=>!s.view||HOME_PAGE||S.view===s.view;
const walkRow=()=>walkIn()?`<div class="nav"><button class="ni" data-walk="again">${I.ask}Walkthrough</button></div>`:'';
function walkDraw(){
  const el=$('walk'), s=walkNow(), had=keysIn(el);el.hidden=!s;
  if(setHTML(el,s?walkHTML(s,walkCtx(),walkThere(s)):'')&&S.live)enter(el,had);
  if(s||document.querySelector('[data-walkat]'))requestAnimationFrame(walkPoint);  // once the view is drawn
}
function walkOnScreen(el){const r=el.getBoundingClientRect();return r.width>0&&r.right>0&&r.left<innerWidth&&getComputedStyle(el).visibility!=='hidden'&&!el.closest('.gone0,.sghost')}
function walkTargets(s){
  if(!walkThere(s))return[];
  for(const at of s.at){
    const all=at.startsWith('sec:')?[...document.querySelectorAll('#body .sec')].filter(x=>x.textContent.startsWith(at.slice(4))):[...document.querySelectorAll(at)];
    const l=all.filter(walkOnScreen);if(l.length)return l.slice(0,s.many||1);
  }
  return[];
}
function walkPoint(){
  const s=walkNow(), l=s?walkTargets(s):[];
  for(const x of document.querySelectorAll('[data-walkat]'))if(!l.includes(x))x.removeAttribute('data-walkat');
  for(const x of l)x.setAttribute('data-walkat','');
  return l;
}
/* a press moved to a step: its view, with the thing on screen; it glides there inside one view */
function walkShow(keys){
  const s=walkNow();if(!s)return render(true);
  const same=walkThere(s)&&!S.thread;
  if(same){S.drawer=false;render(true)}else goView(s.view);
  const l=walkPoint(), b=$('body');
  if(l.length&&b.contains(l[0])){
    const r=l[0].getBoundingClientRect(), box=b.getBoundingClientRect(), y=r.top-flying(l[0])-box.top;
    if(y<8||y+r.height>b.clientHeight-8){const to=Math.max(0,b.scrollTop+y-Math.max(12,(b.clientHeight-r.height)/2));if(same)scrollGlide(b,to);else b.scrollTop=to}
  }
  if(keys){const t=$('walk').querySelector('[data-walk="next"],[data-addproject],[data-walk="done"]');if(t)t.focus({preventScroll:true})}
}
async function tryExample(){
  if(EX.busy)return;
  EX.busy=true;EX.err='';render(true);
  const d=await homePost('example',{});EX.busy=false;
  if(!d.ok||!d.key){EX.err=d.out||'It was not made.';render(true);return}
  if(d.made)store.set(walkKey(d.key),'');  // a new copy starts its walkthrough again
  location.href=projectLink(HB,d.key,T)+'#home';
}
document.addEventListener('click',e=>{
  if(e.target.closest('[data-example]')){tryExample();return}
  const x=e.target.closest('[data-walk]');if(!x)return;
  const how=x.dataset.walk;
  if(how!=='show')walkSet(walkMove(walkState(),how));
  if(how==='skip'||how==='done'){render(true);toast('The walkthrough stays in the menu');return}
  if(how==='again'&&(atAll()||S.thread||S.view==='talk')){goView('home')}
  walkShow(!e.detail);
});
addEventListener('storage',e=>{if(e.key&&e.key===walkKey(WK.key)){WK.key=null;render(true)}});
