/* F194b: the example project's walkthrough: one card at a time, each pointing at the real thing. x: {off: its page with
   no run up, up, working, needs, landed: how many of each there are, home: reached through Runner Home}. A step is
   {id, title, text, view: where the thing is in the run app, at: selectors for it, the first one on screen counts
   ('sec:Words' is a section's heading), many: how many of them to point at}; its words are WALK_STEPS' */
const WALK=WALK_STEPS.map(s=>s.id);
function walkStep(id,x){
  const w=WALK_STEPS.find(s=>s.id===id);if(!w)return null;
  const first='[data-pact="start"]', off=x.off?w.pageOff||w.noRun:'';
  const s={
    queue:{view:'plan',many:3,at:x.off?['[data-k="pq"]','sec:Queue']:['.card[data-k^="task:"]','sec:Queue'],say:[w.text]},
    start:{view:'plan',at:x.off?[first,'.pcard']:x.up?['.card:has([data-k="runsaid"])']:['[data-ctl="start"]','.card:has([data-k="runsaid"])'],say:[x.up?w.up:w.off]},
    session:{view:'plan',at:x.off?[first,'.pcard']:['#body .srow:has(.livedot)','.card:has([data-k="runsaid"])'],say:[w.text,x.working?w.pageWorking:w.pageIdle,off]},
    needs:{view:'home',at:x.off?['.card.need','sec:Needs you']:['#body .card:has([data-needopen])','sec:Needs you'],say:[w.text,x.needs?off||w.some:w.none]},
    land:{view:'plan',at:x.off?[first,'.pcard']:['[data-k="landed"]','sec:Landed'],say:[w.text,w.page,x.landed||x.off?'':w.none,off]},
    chat:{view:'home',at:x.off?[first,'.pcard']:['#body .box'],say:[w.text,w.page,off]},
    own:{view:'',at:['#top [data-addproject]','[data-up]','a.brand','.icon[data-menu]'],say:[w.text,x.home?w.pageHome:w.setup]},
  }[id];
  const{say,...rest}=s;
  return{id,title:w.title,text:say.filter(Boolean).join(' '),...rest};
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
