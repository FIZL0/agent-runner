/* F133, F201: drag a pinned chat's row to set its place among the pins, by pointer events so a phone's touch works too: a mouse drags at once,
   a touch after a short hold (a swipe before it still scrolls the list); the drop is kept by the run */
/* F507: any chat's row drags, into Quiet and back out; a row of the bulk select carries the whole selection along */
const dragEnd=()=>{if(!DR)return;const {row,on}=DR, y=on?shiftOf(row).m42:0;clearTimeout(DR.hold);row.classList.remove('lift','drag');
  for(const r of DR.with||[])r.classList.remove('drag');if(DR.line)DR.line.remove();row.style.transform='';DR=null;if(y)glideTo(row,0,y);if(on)render(true)};
document.addEventListener('pointerdown',e=>{
  const row=e.target.closest&&e.target.closest('.crow[data-crow]');
  if(!row||e.button>0||S.ren||e.target.closest('.pin,.del,.rowmenu,.rowacts')||S.undo||e.shiftKey||e.ctrlKey||e.metaKey)return;
  dragEnd();
  DR={row,name:row.dataset.crow,id:e.pointerId,y0:e.clientY,on:false,ready:e.pointerType==='mouse'};
  if(!DR.ready)DR.hold=setTimeout(()=>{if(DR&&DR.row===row){DR.ready=true;row.classList.add('lift')}},350);
});
document.addEventListener('pointermove',e=>{
  if(!DR||e.pointerId!==DR.id)return;
  const dy=e.clientY-DR.y0;
  if(!DR.on){
    if(Math.abs(dy)<6)return;
    if(!DR.ready){dragEnd();return}  // a touch that moves before the hold is a scroll
    DR.on=true;DR.row.classList.add('drag');
    if(S.sel.length>1&&S.sel.includes(DR.name)){DR.names=S.sel.slice();DR.with=[...document.querySelectorAll('.crow[data-crow]')].filter(r=>r!==DR.row&&DR.names.includes(r.dataset.crow));for(const r of DR.with)r.classList.add('drag')}
    if(!document.querySelector('#sidein .qline')){const rs=document.querySelectorAll('#sidein .crow'), l=rs[rs.length-1];  // no Quiet yet: its line, to drop on
      if(l){DR.line=document.createElement('div');DR.line.className='qline drop';DR.line.textContent='Quiet';l.after(DR.line)}}
    try{DR.row.setPointerCapture(e.pointerId)}catch(err){}
  }
  DR.row.style.transform=`translateY(${dy}px)`;e.preventDefault();
});
document.addEventListener('touchmove',e=>{if(DR&&DR.ready)e.preventDefault()},{passive:false});  // held: no scroll
document.addEventListener('pointerup',e=>{
  if(!DR||e.pointerId!==DR.id)return;
  if(!DR.on)return dragEnd();
  const name=DR.name, others=[...document.querySelectorAll('.crow.pinned[data-crow]')].filter(r=>r!==DR.row);
  const to=others.filter(r=>{const b=r.getBoundingClientRect();return b.top+b.height/2<e.clientY}).length;
  const ql=document.querySelector('#sidein .qline'), low=!!ql&&ql.getBoundingClientRect().top<e.clientY, carried=DR.names||[name], pinned=DR.row.classList.contains('pinned');
  dragEnd();
  noClick=true;setTimeout(()=>noClick=false,0);  // the click that ends a drag opens nothing
  if(saveQuiet(carried,low?'quiet':'top')||!pinned||low)return;
  const names=chatNames(),pins=chatPins().filter(m=>names.includes(m)),moved=chatMove(pins,name,to);
  if(moved.join()!==pins.join())savePins(moved);
});
document.addEventListener('pointercancel',e=>{if(DR&&e.pointerId===DR.id)dragEnd()});
document.addEventListener('contextmenu',e=>{if(DR&&DR.ready&&e.target.closest&&e.target.closest('.crow'))e.preventDefault()});
let noClick=false;
document.addEventListener('click',e=>{if(noClick){noClick=false;e.preventDefault();e.stopPropagation();return}rowTap(e)},true);
/* F83: a press under way holds the refreshes back, so what it lands on is still there when it ends */
document.addEventListener('pointerdown',e=>{PD.down=!(e.button>0);PD.row=PD.down&&e.target.closest&&e.target.closest('.crow,.renform')?Date.now():0},true);
for(const t of ['contextmenu','blur','visibilitychange'])addEventListener(t,e=>{PD.down=false;if(t==='contextmenu'?!TOUCH():e.target===window||e.target===document)PD.row=0},true);  // F201: a finger held on a row is still on it, and so is a press that takes the focus from a box
for(const t of ['blur','focus','pagehide'])addEventListener(t,()=>{if(TK.ear)micLog('window '+t)});  // B162: a permission question, another app
for(const t of ['pointerup','pointercancel'])document.addEventListener(t,()=>{PD.down=false;PD.row=0;if(PD.late)setTimeout(()=>{if(!PD.down)render()},60)},true);
document.addEventListener('selectionchange',()=>{if(PD.late&&!PD.down&&!selecting())render()});
/* B162: the mic report's pointer events: those on the mic, a new report from a press while nothing listens */
for(const t of ['pointerdown','pointerup','pointercancel','gotpointercapture','lostpointercapture','touchend','touchcancel','contextmenu'])document.addEventListener(t,e=>{
  if(!(e.target&&e.target.closest&&e.target.closest('[data-mic]'))&&!(TK.hold&&e.pointerId!=null&&e.pointerId===TK.holdId))return;
  micLog([t,e.pointerType,e.pointerId==null?'':'id '+e.pointerId,document.hidden?'page hidden':''].filter(Boolean).join(' '),t==='pointerdown'&&!TK.ear);
},{capture:true,passive:true});
document.addEventListener('visibilitychange',()=>{if(TK.ear)micLog(document.hidden?'page hidden':'page shown');
  if(document.hidden)letGo('page hidden');soundSeen(document.hidden);if(!document.hidden)talkNext()});  // B174
/* F124: hold to talk: the mic listens while it is held, silence or not (hear), and sends when it is let go */
document.addEventListener('pointerdown',e=>{
  if(!(e.target.closest&&e.target.closest('[data-mic]'))||TS.mic!=='hold'||e.button>0)return;
  TK.hold=true;TK.holdId=e.pointerId;
  try{e.target.closest('[data-mic]').setPointerCapture(e.pointerId)}catch(err){}  // B162: a finger that drifts off it still holds it
  if(TK.state!=='listening')listen();  // auto listen is on already: letting go sends it
  else if(TK.ear&&TK.ear.stopped)TK.ear.more=true;  // B162: held again before the last one ended: it goes on after that end
});
/* B162: a pointercancel (iOS took the touch) does not end the hold: the finger is still down. Its touchend does, and
   after a touchcancel the mic stops by itself at a silence, or at the next hold's end */
const letGo=by=>{if(TK.hold){TK.hold=false;TK.upAt=Date.now();micStop(by);if(by!=='page hidden')unlockAudio();talkNext()}};
document.addEventListener('pointerup',e=>{if(e.pointerId===TK.holdId)letGo('pointerup')});
const onMic=e=>e.target.closest&&e.target.closest('[data-mic]');  // a touch event's target is where that finger went down
document.addEventListener('pointercancel',e=>{if(e.pointerId===TK.holdId&&e.pointerType!=='touch')holdLost()});  // a pen or mouse has no touchend
document.addEventListener('touchend',e=>{if(onMic(e)&&!(e.targetTouches&&e.targetTouches.length))letGo('touchend')},{passive:true});
/* B166: Hold's release is a tap that lets the page play sound; which of its events the browser takes for one differs, so
   each tries until one played. Not in Tap: its touchend comes before the mic's start (B132) */
for(const t of ['touchend','click'])document.addEventListener(t,e=>{if(TS.mic==='hold'&&!TK.hold&&onMic(e))unlockAudio()},{passive:true});
document.addEventListener('touchcancel',e=>{if(onMic(e))holdLost()},{passive:true});
document.addEventListener('contextmenu',e=>{if(e.target.closest&&e.target.closest('[data-mic]'))e.preventDefault()});
