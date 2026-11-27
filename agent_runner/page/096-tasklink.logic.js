/* F482: the ids of known tasks in a reply's html become links that open the task; none inside a link already */
function taskLinks(h,known){
  const k=new Set(known||[]);let inA=0;
  return String(h||'').split(/(<[^>]*>)/).map(s=>{
    if(s[0]==='<'){if(/^<a[\s>]/i.test(s))inA++;else if(/^<\/a>/i.test(s))inA=Math.max(0,inA-1);return s}
    return inA?s:s.replace(/\b([A-Z]\d+[a-z0-9]*)\b/g,(m,id)=>k.has(id)?`<a href="#task-${id}" class="tasklink" data-taskgo="${id}">${id}</a>`:m);
  }).join('');
}
if(typeof module!=='undefined')module.exports=Object.assign(module.exports||{},{taskLinks});
