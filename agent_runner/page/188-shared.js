/* F195b: an icon-only control says what it does while it is hovered (a mouse) or held (a finger or pen): one bubble, with
   its aria-label, for every one on the page. A hold that showed it presses nothing. The mic in Hold has a hold of its own */
const HINT={el:null,wait:0,off:0,title:null,down:null,eat:false,ms:500,over:400,after:1200};
const hintWords=el=>iconWords(el.getAttribute('aria-label'),el.getAttribute('title'),el.textContent,!!el.querySelector('svg'));
function hintAt(e){
  const el=e.target&&e.target.closest&&e.target.closest('button,a[href],[role=button]');
  return el&&!el.querySelector('img')&&hintWords(el)?el:null;
}
function hintHide(){
  clearTimeout(HINT.wait);clearTimeout(HINT.off);
  const el=HINT.el;HINT.el=null;
  if(el&&HINT.title!==null&&!el.hasAttribute('title'))el.setAttribute('title',HINT.title);
  HINT.title=null;
  const b=document.getElementById('hint');if(b)b.hidden=true;
}
/* the browser's own tooltip would say it twice */
function hintOwn(el){if(HINT.el!==el){hintHide();HINT.el=el}
  if(el.hasAttribute('title')&&el.hasAttribute('aria-label')){HINT.title=el.getAttribute('title');el.removeAttribute('title')}}
function hintShow(el){
  if(!el.isConnected)return hintHide();
  let b=document.getElementById('hint');
  if(!b){b=document.createElement('div');b.id='hint';b.className='hint';b.setAttribute('aria-hidden','true');document.body.appendChild(b)}
  b.textContent=hintWords(el);b.hidden=false;b.style.left=b.style.top='0';
  const at=hintSpot(el.getBoundingClientRect(),b.offsetWidth,b.offsetHeight,innerWidth,innerHeight);
  b.style.left=at.left+'px';b.style.top=at.top+'px';
}
document.addEventListener('pointerover',e=>{
  if(e.pointerType!=='mouse')return;
  const el=hintAt(e);
  if(el===HINT.el)return;
  hintHide();
  if(el){hintOwn(el);HINT.wait=setTimeout(()=>hintShow(el),HINT.over)}
});
addEventListener('pointerdown',e=>{
  HINT.eat=false;HINT.down=null;
  if(e.pointerType==='mouse')return;
  hintHide();
  const el=hintAt(e);
  if(!el||!e.isPrimary||el.closest('[data-mic]')&&TS.mic==='hold')return;
  HINT.down={el,id:e.pointerId,x:e.clientX,y:e.clientY};
  HINT.wait=setTimeout(hintHeld,HINT.ms);
},true);
function hintHeld(){const d=HINT.down;if(!d||HINT.eat)return;clearTimeout(HINT.wait);HINT.eat=true;hintOwn(d.el);hintShow(d.el)}
addEventListener('pointermove',e=>{const d=HINT.down;
  if(d&&e.pointerId===d.id&&!HINT.eat&&Math.hypot(e.clientX-d.x,e.clientY-d.y)>9){HINT.down=null;clearTimeout(HINT.wait)}  // a scroll, a swipe
  else if(e.pointerType==='mouse'&&HINT.el&&!HINT.el.isConnected)hintHide();
},{capture:true,passive:true});
function hintUp(e){const d=HINT.down;if(!d||e.pointerId!==d.id)return;
  HINT.down=null;clearTimeout(HINT.wait);
  if(HINT.eat){HINT.off=setTimeout(hintHide,HINT.after);setTimeout(()=>HINT.eat=false,400)}}
for(const t of ['pointerup','pointercancel'])addEventListener(t,hintUp,true);
/* a finger held on a link or a picture would open the browser's menu and end the touch */
addEventListener('contextmenu',e=>{if(HINT.down&&HINT.down.el.contains(e.target)){e.preventDefault();hintHeld()}},true);
addEventListener('click',e=>{if(HINT.eat){HINT.eat=false;e.preventDefault();e.stopImmediatePropagation();return}hintHide()},true);
/* some controls act at the touch's end, with no click (the jump to a session's end) */
addEventListener('touchend',e=>{if(HINT.eat&&hintAt(e)){if(e.cancelable)e.preventDefault();e.target.closest('#pastjump')&&e.stopPropagation()}},{capture:true,passive:false});
for(const t of ['scroll','keydown','blur'])addEventListener(t,e=>{if(t!=='blur'||e.target===window)hintHide()},{capture:true,passive:true});
