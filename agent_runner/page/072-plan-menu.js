/* F429b: the menu on a Plan queue row (a task, a release, the Next release row): three dots beside the row's head, whose
   icons slide in on the row: hold (play while it is held), to the top, remove with Undo. One row's is open at a time; a tap
   elsewhere and Esc close it. S.planMenu: the open one's id. PM.did: what was pressed, drawn at once and until the snapshot
   has it ({id,k,cid,at,ms}); a removed row's has its row, its place and, after Undo, `back`. PM.rows: the rows last drawn */
const PM={did:[],rows:[],at:0,gone:0}, PM_MS=8000, PM_UNDO=20000, PM_AGAIN=500;
const MENU_ICON={menu_hold:'pause',menu_unhold:'play',menu_top:'top',menu_remove:'trash'}, NEXT_ROW='next-release';
const menuId=q=>q.id||NEXT_ROW, menuName=id=>id===NEXT_ROW?'Next release':id;
function menuLive(d){
  const now=Date.now(), x=S.ob.find(y=>y.cid===d.cid);
  if(x&&x.state==='failed')return false;  // the row is as it was; the failure's card has Retry
  if(x)d.at=now;
  return now-d.at<d.ms;
}
/* the Queue's rows with what was pressed */
function menuRows(rows){
  PM.did=PM.did.filter(menuLive);
  let out=rows.slice();
  const put=(r,d)=>{const i=d.down.map(t=>out.findIndex(q=>menuId(q)===t)).find(n=>n>=0);out.splice(i===undefined?out.length:i,0,r)};
  for(const d of PM.did){
    const i=out.findIndex(q=>menuId(q)===d.id), q=out[i];
    if(d.k==='menu_remove'){
      if(d.back){if(!q)put({...d.q,menu:[]},d);continue}
      if(q)out.splice(i,1);
      put({...d.q,removed:true},d);
    }else if(!q)continue;
    else if(d.k==='menu_top'){out.splice(i,1);out.unshift(q)}
    else if(d.k==='menu_unhold')out[i]={...q,held:false};
    else if(!q.held)out[i]={...q,held:true,state:q.placeholder?q.state:'held',...(q.placeholder?{words:`held · ${q.words}`}:{}),...(q.release?{release:{...q.release,words:'held',waits:[],note:''}}:{})};
  }
  return PM.rows=out;
}
function rowMenu(q,list='queue'){
  const id=menuId(q), acts=q.menu||[];
  if(list!=='queue'||!acts.length)return '';
  const name=menuName(id);
  if(S.planMenu!==id)return `<button class="qmenu" data-planmenu="${esc(id)}" aria-expanded="false" aria-label="More for ${esc(name)}">${I.dots}</button>`;
  const keys=[...new Set(acts.map(k=>k==='menu_hold'||k==='menu_unhold'?(q.held?'menu_unhold':'menu_hold'):k))].filter(controlOf);
  return `<span class="qacts" role="group" aria-label="${esc(name)}">${keys.map(k=>`<button data-menuact="${k}" data-tid="${esc(id)}" aria-label="${esc(controlOf(k).label)}">${I[MENU_ICON[k]]}</button>`).join('')}</span>`;
}
const removedCard=q=>card(`<div class="row">${q.id?taskChip(q.id):''}<div class="grow"><b class="ell">${esc(q.title||q.id)}</b><span class="small">Removed</span></div><button class="btn" data-menuundo="${esc(menuId(q))}">Undo</button></div>`,'',`data-k="${q.placeholder?'rel:next':'task:'+esc(q.id)}"`);
/* where a row stands in its section, for Undo */
function menuPlace(q){
  const xs=(S.snap.queue||[]).filter(x=>x.section===q.section), i=xs.findIndex(x=>x.id===q.id), ids=l=>l.map(x=>x.id);
  return JSON.stringify({up:ids(xs.slice(0,Math.max(i,0))),down:ids(xs.slice(i+1)),in:q.section||''});
}
function menuDo(k,id,more){
  const d={id,k,cid:'',at:Date.now(),ms:PM_MS,...more};
  PM.did=PM.did.filter(x=>x.id!==id||k!=='menu_remove'&&x.k!==k&&!(x.k.endsWith('hold')&&k.endsWith('hold'))).concat([d]);
  d.cid=outbox('run_control',{key:k,tid:id},{ctl:k+':'+id,say:`${controlOf(k).label.split(':')[0]}: ${menuName(id)}`}).cid;
  return d;
}
function menuAct(k,id){
  const i=PM.rows.findIndex(x=>menuId(x)===id), q=PM.rows[i];
  if(!q||!controlOf(k)||k==='menu_remove'&&Date.now()-PM.at<PM_AGAIN)return;  // a double tap on the dots removes nothing
  if(k!=='menu_remove'){
    if(k==='menu_top')S.planMenu='';
    menuDo(k,id);render(true);
    return menuFocus(k==='menu_top'?`[data-planmenu="${id}"]`:`[data-menuact][data-tid="${id}"]`);
  }
  S.planMenu='';PM.gone=Date.now();
  for(const l of Object.keys(S.taskOpen))if(taskIsOpen(l,id))delete S.taskOpen[l];
  menuDo(k,id,{ms:PM_UNDO,q,down:PM.rows.slice(i+1).map(menuId),place:q.placeholder?'':menuPlace(q)});
  render(true);menuFocus(`[data-menuundo="${id}"]`);
  menuTimer();
}
/* Undo goes once its time is over */
function menuTimer(){setTimeout(()=>{if(PM.did.some(d=>d.k==='menu_remove'&&!d.back)){render();menuTimer()}},PM_UNDO/4)}
function menuUndo(id){
  const d=PM.did.find(x=>x.id===id&&x.k==='menu_remove'&&!x.back);
  if(!d||Date.now()-PM.gone<PM_AGAIN)return;  // nor does one on Remove undo it
  d.back=true;d.at=Date.now();d.ms=PM_MS;
  d.cid=outbox('run_control',{key:'menu_restore',tid:id,text:d.place},{ctl:'menu_restore:'+id,say:`Put back: ${menuName(id)}`}).cid;
  render(true);menuFocus(`[data-task="${id}"]`);
}
function menuFocus(sel){const b=$('body').querySelector(sel);if(b)b.focus({preventScroll:true})}
function rowMenuOpen(id){
  S.planMenu=id;PM.at=Date.now();render(true);
  const b=$('body').querySelector('.qacts button');if(!b)return;
  b.focus({preventScroll:true});
  if(b.animate)moAnim(b.parentElement,[{transform:'translateX(24px)',opacity:0},{transform:'none',opacity:1}],FOLD_MO);
}
function rowMenuShut(){
  const id=S.planMenu, was=$('body').querySelector('.qacts');if(!id)return;
  const focused=was&&was.contains(document.activeElement);
  S.planMenu='';render(true);
  const b=$('body').querySelector(`[data-planmenu="${id}"]`);if(!b)return;
  if(focused)b.focus({preventScroll:true});
  rowMenuOut(b,was);
}
/* a copy of the closed icons goes back; the dots come in their place */
function rowMenuOut(b,was){
  const g=was&&!calm()&&was.cloneNode(true);if(!g||!b.animate)return;
  g.setAttribute('aria-hidden','true');g.inert=true;for(const x of g.querySelectorAll('*'))for(const k of Object.keys(x.dataset))delete x.dataset[k];
  g.style.pointerEvents='none';g.style.zIndex=1;document.body.appendChild(g);
  const r=b.getBoundingClientRect();Object.assign(g.style,{position:'fixed',top:r.top+'px',right:innerWidth-r.right+'px'});
  const a=moAnim(g,[{transform:'none',opacity:1},{transform:'translateX(24px)',opacity:0}],{...FOLD_MO,fill:'forwards'});
  if(a)a.onfinish=a.oncancel=()=>g.remove();else g.remove();
  moAnim(b,[{opacity:0},{opacity:1}],{ease:'--ease',dur:'--dur'});
}
I.top=ic('<path d="M5 4h14M12 20V9M6 14l6-6 6 6"/>');
window.addEventListener('keydown',e=>{if(e.key==='Escape'&&S.planMenu&&!S.sheet&&$('body').querySelector('.qacts')){e.preventDefault();e.stopImmediatePropagation();rowMenuShut()}},true);
