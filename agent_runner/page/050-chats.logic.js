function feedMark(entries){const es=entries||[], l=es[es.length-1];
  return l&&l.id?{id:l.id}:{tail:es.map(e=>e.kind+'\n'+e.text)}}
/* the entries after the mark. No mark (the feed was not read yet at the send): those after the person's own words
   `said`, none until they show */
function feedAfter(entries,mark,said){
  const es=entries||[];
  if(typeof mark==='number')return es.slice(mark);
  if(!mark){let i=-1;es.forEach((e,j)=>{if(e.kind==='you'&&(!said||talkShown(e.text)===talkShown(said)))i=j});return i<0?[]:es.slice(i+1)}
  if(mark.id){const i=es.findIndex(e=>e.id===mark.id);return i<0?es:es.slice(i+1)}  // gone past the cap: all of it is new
  const t=mark.tail, k=es.map(e=>e.kind+'\n'+e.text);
  if(!t.length)return es;
  for(let at=0;at<Math.max(1,Math.min(2,k.length));at++)  // B154: the feed may start with the prompt it kept
    for(let d=0;d<t.length;d++){const n=t.length-d;
      if(n<=k.length-at&&t.slice(d).every((x,i)=>k[at+i]===x))return es.slice(at+n)}
  return es;
}
/* the page keeps a chat at its newest message: is it there now */
const atEnd=b=>b.scrollHeight-b.scrollTop-b.clientHeight<60;
/* F171: whether Talk's top bar is away, after `was` {top,size,run,away}: gone once the person scrolls up 8px and is away from the
   end (atEnd), back once they scroll down 8px or are at the end. A change of size (new words, the keyboard) and iOS's bounce are no scroll of theirs */
function barAway(was,b){
  const end=Math.max(0,b.scrollHeight-b.clientHeight), top=Math.max(0,Math.min(b.scrollTop,end)), size=b.scrollHeight+'x'+b.clientHeight;
  const d=was.size===size?top-was.top:0, run=atEnd(b)?0:d*was.run>=0?was.run+d:d;
  return {top,size,run,away:atEnd(b)?false:run<=-8?true:run>=8?false:was.away};
}
/* F124: a finger moving (dx, dy) over the app: does the drawer follow it (open: it is open), '' not, 'wait' too early */
function swipeTakes(dx,dy,open){
  if(Math.hypot(dx,dy)<8)return 'wait';  // B167: under the 10px at which iOS begins a scroll, which nothing can cancel then
  return Math.abs(dx)>Math.abs(dy)*1.7&&(open?dx<0:dx>0)?'drag':'';
}
/* F401: past the first 8px, is a finger moving (dx, dy) a pull down; how far it must go for letting go to refresh; and how
   far the spinner then is (it resists) */
const pullTakes=(dx,dy)=>dy>Math.abs(dx)*1.7, PULL_AT=70, pullAt=dy=>96*(1-Math.exp(-Math.max(0,dy)/120));
const WAVE='<span class="wave" aria-hidden="true"><i></i><i></i><i></i></span>';  // F147: at work
/* F147: a spring with no overshoot of its own, let go at from with speed v (px/ms): where it is on each frame (16 ms) to to */
function springFrames(from,to,v){
  const w=.02, a=from-to, b=(v||0)+w*a, out=[];
  for(let i=0;i<60;i++){const x=Math.exp(-w*16*i)*(a+b*16*i);out.push(to+x);if(i&&Math.abs(x)<.5)break}
  out.push(to);return out;
}
/* where the drawer settles when the finger lets go: dx moved, v its speed (px/ms), w the drawer's width */
const swipeOpens=(dx,v,w,open)=>Math.abs(v)>.35?v>0:(open?w+dx:dx)>w/2;
/* F97: a setting's value as a field shows it, and the words typed in one as a value ({v} or {err}) */
const settingText=v=>v==null?'':typeof v==='string'?v:Array.isArray(v)?v.join('\n'):typeof v==='object'?JSON.stringify(v):String(v);
