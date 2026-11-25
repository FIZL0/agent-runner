/* F429c: the grip of a Plan queue row (a task, a release, the Next release row): a mouse drags the row to its place, arrow
   up and down move it one place. No grip on a row with nothing to move it ('menu_top' of its menu). GR.did: what was moved,
   drawn at once and until the snapshot has it ({id,cid,at,ms,down: the rows below it, seen: the row menu's presses before
   it}); GR.rows: the rows last drawn; GR.d: the drag under way */
const GR={did:[],rows:[],d:null}, GRIP_PX=4, GRIP_EDGE=56;
const gripOn=q=>!q.removed&&(q.menu||[]).includes('menu_top');
const gripReal=q=>!q.placeholder&&!q.removed;  // a row the plan can name
/* as plan.child(): a task's subtasks move with it */
const gripChild=(id,t)=>t.length>id.length&&t.startsWith(id)&&/\d/.test(t[id.length])!==/\d/.test(id[id.length-1]);
const gripBlock=(rows,id)=>{const own=rows.filter(q=>menuId(q)===id);return own.length&&!own[0].placeholder?own.concat(rows.filter(q=>gripReal(q)&&gripChild(id,q.id))):own};
/* the rows with row `id` (its subtasks after it) at place `g` among the others */
function gripPut(rows,id,g){
  const block=gripBlock(rows,id), rest=rows.filter(q=>!block.includes(q));
  return rest.slice(0,g).concat(block,rest.slice(g));
}
/* does that change anything the plan knows: the order of the rows it can name, and of `id` */
const gripOrder=(rows,id)=>rows.filter(q=>gripReal(q)||menuId(q)===id).map(menuId).join(' ');
const gripNew=(rows,id,g)=>gripOrder(gripPut(rows,id,g),id)!==gripOrder(rows,id);
function gripRows(rows){
  GR.did=GR.did.filter(menuLive);
  let out=rows;
  for(const d of GR.did){
    if(PM.did.some(x=>x.id===d.id&&x.k==='menu_top'&&!d.seen.includes(x)))continue;  // pressed since
    const block=gripBlock(out,d.id), rest=out.filter(q=>!block.includes(q));if(!block.length)continue;
    const down=d.down.filter(t=>!PM.did.some(x=>x.id===t&&x.k==='menu_top'&&!d.seen.includes(x)));
    const g=down.map(t=>rest.findIndex(q=>menuId(q)===t)).find(n=>n>=0);
    out=gripPut(out,d.id,g===undefined?rest.length:g);
  }
  return GR.rows=PM.rows=out;
}
const rowGrip=(q,list='queue')=>list==='queue'&&gripOn(q)?`<button class="grip" data-grip="${esc(menuId(q))}" aria-label="Move ${esc(menuName(menuId(q)))}: drag, or arrow up and down">${I.grip}</button>`:'';
/* row `id` to place `g` among the others: true when that moves it */
function gripMove(id,g){
  const rows=GR.rows, q=rows.find(x=>menuId(x)===id);
  if(!q||!gripOn(q)||!gripNew(rows,id,g)||q.placeholder&&GR.did.some(d=>d.id===id))return false;  // moved once, it is a release of its own
  const block=gripBlock(rows,id), rest=rows.filter(x=>!block.includes(x));
  const above=rest.slice(0,g).reverse().find(gripReal), below=rest.slice(g).find(gripReal), by=above||below;
  if(!by)return false;
  PM.did=PM.did.filter(x=>x.id!==id||x.k!=='menu_top');
  const d={id,cid:'',at:Date.now(),ms:PM_MS,down:rest.slice(g).map(menuId),seen:PM.did.slice()};
  GR.did=GR.did.filter(x=>x.id!==id).concat([d]);
  d.cid=outbox('move',{tid:id,where:above?'after':'before',other:by.id},{grip:id,say:`Move ${menuName(id)} ${above?'after':'before'} ${by.id}`}).cid;
  return true;
}
/* an arrow: one place, past the rows the plan cannot name too */
function gripStep(id,by){
  const rows=GR.rows, block=gripBlock(rows,id), rest=rows.filter(q=>!block.includes(q)), at=rows.indexOf(block[0]);if(at<0)return;
  for(let g=rest.filter(q=>rows.indexOf(q)<at).length+by;g>=0&&g<=rest.length;g+=by)
    if(gripNew(rows,id,g)){if(gripMove(id,g)){render(true);gripFocus(id);gripSee(id)}return}
}
const gripFocus=id=>{const b=[...$('body').querySelectorAll('[data-grip]')].find(x=>x.dataset.grip===id);if(b&&b!==document.activeElement)b.focus({preventScroll:true})};
const gripCard=id=>[...$('body').querySelectorAll('[data-k]')].find(x=>x.dataset.k===(id===NEXT_ROW?'rel:next':'task:'+id));
/* a row moved by a key stays in view */
function gripSee(id){
  const b=$('body'), el=gripCard(id);if(!el||!el.getBoundingClientRect)return;
  const e=b.getBoundingClientRect(), r=el.getBoundingClientRect(), y=r.top-flying(el), bar=b.querySelector('.planq'), top=e.top+(bar?bar.offsetHeight:0)+8;
  const d=y<top?y-top:Math.max(0,Math.min(y+r.height+8-e.bottom,y-top));
  if(d)scrollGlide(b,b.scrollTop+d);
}
/* over a redraw: call before, then call what it returns */
function gripKeep(el){
  const a=document.activeElement, id=a&&a!==el&&el.contains(a)&&a.dataset&&a.dataset.grip;
  return()=>{if(id)gripFocus(id)};
}
/* the drag: the row goes with the mouse, the others make room; a redraw midway drew other cards, which go on from there */
function gripDraw(){
  const d=GR.d, b=$('body'), card=d&&gripCard(d.id), col=card&&card.parentElement;
  if(!card||!GR.rows.some(q=>menuId(q)===d.id&&gripOn(q)))return gripEnd();
  d.card=card;const a=MO.fly.get(card);if(a)a.cancel();
  const gap=parseFloat(getComputedStyle(col).rowGap)||0, c0=col.getBoundingClientRect().top, H=card.offsetHeight+gap;
  const at=c=>c.offsetParent===col?c.offsetTop+col.clientTop:c.offsetTop-col.offsetTop;  // where it is laid out
  const here=at(card), top=d.y-d.grab-c0, low=top+card.offsetHeight, block=gripBlock(GR.rows,d.id);
  const rest=GR.rows.filter(q=>!block.includes(q)).map(q=>gripCard(menuId(q)));
  const past=rest.map(c=>{if(!c)return false;const m=at(c)+c.offsetHeight/2;return at(c)<here?top>=m:low>m});
  d.g=past.filter(Boolean).length;
  rest.forEach((c,i)=>{if(c){const y=at(c)<here&&!past[i]?H:at(c)>here&&past[i]?-H:0;c.style.transform=y?`translateY(${y}px)`:''}});
  b.classList.add('gripping');card.classList.add('gripped');card.style.transform=`translateY(${top-here}px)`;
}
/* near an edge of the view the list scrolls on; a wheel may have scrolled it too */
function gripTick(){
  const d=GR.d;if(!d||!d.on)return;
  const b=$('body'), e=b.getBoundingClientRect(), near=x=>Math.max(0,Math.min(1,(GRIP_EDGE-x)/GRIP_EDGE));
  b.scrollTop+=Math.round(14*(near(e.bottom-d.y)-near(d.y-e.top)));
  if(b.scrollTop!==d.sc||!d.card.isConnected){d.sc=b.scrollTop;gripDraw()}
  requestAnimationFrame(gripTick);
}
function gripEnd(drop){
  const d=GR.d, b=$('body');if(!d)return;
  GR.d=null;if(!d.on)return;
  noClick=true;setTimeout(()=>noClick=false,0);  // the click that ends a drag opens nothing
  const moved=drop&&gripMove(d.id,d.g);  // drawn from where each is seen
  b.classList.remove('gripping');
  for(const c of b.querySelectorAll('.card')){
    if(!c.style.transform&&!c.classList.contains('gripped'))continue;
    const y=shiftOf(c).m42;c.classList.remove('gripped');c.style.transform='';if(!moved&&y)glideTo(c,0,y)}
  if(!moved)render();
  gripFocus(d.id);
}
document.addEventListener('pointerdown',e=>{
  const g=e.pointerType==='mouse'&&!e.button&&e.target.closest&&e.target.closest('[data-grip]');
  if(!g||GR.d)return;
  const card=gripCard(g.dataset.grip);if(!card)return;
  g.focus({preventScroll:true});
  GR.d={id:g.dataset.grip,pid:e.pointerId,y0:e.clientY,y:e.clientY,grab:e.clientY-card.getBoundingClientRect().top,on:false,g:0,sc:$('body').scrollTop};
});
document.addEventListener('mousedown',e=>{if(e.target.closest&&e.target.closest('[data-grip]'))e.preventDefault()});  // selects no words
document.addEventListener('pointermove',e=>{
  const d=GR.d;if(!d||e.pointerId!==d.pid)return;
  if(!(e.buttons&1))return gripEnd();  // let go outside the window
  d.y=e.clientY;
  if(!d.on){if(Math.abs(d.y-d.y0)<GRIP_PX)return;d.on=true;gripDraw();requestAnimationFrame(gripTick);return}
  gripDraw();
});
document.addEventListener('pointerup',e=>{if(GR.d&&e.pointerId===GR.d.pid)gripEnd(true)});
document.addEventListener('pointercancel',e=>{if(GR.d&&e.pointerId===GR.d.pid)gripEnd()});
window.addEventListener('blur',e=>{if(e.target===window)gripEnd()});
window.addEventListener('keydown',e=>{
  if(e.key==='Escape'&&GR.d){e.preventDefault();e.stopImmediatePropagation();gripEnd();return}
  const g=(e.key==='ArrowUp'||e.key==='ArrowDown')&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&!e.shiftKey&&e.target.closest&&e.target.closest('[data-grip]');
  if(g){e.preventDefault();e.stopImmediatePropagation();if(!GR.d)gripStep(g.dataset.grip,e.key==='ArrowUp'?-1:1)}
},true);
I.grip=ic('<path d="M9 5h.01M15 5h.01M9 12h.01M15 12h.01M9 19h.01M15 19h.01"/>');
