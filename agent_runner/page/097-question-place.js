/* B840a: a long question is read by scrolling inside its card: a redraw of the dock (a chip changes) keeps the place, per chat and question */
const QPLACE={at:'',y:0}, questionPlaced=()=>{const c=document.querySelector('#dock .qcard');return c&&{c,at:c.dataset.k+' '+c.dataset.v}};
document.addEventListener('scroll',e=>{const q=questionPlaced();if(q&&e.target===q.c)Object.assign(QPLACE,{at:q.at,y:q.c.scrollTop})},{capture:true,passive:true});
if(window.MutationObserver)new MutationObserver(()=>{const q=questionPlaced();if(q&&q.at===QPLACE.at&&!q.c.scrollTop)q.c.scrollTop=QPLACE.y}).observe($('dock'),{childList:true});
