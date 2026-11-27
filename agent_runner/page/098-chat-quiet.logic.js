/* F507: the chats the person dragged into Quiet (quiet) or out of it (up) stand there whatever their activity says.
   g: {top, quiet}, the rows as grouped; pins: the pinned chats in their order. The top keeps chatSort's order, Quiet newest first */
function chatForce(g,quiet,up,pins){
  const q=quiet||[], u=up||[], down=g.top.filter(s=>q.includes(s.name)), lift=g.quiet.filter(s=>!s.response&&u.includes(s.name));
  if(!down.length&&!lift.length)return g;
  const top=g.top.filter(s=>!down.includes(s)), rest=g.quiet.filter(s=>!lift.includes(s));
  const p=pins||[], pin=s=>{const i=p.indexOf(s.name);return i<0?p.length:i}, at=s=>s.at>0?s.at:Infinity;
  return{top:top.concat(lift).sort((a,b)=>pin(a)-pin(b)||(at(a)===at(b)?+b.name.slice(1)-+a.name.slice(1):at(b)>at(a)?1:-1)),
    quiet:rest.concat(down).sort((a,b)=>(b.at||0)-(a.at||0))};
}
/* F507: a drop of chats (names) into a section (to: 'quiet' or 'top'). was: {top, quiet}, the names as drawn; saved: {quiet, up, pins}.
   The new saved lists, or null when none of them changes section. A chat put in Quiet is unpinned */
function chatDrop(was,names,to,saved){
  const from=to==='quiet'?was.top:was.quiet, moved=(names||[]).filter(n=>from.includes(n));
  if(!moved.length)return null;
  const off=l=>(l||[]).filter(n=>!moved.includes(n)), on=l=>off(l).concat(moved);
  return to==='quiet'?{quiet:on(saved.quiet),up:off(saved.up),pins:off(saved.pins)}:{quiet:off(saved.quiet),up:on(saved.up),pins:(saved.pins||[]).slice()};
}
if(typeof module!=='undefined')module.exports=Object.assign(module.exports||{},{chatForce,chatDrop});
