/* F426e: what merges, as Status and Home say it: the snapshot's `merging`, and a slot that is still on its task while it
   merges (slot: its name); an older run sends only those */
function mergeRows(snap){
  const ss=((snap&&snap.sessions)||[]).filter(s=>s.task&&s.state==='merging'), ms=(snap&&snap.merging)||[];
  return ms.map(m=>{const s=ss.find(x=>x.task===m.id);return s?{...m,slot:s.name,title:m.title||s.title}:m})
    .concat(ss.filter(s=>!ms.some(m=>m.id===s.task)).map(s=>({id:s.task,title:s.title,step:'',link:s.link||'',slot:s.name})));
}
/* two tasks' files: the same file, or one under the other's dir/** */
function filesMeet(a,b){
  const under=(x,y)=>x===y||y.endsWith('**')&&x.startsWith(y.slice(0,-2));
  return (a||[]).some(x=>(b||[]).some(y=>under(x,y)||under(y,x)));
}
/* why an idle slot starts nothing, from the run's state and the queue: merging, the ids that merge now */
function idleWhy(snap,merging){
  const run=snap.run||{}, all=snap.queue||[], on=q=>/^running/.test(q.state||'')||q.under_way||q.started||(merging||[]).includes(q.id);
  if(run.stopping)return 'The run is stopping: nothing new starts.';
  if(run.paused)return 'The run is paused: no new tasks start.';
  const qs=all.filter(q=>!on(q)&&q.state!=='parked'), of=f=>qs.filter(f).length, live=all.filter(on);
  if(!qs.length)return 'The queue is empty.';
  const ready=qs.filter(q=>q.state==='ready'||q.state==='critical'), files=ready.filter(q=>live.some(b=>filesMeet(q.files,b.files))).length, rest=ready.length-files;
  const say=(n,one,many)=>n?`${n} ${n===1?one:many}`:'';
  const parts=[say(files,'shares files with a task under way','share files with a task under way'),
    say(of(q=>q.state==='after'),'waits for another task','wait for another task'),
    say(of(q=>q.state==='blocked'),'is blocked','are blocked'),
    say(of(q=>q.state==='held'),'is held','are held'),
    say(of(q=>q.state==='tool'),'waits for a tool or a check','wait for a tool or a check'),
    say(rest,'is ready but not started yet','are ready but not started yet')].filter(Boolean);
  return `Of ${qs.length} queued ${qs.length===1?'task':'tasks'}, ${parts.join(', ')}.`;
}
