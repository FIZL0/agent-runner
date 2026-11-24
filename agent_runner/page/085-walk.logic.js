/* F194b: the example project's walkthrough: one card at a time, each pointing at the real thing. x: {off: its page with
   no run up, up, working, needs, landed: how many of each there are, home: reached through Runner Home}. A step is
   {id, title, text, view: where the thing is in the run app, at: selectors for it, the first one on screen counts
   ('sec:Words' is a section's heading), many: how many of them to point at} */
const WALK=['queue','start','session','needs','land','chat','own'];
function walkStep(id,x){
  const first='[data-pact="start"]', off=(words)=>x.off?` ${words}`:'';
  const s={
    queue:{title:'The queue',view:'plan',many:3,at:x.off?['[data-k="pq"]','sec:Queue']:['.card[data-k^="task:"]','sec:Queue'],
      text:'Each task names the files it changes. Tasks that share no files run side by side, one agent each. A task can also wait for another one to land first.'},
    start:{title:'Start run',view:'status',at:x.off?[first,'.pcard']:x.up?['.card:has([data-k="runsaid"])']:['[data-ctl="start"]','.card:has([data-k="runsaid"])'],
      text:x.up?'The run is up. Its agents work on the queue, on your own Claude usage. A run starts only when you start it. Stop lets the running tasks finish, then ends the run.'
        :'Start run sets agents to work on the queue, on your own Claude usage. Nothing starts until you press it.'},
    session:{title:'A session',view:'home',at:x.off?[first,'.pcard']:['#body .card[data-thread]','sec:Working now'],
      text:(x.working?'Each task has an agent session of its own. Open one to watch it work and to write to it.'
        :'Each task has an agent session of its own. It shows under Working now while it works, and opening it lets you watch it and write to it.')+off('Start the run to see one.')},
    needs:{title:'Needs you',view:'home',at:x.off?['.card.need','sec:Needs you']:['#body .card:has([data-needopen])','sec:Needs you'],
      text:x.needs?'What only you can decide or check waits here, and the rest of the run goes on. '+(x.off?'You can answer it once the run is up.':'An answer sends its task back to the queue.')
        :'What only you can decide or check waits here, and the rest of the run goes on. Nothing does right now.'},
    land:{title:'A merge landing',view:'status',at:x.off?[first,'.pcard']:['[data-k="late"]','sec:Landed lately'],
      text:'A finished task is merged and its tests run. It lands on main only when they pass, and then it is listed under Landed lately on Status.'+(x.landed||x.off?'':' Nothing has landed yet.')+off('Start the run to see one.')},
    chat:{title:'Talk to a control session',view:'home',at:x.off?[first,'.pcard']:['#body .box'],
      text:'Write in your own words: ask how it goes, add a task, change one. Each message here opens a chat with a control session, which knows the run and uses your own Claude usage.'+off('The message box is on Home once the run is up.')},
    own:{title:'Your own project',view:'',at:['#top [data-addproject]','[data-up]','a.brand','.icon[data-menu]'],
      text:x.home?'That is how a run goes. Add the folder of a git project of yours, and its queue and its run get a page like this one.'
        :'That is how a run goes. For a project of yours, run agent-runner setup in its folder, in a terminal.'},
  }[id];
  return s?{id,...s}:null;
}
/* what a press does to where the person is: {at: the step's id, off: skipped or done}; nothing kept is the first step */
function walkParse(text){
  let o;try{o=JSON.parse(text||'{}')}catch(e){}
  return{at:o&&WALK.includes(o.at)?o.at:WALK[0],off:!!(o&&o.off===true)};
}
function walkMove(st,press){
  const i=WALK.indexOf(st.at);
  return press==='next'?{...st,at:WALK[Math.min(i+1,WALK.length-1)]}:press==='back'?{...st,at:WALK[Math.max(i-1,0)]}
    :press==='skip'?{...st,off:true}:press==='done'?{at:WALK[0],off:true}:press==='again'?{...st,off:false}:st;
}
/* the card: Skip (Done on the last one) is always there, and so is Back. there: the page shows the step's view */
function walkHTML(s,x,there){
  const i=WALK.indexOf(s.id), last=i===WALK.length-1;
  return `<div class="card walkcard" data-k="walk:${s.id}"><div class="row"><div class="grow"><b>${s.title}</b> <span class="small">${i+1} of ${WALK.length}</span></div></div><div class="small">${s.text}</div><div class="btns"><button class="btn" data-walk="back"${i?'':' disabled'}>Back</button>${there?'':'<button class="btn" data-walk="show">Show me</button>'}${!last?'<button class="btn pri" data-walk="next">Next</button>':x.home?'<button class="btn pri" data-addproject>Add a project</button>':''}<button class="btn end" data-walk="${last?'done':'skip'}">${last?'Done':'Skip'}</button></div></div>`;
}
/* Runner Home with no projects: the example project, or one's own. o: {busy, err} */
function exampleOffer(o){
  return `<div class="card" data-k="example"><div><b>No projects yet</b><div class="small">None is under the scanned folders. Try agent-runner on the example project, a tiny app with a short queue made in a folder of its own, or add a project of yours. Nothing starts until you press Start run.</div></div>${o.err?`<div class="small"><span class="v-bad">${o.err}</span></div>`:''}<div class="btns"><button class="btn pri${o.busy?' busy':''}"${o.busy?' disabled':''} data-example>${o.err?'Retry':'Try the example project'}</button><button class="btn" data-addproject>Add a project</button></div></div>`;
}
