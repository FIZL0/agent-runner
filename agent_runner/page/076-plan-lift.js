/* F429d: a finger moves a Plan queue row: held still for LIFT_MS the row lifts, and then the finger drags it as a mouse
   drags its grip (GR.d, gripDraw, gripEnd). Moved before that it is a scroll or a swipe, and never lifts. Not from the opened
   row's details (its words are selected by a hold) nor another control (a hold shows its Hint). LF.now: the touch, to its end
   {id,tid: the row,el,x,y: where it went down,at: where it is now,scr,wait: the timer,on: it lifted,d: its drag} */
const LF={now:null}, LIFT_MS=350, LIFT_PX=8;
/* the row a finger may lift from here: one with a grip */
function liftRow(el){
  if(!el||!el.closest||el.closest('.foldin'))return '';
  const own=el.closest('button,a,input,textarea,select');if(own&&!own.classList.contains('fold')&&!own.classList.contains('grip'))return '';
  const card=el.closest('.card'), g=card&&[...card.children].find(c=>c.dataset&&c.dataset.grip);
  return g?g.dataset.grip:'';
}
const liftMay=id=>GR.rows.some(q=>menuId(q)===id&&gripOn(q));
/* a redraw may take the touched element away, and its events then reach only itself */
const liftEars=(el,f)=>{el[f]('touchmove',liftMove,{passive:false});el[f]('touchend',liftEnd,{passive:false});el[f]('touchcancel',liftEnd,{passive:true})};
function liftOff(){const l=LF.now;LF.now=null;if(l){clearTimeout(l.wait);liftEars(l.el,'removeEventListener')}}
const liftDrop=(l,drop)=>{if(GR.d&&GR.d===l.d)gripEnd(drop)};
function liftUp(l){
  if(LF.now!==l||l.on)return;
  const card=gripCard(l.tid);
  if(!card||!liftMay(l.tid)||GR.d||S.sheet||SW&&SW.on||scrolled(l.scr))return liftOff();
  l.on=true;SW=null;HINT.down=null;  // this touch is the row's: no drawer swipe, no pull, no Hint
  GR.d=l.d={id:l.tid,pid:null,y0:l.at,y:l.at,grab:l.at-card.getBoundingClientRect().top,on:true,g:0,sc:$('body').scrollTop};
  gripDraw();requestAnimationFrame(gripTick);
}
function liftMove(e){
  const l=LF.now;if(!l)return;
  const t=[...e.touches].find(f=>f.identifier===l.id);
  if(!l.on){
    if(!t||e.touches.length>1||!e.cancelable||Math.hypot(t.clientX-l.x,t.clientY-l.y)>=LIFT_PX)return liftOff();
    l.at=t.clientY;return;
  }
  if(e.cancelable)e.preventDefault();  // no scroll until the finger lifts, also once the drag is over
  if(t&&GR.d&&GR.d===l.d){l.d.y=t.clientY;gripDraw()}
}
function liftEnd(e){
  const l=LF.now;if(!l)return;
  if(!l.on)return liftOff();
  if(e.cancelable)e.preventDefault();  // no click: a lift opens nothing
  if([...e.touches].some(f=>f.identifier===l.id))return;
  liftDrop(l,e.type==='touchend');
  if(!e.touches.length)liftOff();
}
document.addEventListener('touchstart',e=>{
  const l=LF.now;
  if(l&&l.on&&e.touches.length>1)return liftDrop(l);  // a second finger puts the row back
  if(l){liftDrop(l);liftOff()}
  if(e.touches.length!==1||GR.d||S.sheet)return;
  const t=e.touches[0], tid=liftRow(e.target);if(!tid||!liftMay(tid))return;
  const n=LF.now={id:t.identifier,tid,el:e.target,x:t.clientX,y:t.clientY,at:t.clientY,scr:scrollers(e.target),on:false,d:null};
  n.wait=setTimeout(()=>liftUp(n),LIFT_MS);liftEars(n.el,'addEventListener');
},{passive:true});
document.addEventListener('touchmove',liftMove,{passive:false});
document.addEventListener('touchend',liftEnd,{passive:false});
document.addEventListener('touchcancel',liftEnd,{passive:true});
/* the browser's long press would open its menu, or let the held redraws in, and end the touch */
window.addEventListener('contextmenu',e=>{if(LF.now){e.preventDefault();e.stopImmediatePropagation()}},true);
