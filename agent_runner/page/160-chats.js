const VV=window.visualViewport, IOS=!!(window.CSS&&CSS.supports('-webkit-touch-callout','none')), KB_MS=900;
let kbH=0;  // .app's height while the keyboard is open, 0 when it is closed
let kbUntil=0, kbLoop=0;  // the keyboard is on its way in or out until then
/* B212a: what iOS tells late, or never. kbAsk asks again while the keyboard is open; kbGone is the height of a keyboard that
   is away, which the viewport still has; kbLeft is when the last field was left; kbPress is true in a press's own events */
const KB_ASK=300;
let kbAsk=0, kbGone=0, kbLeft=0, kbPress=false;
function kbPressed(){kbPress=true;setTimeout(()=>{kbPress=false},0)}
/* a script's focus brings no keyboard, so a viewport still short after KB_MS without a field is out of date */
function kbEnter(e){
  if(kbPress)kbGone=0;
  else if(!kbH&&!typingIn(e.relatedTarget)&&Date.now()-kbLeft>KB_MS)kbGone=kbHeight(VV,document.documentElement.clientHeight,typingIn(e.target));
}
/* B214: and so it is on a touch device whose browser shrinks the page itself: the session keeps its size for as long */
let kbStill=0, kbStillT=0;
for(const t of ['focusin','focusout'])document.addEventListener(t,e=>{if(!TOUCH()||!typingIn(e.target))return;
  kbStill=Date.now()+KB_MS;clearTimeout(kbStillT);kbStillT=setTimeout(()=>{if(FD.shown)feedPlace()},KB_MS+50)});
function kbHeight(vv,full,typing){return vv&&typing&&Math.abs(vv.scale-1)<.02&&full-vv.height>100?Math.round(vv.height):0}
const typingIn=el=>!!(el&&el.matches&&el.matches('textarea,input,select,[contenteditable]'));
function kbFit(){
  const app=$('app'), el=document.activeElement;
  if(kbGone&&Math.abs(VV.height-kbGone)>1)kbGone=0;
  const h=kbGone?0:kbHeight(VV,document.documentElement.clientHeight,typingIn(el));
  const moving=Date.now()<kbUntil&&Math.abs(VV.scale-1)<.02;  // a pan comes before the resize, or outlasts the blur: follow it, at full height
  const pin=chatShown()&&S.pin, changed=h!==kbH;  // before the new height can move the chat
  const was=changed?kbSpot():null;
  if(changed)kbH=h;
  const top=h||moving?Math.max(0,Math.round(VV.offsetTop)):0;
  app.classList.toggle('kb',!!h);
  app.style.height=h?h+'px':'';app.style.top=h||top?top+'px':'';
  if((h||moving)&&window.scrollY)window.scrollTo(0,0);  // Safari scrolls even a locked document to show the box
  if(!changed)return;
  if(h&&!kbAsk)kbAsk=setInterval(kbFit,KB_ASK);
  if(!h){clearInterval(kbAsk);kbAsk=0}
  if(pin)toEnd();
  if(h)kbReveal(el);
  kbGlide(was,pin);feedGlide(was.feed);
}
function kbWatch(){
  kbUntil=Date.now()+KB_MS;
  const step=()=>{kbFit();kbLoop=Date.now()<kbUntil?requestAnimationFrame(step):0};
  if(!kbLoop)kbLoop=requestAnimationFrame(step);
}
/* the message box, the chat's words and the sheet glide to their new place: transforms only, the layout is there at once */
let kbAnims=[], kbUndo=null;
function kbSpot(){
  const dock=document.querySelector('.dockwrap'), was={dock:dock?dock.getBoundingClientRect().top:0,sheet:S.sheet?$('sheet').getBoundingClientRect().bottom:0,feed:feedTop()};
  if(kbUndo)kbUndo();
  was.scroll=$('body').scrollTop;return was;
}
function kbGlide(was,pin){
  if(!document.querySelector('.dockwrap')||document.hidden||matchMedia('(prefers-reduced-motion:reduce)').matches)return;
  const dock=document.querySelector('.dockwrap'), b=$('body'), css=getComputedStyle(document.documentElement);
  const o={duration:parseFloat(css.getPropertyValue('--dur-slow')),easing:css.getPropertyValue('--ease').trim()};
  const go=(el,d)=>{if(Math.abs(d)<1)return;
    const at=`translateY(${d}px)`, a=el.animate([{transform:at},{transform:'none'}],o), clear=()=>{el.style.transform=''};
    el.style.transform=at;requestAnimationFrame(()=>requestAnimationFrame(clear));kbAnims.push(a)};  // iOS draws one frame before the animation
  const moved=was.dock-dock.getBoundingClientRect().top, text=pin?b.scrollTop-was.scroll:0;  // how far each went up
  if(S.sheet)go($('sheet'),was.sheet-$('sheet').getBoundingClientRect().bottom);
  if(text>0){b.style.marginTop=-text+'px';toEnd()}  // under the header for now, so the lines that leave are still drawn
  go(b,text);go(dock,moved);
  if(!kbAnims.length)return;
  kbUndo=()=>{kbUndo=null;for(const a of kbAnims){a.onfinish=null;a.cancel()}kbAnims=[];b.style.marginTop='';if(chatShown()&&S.pin)toEnd()};
  kbAnims[0].onfinish=kbUndo;
}
/* iOS decides to pan when a tap focuses a box under where the keyboard comes. So the tap's focus is made here, with no
   scroll, and the box see-through for two frames: WebKit does not pan to show a box that is not visible. */
const KB_BOX='textarea,input:not([type]),input[type=text],input[type=search],input[type=number],input[type=password],input[type=url],input[type=email]';
let KT=null;  // the touch that may be a tap on a box
function kbTapStart(e){
  const t=e.touches.length===1?e.touches[0]:null, el=t&&e.target.closest&&e.target.closest(KB_BOX);
  KT=el&&!(kbH&&el===document.activeElement)&&!el.disabled&&!el.readOnly&&Math.abs(VV.scale-1)<.02?{el,x:t.clientX,y:t.clientY,at:Date.now()}:null;
}
function kbTapEnd(e){
  const k=KT, t=e.changedTouches[0];KT=null;kbPressed();
  if(!k||!e.cancelable||e.defaultPrevented||!k.el.isConnected||Date.now()-k.at>450||Math.abs(t.clientX-k.x)>9||Math.abs(t.clientY-k.y)>9)return;  // a scroll, a swipe or a long press
  e.preventDefault();
  if(k.el===document.activeElement)k.el.blur();  // a script's focus (open()) brought no keyboard: only a new focus does
  kbFocus(k.el);
  k.el.click();  // the click that preventDefault took away
}
function kbFocus(el){
  if(!IOS)return el.focus({preventScroll:true});
  el.style.opacity='0';
  try{const n=el.value.length;el.setSelectionRange(n,n)}catch(x){}  // a number box has no selection
  el.focus({preventScroll:true});
  requestAnimationFrame(()=>requestAnimationFrame(()=>{el.style.opacity=''}));
}
/* the field being typed in, inside its own scroller (never scrollIntoView: that pans the page too).
   At once, as while typing; F189a: it glides when a press asked for it (press), or when that glide is under way */
function kbReveal(el,press){
  const b=el&&el.closest&&el.closest('.sheet,.side,.body');if(!b)return;
  const r=el.getBoundingClientRect(), v=b.getBoundingClientRect();
  const d=r.bottom>v.bottom-8?Math.min(r.bottom-v.bottom+8,r.top-v.top-8):r.top<v.top+8?r.top-v.top-8:0;if(!d)return;
  if(press||MO.scroll.has(b))scrollGlide(b,b.scrollTop+d);else b.scrollTop+=d;
}
if(VV){for(const t of ['resize','scroll'])VV.addEventListener(t,kbFit);
  document.addEventListener('focusin',e=>{if(IOS)kbEnter(e);if(IOS&&typingIn(e.target))kbWatch();kbFit();if(kbH)kbReveal(e.target)});
  /* left for no other field: the full height at once, not when the viewport says so. After the microtask: a refresh that
     drew the box again has put the focus back by then */
  document.addEventListener('focusout',e=>{if(typingIn(e.target)&&!typingIn(e.relatedTarget))kbLeft=Date.now();if(kbH&&!typingIn(e.relatedTarget))queueMicrotask(()=>{if(typingIn(document.activeElement))return;if(IOS)kbWatch();kbFit()})});
  if(IOS){for(const t of ['pointerup','mousedown','click'])document.addEventListener(t,kbPressed,true);
    document.addEventListener('input',e=>{if(kbGone&&e.isTrusted){kbGone=0;kbFit()}});  // typed: there is a keyboard after all
    /* another app puts the keyboard away, can leave the box in focus, and no event may say so: the focus goes with it */
    document.addEventListener('visibilitychange',()=>{if(document.hidden&&kbH)document.activeElement.blur()});
    document.addEventListener('touchstart',kbTapStart,{passive:true});document.addEventListener('touchcancel',()=>{KT=null},{passive:true});
    document.addEventListener('touchend',kbTapEnd,{passive:false})}}
let boxWas={k:'',h:0};
function grow(ta,drawn){
  sendDraw(ta);
  const k=boxKey(), was=boxWas.k===k?boxWas.h:0;
  ta.closest('.box')?.classList.toggle('has',!!ta.value.trim());ta.style.height='auto';ta.style.height=Math.min(ta.scrollHeight,160)+'px';
  const h=ta.offsetHeight||0;boxWas={k,h};if(was&&h&&was!==h)growGlide(ta,h-was,drawn);
}
/* B208: Send is Force send while the open session works and there is something to send; changed in place, so nothing is
   drawn again under a caret. box() draws it plain, and grow() runs after every draw and every change of the words. */
function sendDraw(ta){
  const b=ta.closest('.box')?.querySelector('[data-send]');if(!b)return;
  const n=S.thread, on=!!n&&!isNew(n)&&sendForces(sessWorks(n),ta.value,S.atts[boxKey()]), say=on?'Force send':'Send';
  b.classList.toggle('force',on);b.setAttribute('aria-label',say);b.title=say;
}
/* F147: a box that grew by d: at the foot of the view it slides up into its new height (and the chat with it), on Home what is under its words slides down */
function growGlide(ta,d,drawn){
  const dock=ta.closest('.dock'), box=ta.closest('.box'), go=(el,y)=>glideTo(el,0,y+(MO.fly.has(el)?shiftOf(el).m42:0),FD.shown?{ease:'--ease',dur:'--dur-slow'}:{ease:'--spring-soft'});
  const was=dock?feedTop():null, from=dock&&MO.fly.has(dock)?shiftOf(dock).m42:0;if(was!=null)feedPlace();
  if(!box||!box.animate||calm())return;
  if(was!=null)feedGrow(was-feedTop()+from);
  if(dock){for(const el of FD.shown?[dock]:dock.children)go(el,d);const b=$('body'), c=!drawn&&chatShown()&&S.pin&&b.firstElementChild;if(c){const at=b.scrollTop;toEnd();go(c,b.scrollTop-at)}return}  // in a redraw glide() moves the chat
  for(let el=ta.closest('.inrow').nextElementSibling;el;el=el.nextElementSibling)go(el,-d);
  for(let el=box.nextElementSibling;el;el=el.nextElementSibling)if(el.getBoundingClientRect().top<innerHeight)go(el,-d);
}
/* B119: the slash command menu. SL.cmds the session's commands from /commands (null until they come, then
   SLASH_FALLBACK's list stands in), SL.items the rows shown, SL.i the highlighted one */
const SL={cmds:null,items:[],i:0,at:0,of:''};
function slashLoad(of){SL.of=of;SL.at=Date.now();fetch(tq(of?'commands?s='+encodeURIComponent(of):'commands')).then(r=>r.json()).then(j=>{if(SL.of===of&&Array.isArray(j)&&j.length){SL.cmds=j;const ta=document.querySelector('[data-in]');if(ta&&document.activeElement===ta)slashShow(ta)}}).catch(()=>{})}
slashLoad('');
function slashShow(ta,press){
  const of=/^[cs]\d+$/.test(S.thread||'')?S.thread:'';  // F170: the open chat's own commands, again after a while
  if(ta&&ta.value[0]==='/'&&(of!==SL.of||Date.now()-SL.at>60000))slashLoad(of);
  const m=document.querySelector('[data-slash]');if(!m)return;
  SL.items=ta?slashMatches(SL.cmds,ta.value):[];if(SL.i>=SL.items.length)SL.i=0;
  m.hidden=!SL.items.length;
  m.innerHTML=SL.items.map((c,j)=>`<button type="button" role="option" class="${j===SL.i?'on':''}" aria-selected="${j===SL.i}" data-slashpick="${j}"><b>/${esc(c.name)}</b><span>${esc(c.desc||'')}</span></button>`).join('');
  const on=m.querySelector('.on');if(!on||!on.scrollIntoView)return;
  if(!press&&!MO.scroll.has(m)){on.scrollIntoView({block:'nearest'});return}
  const r=on.getBoundingClientRect(), v=m.getBoundingClientRect(), d=r.bottom>v.bottom?r.bottom-v.bottom:r.top<v.top?r.top-v.top:0;  // F189a: an arrow key; a redraw under its glide leaves it to go on
  if(d)scrollGlide(m,m.scrollTop+d);else if(press)scrollStop(m);
}
/* B188: Enter picks the highlighted command, unless it is typed in full already */
const slashPicks=ta=>{const c=SL.items[SL.i];return !!c&&ta.value.trim()!=='/'+c.name};
const slashOpen=()=>{const m=document.querySelector('[data-slash]');return !!(m&&!m.hidden&&SL.items.length)};
function slashClose(){SL.items=[];SL.i=0;const m=document.querySelector('[data-slash]');if(m){m.hidden=true;m.innerHTML=''}}
function slashTake(j){
  const ta=document.querySelector('[data-in]'), c=SL.items[j];if(!ta||!c)return;
  ta.value=slashPick(c);store.set(DRAFT_KEY(boxKey()),ta.value);slashClose();grow(ta);ta.focus({preventScroll:true});ta.setSelectionRange(ta.value.length,ta.value.length);
}

