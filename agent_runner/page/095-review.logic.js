/* F444c: a pitch's Ask… fold on Needs you, beside Approve and Not this…: per waiting change a box, Ask about it (the
   answer shows under it, `ans`: {'pid:tid': {q, a} or {wait: q}}) and Ask for a better way (the box says what instead;
   it asks in place first, `sure` being 'better:pid:tid'). i is the item's place in the snapshot's needs */
const reviewField=(pid,tid)=>`review:${pid}:${tid}`;
function reviewAskHTML(n,i,ans,sure){
  return (n.changes||[]).map(x=>{const k=`${n.id}:${x.id}`, a=(ans||{})[k];
    const said=!a?'':a.wait?`<div class="small" role="status">Asking: ${E_(a.wait)}…</div>`:a.err?`<div class="small v-bad" role="alert">${E_(a.err)}</div>`
      :`<div class="review-ans" role="status"><div class="small"><b>${E_(a.q)}</b></div>${String(a.a||'').split(/\n+/).map(p=>`<p>${E_(p)}</p>`).join('')}</div>`;
    const at=`data-review="${i}" data-tid="${E_(x.id)}"`;
    return `<div class="small ell">${E_(x.id)} · ${E_(x.title)}</div><input class="fld" data-f="${E_(reviewField(n.id,x.id))}" aria-label="Your question about ${E_(x.id)}, or what you want instead" placeholder="Your question, or what you want instead" autocomplete="off">`
      +`<div class="btns"><button class="btn" ${at} data-how="ask">Ask about it</button><button class="btn" ${at} data-how="better">Ask for a better way</button></div>`
      +(sure===`better:${k}`?`<div class="sure" data-k="sure" role="group"><div class="small">Undo ${E_(x.id)} here and reopen its task with what you want instead?</div><div class="btns"><button class="btn bad" ${at} data-how="better" data-sure>Yes, undo and reopen</button><button class="btn" data-unsure>No</button></div></div>`:'')
      +said}).join('')}
if(typeof module!=='undefined')module.exports=Object.assign(module.exports||{},{reviewField,reviewAskHTML});
