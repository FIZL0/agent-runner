/* B216a1: what one continuous recognizer heard in a Hold. Its results list holds several finals, and iOS may repeat the
   earlier text in a later one, drop it from the list, or begin a piece anew after a silence with the words before gone:
   nothing heard is lost, and nothing is there twice. slots: per place in the list, done (pieces that were there before),
   w (the piece now), fin (it is final); kept by the caller between calls. after: ms since the words last changed */
const holdWords=x=>x.toLowerCase().replace(/['’]/g,'').replace(/[^\p{L}\p{N}]+/gu,' ').trim().split(' ').filter(Boolean);
const holdBegins=(x,y)=>{const a=holdWords(x), b=holdWords(y);return b.length>0&&b.every((w,i)=>a[i]===w)};
/* the piece w takes the place of old, yet is no new version of it: an old final that w does not go on from, or after a
   silence words with none of old's (a final: anywhere; one not yet final: in the same place) */
function holdApart(old,w,fin,after,pause){
  if(!holdWords(old.w).length||holdBegins(w,old.w))return false;
  if(old.fin)return true;
  if(after<pause)return false;
  const a=holdWords(old.w), b=holdWords(w);
  return fin?!b.some(x=>a.includes(x)):!b.some((x,i)=>a[i]===x);
}
function holdHear(slots,results,after,pause){
  for(let i=0;i<results.length;i++){
    const x=results[i], w=x[0].transcript, s=slots[i]||(slots[i]={done:[],w:'',fin:false});
    if(!w.trim()){if(x.isFinal)s.fin=true;continue}  // an empty piece unsays nothing
    if(holdApart(s,w,x.isFinal,after,pause))s.done.push(s.w);
    s.w=w;s.fin=!!x.isFinal;
  }
  if(results.length)for(const s of slots.slice(results.length))if(!s.fin)s.w='';  // not yet final and gone: it went into another piece
  return holdJoin(slots);
}
/* the pieces as one text. One that begins with all before it, or with the one before it, repeats that; one lone word said
   again is the person's own */
function holdJoin(slots){
  const ps=[];
  for(const s of slots){for(const w of s.done)ps.push({w,gap:true});if(s.w.trim())ps.push({w:s.w,gap:s.fin})}
  let out='', last='', gap=false;
  for(const p of ps){
    const w=p.w.trim(), rep=x=>holdWords(x).length>1&&holdBegins(w,x);
    if(rep(out))out=w;
    else if(rep(last))out=out.slice(0,out.length-last.length)+w;
    else out+=(out&&(gap||/^\s/.test(p.w))?' ':'')+w;
    last=w;gap=p.gap||/\s$/.test(p.w);
  }
  return out;
}
