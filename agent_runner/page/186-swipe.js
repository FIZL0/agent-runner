/* F124: a swipe right anywhere opens the sidebar drawer and a swipe left closes it, following the finger;
   a swipe down closes the sheet. B167: a touch is one thing until the finger lifts: one that scrolled never becomes a
   swipe, and a drawer swipe keeps the page from scrolling (so touchmove is not passive). Not from a text box, a sideways scroller, a held mic, a row being dragged or
   a mostly vertical move; Safari keeps its own back swipe at the very edge. */
let SW=null, PULL=null;  // F401: PULL is the spinner of a pull to refresh
/* F147: a panel goes on from where the finger left it, with its speed; .drag stays on (no transition) until it is there */
function runStop(el){  // from where it is, the stylesheet's transition takes it on (or a finger)
  const a=el&&el._run;if(!a)return;
  const c=getComputedStyle(el), st={transform:c.transform,opacity:c.opacity}, p=el===$('scrim')?'opacity':'transform';
  el.style[p]=st[p];el._run=null;a.cancel();void el.offsetWidth;el.classList.remove('drag');el.style[p]='';
  if(el===$('side'))runStop($('scrim'));
}
function springRun(el,frames,css){
  const done=()=>{el._run=null;el.classList.remove('drag')};
  if(!el.animate||calm())return done();
  const a=el._run=el.animate(frames.map(css),{duration:(frames.length-1)*16,easing:'linear'});a.onfinish=a.oncancel=()=>{if(el._run===a)done()};
}
/* where a panel is now (it may still be on its way), and the finger has it */
function grab(el,axis,rest){let at=rest;try{at=shiftOf(el)[axis]}catch(e){}runStop(el);return at}
const sideways=el=>{for(;el&&el!==document.body;el=el.parentElement)if(el.scrollWidth>el.clientWidth+1&&/(auto|scroll)/.test(getComputedStyle(el).overflowX))return true;return false};
/* B167: what a touch could scroll, and did it: a change of height is the page's own scroll (a chat's new message) */
const scrollers=el=>{const a=[];for(;el&&el!==document.body;el=el.parentElement)if(el.scrollHeight>el.clientHeight+1)a.push([el,el.scrollTop,el.scrollHeight]);return a};
const scrolled=a=>a.some(s=>{const [el,top,h]=s;if(el.scrollHeight===h)return el.scrollTop!==top;s[1]=el.scrollTop;s[2]=el.scrollHeight;return false});
const drawerOn=()=>{const m=document.querySelector('.top .menu');return !!(m&&m.offsetParent)};
/* B813: the drawer opens without the keyboard; before render, which would hand the focus on. The draft stays */
function drawerBlur(){if(TOUCH()&&typingIn(document.activeElement))document.activeElement.blur()}
document.addEventListener('touchstart',e=>{
  if(SW&&SW.on&&!SW.sheet){if(e.touches.length>1&&!SW.pl)return;swipeEnd(false)}  // B167: a second finger does not end the lock
  SW=null;const t=e.touches[0], el=e.target;
  if(e.touches.length!==1||!el.closest||el.closest('input,textarea,select,[contenteditable],iframe,.obpop,.cview,.mic.hold')||DR&&DR.on)return;
  if(S.sheet){if(el.closest('#sheet')&&$('sheet').scrollTop<=0)SW={sheet:true,x:t.clientX,y:t.clientY,at:e.timeStamp,d:0,on:false,ly:t.clientY,lt:e.timeStamp,v:0,base:0};return}
  const scr=scrollers(el), dr=drawerOn()&&!(el.closest('#body,#dock')&&sideways(el)), pull=pullPane(el,scr);
  if(!dr&&!pull)return;
  SW={dr,pull,x:t.clientX,y:t.clientY,at:e.timeStamp,d:0,on:false,open:S.drawer,w:$('side').offsetWidth||280,lx:t.clientX,lt:e.timeStamp,v:0,id:t.identifier,scr};
},{passive:true});
document.addEventListener('touchmove',e=>{
  if(!SW)return;
  const t=SW.on&&[...e.touches].find(f=>f.identifier===SW.id)||e.touches[0], dx=t.clientX-SW.x, dy=t.clientY-SW.y;
  if(DR&&DR.ready&&DR.hold){if(SW.on)swipeEnd(false);SW=null;return}  // the row is held: it is being dragged
  if(SW.sheet){
    if(!SW.on){if(Math.abs(dy)<10&&Math.abs(dx)<10)return;if(dy<Math.abs(dx)||$('sheet').scrollTop>0){SW=null;return}SW.on=true;SW.base=Math.max(0,grab($('sheet'),'m42',0));$('sheet').classList.add('drag')}
    if(e.timeStamp>SW.lt){SW.v=(t.clientY-SW.ly)/(e.timeStamp-SW.lt);SW.ly=t.clientY;SW.lt=e.timeStamp}
    SW.d=Math.max(0,SW.base+dy);$('sheet').style.transform=`translateY(${SW.d}px)`;return;
  }
  if(!SW.on&&!SW.lvl){if(!e.cancelable||scrolled(SW.scr)){SW=null;return}  // B167: it is a scroll
    if(SW.dr&&SW.open&&HB&&!atAll()&&!oneProject(H.projects)&&swipeTakes(dx,dy,false)==='drag'){SW.lvl=true;if(DR)dragEnd()}  // F150: up a level
    else{const s=swipeTakes(dx,dy,SW.open);if(s==='wait')return;
    if(!s||!SW.dr){if(!SW.pull||!pullTakes(dx,dy)||!atTop(SW.scr)){SW=null;return}pullStart(SW)}
    else{SW.on=true;if(DR)dragEnd();SW.base=Math.max(-SW.w,grab($('side'),'m41',SW.open?0:-SW.w));$('side').classList.add('drag');$('scrim').classList.add('drag','on')}}}
  if(e.cancelable)e.preventDefault();  // B167: no scroll until the finger lifts
  if(SW.pl){pullMove(SW,dy);return}
  SW.d=dx;if(SW.lvl)return;
  if(e.timeStamp>SW.lt){SW.v=(t.clientX-SW.lx)/(e.timeStamp-SW.lt);SW.lx=t.clientX;SW.lt=e.timeStamp}
  const at=SW.px=Math.max(-SW.w,Math.min(0,SW.base+dx));
  $('side').style.transform=`translateX(${at}px)`;$('scrim').style.opacity=String(1+at/SW.w);
},{passive:false});
/* F401: pull to refresh: a touch that starts with all under it at the top and moves mostly down. The spinner follows the
   finger; let go past PULL_AT it does what Refresh does, or springs back. Where that may start: the main view and the sidebar */
const atTop=scr=>scr.every(s=>s[0].scrollTop<=0);
const pullFree=()=>!S.sheet&&!S.obOpen&&$('cview').hidden!==false;
function pullPane(el,scr){
  const p=pullFree()&&atTop(scr)?el.closest('#body,#side'):null;if(!p||PULL)return p;
  PULL=document.createElement('div');PULL.className='pull';PULL.setAttribute('role','status');PULL.innerHTML='<i></i><span></span>';document.body.append(PULL);  // there before it has words, so they are read out
  return p;
}
const pullCSS=at=>({transform:`translate(-50%,${at}px)`,opacity:Math.min(1,at/30)});
const pullSay=t=>{const s=PULL.lastElementChild;if(s.textContent!==t)s.textContent=t};
function pullStart(w){
  w.on=w.pl=true;if(DR)dragEnd();
  const r=w.pull.getBoundingClientRect();PULL.style.left=r.left+r.width/2+'px';PULL.style.top=r.top+'px';
  w.base=Math.max(0,grab(PULL,'m42',0));PULL.classList.remove('go');
}
function pullMove(w,dy){
  w.d=dy;w.px=w.base+pullAt(dy);const ready=dy>=PULL_AT;
  PULL.classList.toggle('ready',ready);pullSay(ready?'Let go to refresh':'');
  Object.assign(PULL.style,pullCSS(w.px));PULL.firstElementChild.style.transform=`rotate(${Math.round(w.px*4)}deg)`;
}
function pullEnd(w,done){
  noClick=true;setTimeout(()=>noClick=false,50);PD.down=false;
  if(done&&w.d>=PULL_AT&&pullFree()&&newsRefresh()){PULL.classList.add('go');pullSay('Refreshing');return}
  PULL.classList.remove('ready');pullSay('');PULL.style.transform=PULL.style.opacity='';
  springRun(PULL,springFrames(w.px,0,0).map(x=>Math.max(0,x)),pullCSS);
}
function swipeEnd(done){
  const w=SW;SW=null;if(w&&w.lvl){noClick=true;setTimeout(()=>noClick=false,50);PD.down=false;if(done&&w.d>48)goUp();return}
  if(!w||!w.on)return;
  if(w.pl){pullEnd(w,done);return}
  const still=performance.now()-w.lt>120, v=still?0:w.v;  // it rested before it was let go
  if(w.sheet){const el=$('sheet'), go=done&&(w.d>80||v>.5&&w.d>10);el.style.transform='';
    if(go)closeSheet();
    if(drawerOn())springRun(el,springFrames(w.d,go?el.offsetHeight*1.03:0,v).map(x=>Math.max(0,x)),x=>({transform:`translateY(${x}px)`}));else el.classList.remove('drag');
    return}
  const side=$('side'), scrim=$('scrim');side.style.transform='';scrim.style.opacity='';
  S.drawer=done?swipeOpens(w.d,v,w.w,w.open):w.open;if(S.drawer&&!w.open)drawerBlur();
  noClick=true;setTimeout(()=>noClick=false,50);PD.down=false;render(true);
  const fs=springFrames(w.px||0,S.drawer?0:-w.w,v).map(x=>Math.max(-w.w,Math.min(0,x)));side._to=S.drawer;
  springRun(side,fs,x=>({transform:`translateX(${x}px)`}));springRun(scrim,fs,x=>({opacity:1+x/w.w}));
}
document.addEventListener('touchend',e=>{if(SW&&SW.on&&!SW.sheet&&[...e.touches].some(f=>f.identifier===SW.id))return;swipeEnd(true)},{passive:true});
document.addEventListener('touchcancel',()=>swipeEnd(false),{passive:true});
