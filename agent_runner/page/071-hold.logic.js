/* B216a1: what one continuous recognizer heard in a Hold. Its results list holds several finals, and iOS may repeat the
   earlier text in a later one, drop it from the list, or begin a piece anew after a silence with the words before gone:
   nothing heard is lost, and nothing is there twice. slots: per place in the list, done (pieces that were there before),
   w (the piece now), fin (it is final); kept by the caller between calls. after: ms since the words last changed */
const holdWords=x=>x.toLowerCase().replace(/['’]/g,'').replace(/[^\p{L}\p{N}]+/gu,' ').trim().split(' ').filter(Boolean);
const holdBegins=(x,y)=>{const a=holdWords(x), b=holdWords(y);return b.length>0&&b.every((w,i)=>a[i]===w)};
/* the piece w takes the place of old, yet is no new version of it: an old final that w does not go on from, or after a
   silence words with under half of old's (a final: anywhere; one not yet final: in the same place) */
function holdApart(old,w,fin,after,pause){
  if(!holdWords(old.w).length||holdBegins(w,old.w))return false;
  if(old.fin)return true;
  if(after<pause)return false;
  const a=holdWords(old.w), b=holdWords(w);
  return 2*a.filter((x,i)=>fin?b.includes(x):b[i]===x).length<a.length;
}
function holdHear(slots,results,after,pause){
  let changed=false;
  for(let i=0;i<results.length;i++){
    const x=results[i], w=x[0].transcript, s=slots[i]||(slots[i]={done:[],w:'',fin:false});
    if(!w.trim()){if(x.isFinal)s.fin=true;continue}  // an empty piece unsays nothing
    if(holdApart(s,w,x.isFinal,after,pause))s.done.push(s.w);
    changed=changed||s.w!==w;s.w=w;s.fin=!!x.isFinal;
  }
  /* a piece gone from the list went into another one: not yet final, when another changed; final, when its words are there */
  const there=w=>slots.slice(0,results.length).some(s=>(' '+holdWords(s.w).join(' ')+' ').includes(' '+holdWords(w).join(' ')+' '));
  if(results.length)for(const s of slots.slice(results.length))if(s.fin?there(s.w):changed)s.w='';
  return holdJoin(slots);
}
/* the pieces as one text. One that begins with all before it, or with the last of them, repeats that; one lone word, or
   just the same two, said again are the person's own */
function holdJoin(slots){
  const ps=[];
  for(const s of slots){for(const w of s.done)ps.push({w,gap:true});if(s.w.trim())ps.push({w:s.w,gap:s.fin})}
  let out='', at=[], gap=false;  // at: where each piece in out begins
  for(const p of ps){
    const w=p.w.trim(), n=holdWords(w).length;
    const rep=at.find(i=>{const x=out.slice(i), m=holdWords(x).length;return m>(m===n?2:1)&&holdBegins(w,x)});
    if(rep!=null){out=out.slice(0,rep)+w;at=at.filter(i=>i<=rep)}
    else{out+=out&&(gap||/^\s/.test(p.w))?' ':'';at.push(out.length);out+=w}
    gap=p.gap||/\s$/.test(p.w);
  }
  return out;
}
