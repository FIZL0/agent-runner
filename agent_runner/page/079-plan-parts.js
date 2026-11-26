/* F453: a split task's parts in the Plan queue: one card for the split task, its parts under it, indented, in the order
   they run (its `split.list`, ui_model_queue.split_parts: the landed first, ticked and dim, then the rest in plan order).
   An open part is a row there only, with its menu, buttons and grip; a parked or shelved one is there too, and says so.
   The group stands where its first open part stands in the queue. Open by default; PT.shut: the groups shut on this
   page (not kept over a load) */
const PT={shut:{}};
const partsOf=q=>((q&&q.split&&q.split.list)||[]);
/* the queue's rows `rows` (plan order) as they are drawn: each split task's parts after it, nested */
function partRows(rows){
  const all=(S.snap.queue||[]).concat(rows.filter(q=>!(S.snap.queue||[]).includes(q))), sh=S.snap.shelved||[];
  const owner={};
  for(const q of all)for(const p of partsOf(q))if(!p.landed&&p.id!==q.id)owner[p.id]=owner[p.id]||q.id;
  const top=id=>{const seen=[];while(owner[id]&&!seen.includes(id)&&all.some(q=>q.id===owner[id])){seen.push(id);id=owner[id]}return id};
  const hits=planWant()&&PQ.got?[...(PQ.got.open||[]),...(PQ.got.parked||[])].map(h=>h.id):[];
  for(const h of hits)for(let id=owner[h];id;id=owner[id]===id?'':owner[id])delete PT.shut[id];  // Find a task opens the group holding a match
  const live=id=>rows.find(q=>q.id===id);
  const running=q=>/^running/.test(q.state||'')||q.under_way;
  /* the group of row q: q, then (open) each of its parts not landed, depth one deeper, their own parts after them */
  const group=(q,depth,seen)=>{
    const ps=partsOf(q).filter(p=>!p.landed&&!seen.includes(p.id)), out=[];
    const rowOf=p=>{const r=live(p.id);if(r)return r;const k=all.find(x=>x.id===p.id);if(k&&k.state==='parked')return {...k,partHow:'parked'};
      const s=sh.find(x=>x.id===p.id);return s?{...s,partHow:'shelved'}:null};
    const kids=ps.map(rowOf).filter(Boolean), now=kids.find(running);
    const shut=!!PT.shut[q.id]&&!S.planWait;
    const me=partsOf(q).length?{...q,parts:{shut,now:now?`${now.id} ${planWords(now,S.snap.sessions)}`:''}}:q;
    out.push(depth?{...me,partOf:q.partOf||'',depth}:me);
    if(shut)return out;
    for(const k of kids)for(const x of group({...k,partOf:q.id},depth+1,seen.concat(q.id)))out.push(x.partOf?x:{...x,partOf:q.id});
    return out;
  };
  const done=new Set(), out=[];
  for(const q of rows){
    const t=top(q.id);
    if(t===q.id&&!partsOf(q).length){out.push(q);continue}
    if(done.has(t))continue;
    const head=live(t);
    if(!head){out.push(q);continue}  // a part whose split task is not in the queue
    if(t===q.id&&rows.some(x=>x!==q&&top(x.id)===t))continue;  // it stands where its first open part stands
    done.add(t);out.push(...group(head,0,[]));
  }
  for(const q of rows)if(partsOf(q).length&&!done.has(q.id)&&top(q.id)===q.id){done.add(q.id);out.push(...group(q,0,[]))}  // no open part in the queue
  return out;
}
/* is row q (a part) under task `id`, however deep */
const partIn=(q,id,rows)=>{for(let p=q.partOf,n=0;p&&n<9;n++){if(p===id)return true;const r=rows.find(x=>x.id===p);p=r&&r.partOf}return false};
/* the split task's card: its row, the parts bar (a chevron; shut, it still says which part runs) and its landed parts */
function partsBar(q){
  const ps=partsOf(q), id=q.id, shut=!!(q.parts&&q.parts.shut), left=ps.filter(p=>!p.landed).length;
  const words=shut?`${ps.length} part${ps.length===1?'':'s'}${q.parts.now?` · ${q.parts.now}`:left?` · ${left} to go`:''}`:'Parts, in the order they run';
  const landed=shut?'':ps.filter(p=>p.landed).map(p=>`<div class="partdone" data-k="partdone:${esc(id)}:${esc(p.id)}"><span class="tick" aria-label="Landed">${I.check}</span>${taskChip(p.id)}<span class="ell">${esc(p.title||p.id)}</span></div>`).join('');
  return `<button class="partsbar" data-partsopen="${esc(id)}" data-k="parts:${esc(id)}" aria-expanded="${!shut}"><span class="grow small">${esc(words)}</span><span class="chev">${I.chev}</span></button>${landed?`<div class="partsdone">${landed}</div>`:''}`;
}
const splitCard=(q,list='queue')=>card(taskRow(q,q.title||q.id,taskBtns(q),list)+partsBar(q)+rowMenu(q,list)+rowGrip(q,list),'splitq'+(q.depth?' part':''),`data-k="task:${esc(q.id)}"${q.depth?` style="--depth:${q.depth}"`:''}`);
/* a part's card: the card it has anywhere (a parked or shelved one's too), indented */
function partCard(q){
  if(partsOf(q).length)return splitCard(q);
  const c=q.partHow==='shelved'?shelvedCard(q,'queue'):q.partHow==='parked'?parkedCard(q,'queue'):planCard(q);
  return c.replace('class="card ',`style="--depth:${q.depth||1}" class="card part `);
}
document.addEventListener('click',e=>{
  const b=e.target.closest&&e.target.closest('[data-partsopen]');if(!b)return;
  e.preventDefault();e.stopImmediatePropagation();
  const id=b.dataset.partsopen;if(PT.shut[id])delete PT.shut[id];else PT.shut[id]=true;
  render(true);
  const f=[...$('body').querySelectorAll('[data-partsopen]')].find(x=>x.dataset.partsopen===id);if(f)f.focus({preventScroll:true});
},true);
