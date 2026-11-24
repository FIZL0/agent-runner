/* B162b1: the Mic test (Talk settings): one press per try, each about MT_MS, the same mic in other conditions, so a mic that
   is on and hears no words can be told apart from one that takes no sound. It sends nothing; its report has times, letter
   counts and sound levels, never words. MT.runs: the tries so far, MT.run: the one under way */
const MT={ear:'',runs:[],run:null}, MT_MS=5000, MT_START=8000, MT_END=3000, MT_LOOK=200, MT_MOST=12;
const MT_TRIES=[['plain','Words, sound setting left as it is'],['switch','Words, set to play and record'],['sound','Words, right after a silent sound'],['level','Sound level only, no words']];
const MT_EAR=[['','Not said'],['off','Off'],['on','On']];
function micTestSheet(){
  const why=micWhy(), r=MT.run;
  const says=r?r.on?'Say "one two three four five" until it stops.':'Starting the mic…':!MT.ear?'Reload the page first, then pick whether earbuds are on.':'Press each in turn and say "one two three four five" each time. Nothing is sent.';
  return `<h2>Mic test</h2><div class="small" id="mtsays" role="status">${esc(why||says)}</div>
    <label class="it setrow"><span class="grow">Earbuds</span><select class="fld" data-mtear ${r?'disabled':''}>${MT_EAR.map(([v,l])=>`<option value="${v}" ${MT.ear===v?'selected':''}>${l}</option>`).join('')}</select></label>
    ${MT_TRIES.map(([k,l])=>{const last=MT.runs.filter(x=>x.kind===k&&x.done).pop();
      return `<button class="it" data-mictest="${k}" ${why||r||!MT.ear?'disabled':''}><span class="grow">${esc(l)}<span class="small" style="display:block">${esc(r&&r.kind===k?'Under way':last?last.says:'Not tried')}</span></span></button>`}).join('')}
    <div class="btns">${MT.runs.length?`<button class="btn" data-mictestcopy ${r?'disabled':''}>Copy mic test</button>`:''}<button class="btn" data-closesheet>Done</button></div>`;
}
SHEETS.mictest=micTestSheet;
function micTest(kind){
  if(MT.run||!MT.ear||micWhy())return;
  /* no hush() here: it calls speechSynthesis, and on iOS a mic started after that hears nothing (B132) */
  if(talkReads())return toast('A reply is being read: try again once it has ended.',true);
  if(TK.ear||MIC.rec||MIC.next)return toast('The mic is in use: stop it, then try again.',true);
  const prev=TK.trail;micLog(`mic test ${kind}`,true);TK.trail.used=true;
  try{if(navigator.audioSession)micLog(`audio session was ${navigator.audioSession.type}, ${navigator.audioSession.state||''}`)}catch(e){}
  const r=MT.run={kind,ear:MT.ear,trail:TK.trail,prev,on:false,done:false,says:'',letters:0,err:'',peak:0,loud:0,looks:0,timers:[],end:null};
  MT.runs=[...MT.runs,r].slice(-MT_MOST);
  if(kind==='level')mtLevel(r);
  else if(kind==='sound')mtSound(r,()=>mtWords(r));
  else mtWords(r);
  mtWatch(r);render(true);
}
const mtLog=(r,x)=>micLog(x,false,r.trail);
/* once a try is over, whatever ended it */
function mtDone(r){
  if(r.done)return;
  r.done=true;r.timers.forEach(clearTimeout);if(MT.run===r)MT.run=null;
  r.says=r.kind!=='level'?r.letters?`Heard ${r.letters} letters`:r.on?`The mic was on, no words (${r.err||'no error'})`:`The mic did not start (${r.err||'no error'})`
    :r.looks?`Loudest ${r.peak.toFixed(3)}, sound in ${Math.round(100*r.loud/r.looks)}% of the time${r.reader==='running'?'':` (not to trust: the sound reader was ${r.reader})`}`:`No sound was read (${r.err||'no error'})`;
  mtLog(r,`done: ${r.says}`);if(r.kind!=='level'&&r.on)PAST[r.letters?'words':'none']++;
  if(r.kind!=='plain')soundAs('playback');
  if(TK.trail===r.trail)TK.trail=r.prev;  // the last listen's report stays the one to copy
  render(true);
}
/* left or hidden: the try ends, and the mic with it */
function mtWatch(r){
  if(r.done)return;
  if((S.sheet!=='mictest'||document.hidden)&&!r.left){r.left=true;mtLog(r,'left');r.end?mtStop(r):mtDone(r)}
  r.timers.push(setTimeout(()=>mtWatch(r),MT_LOOK));
}
const mtLive=r=>{if(!r.on&&!r.done){r.on=true;r.timers.push(setTimeout(()=>mtStop(r),MT_MS));render(true)}};
function mtStop(r){if(!r.done&&!r.ending&&r.end){r.ending=true;r.end()}}
/* the page's own audio element plays silence first, as it plays a reply's clips */
function mtSound(r,then){
  let went=false;const go=x=>{if(went||r.done)return;went=true;mtLog(r,x);then()};
  soundAs('playback');
  try{const a=audioSrc(new Blob([silentWav()],{type:'audio/wav'}));a.onended=()=>go('silent sound ended');a.onerror=()=>go('silent sound failed');
    const p=a.play();if(p)p.then(()=>{AU.ok=true;pastSound('silent')}).catch(e=>go(`silent sound refused: ${e.name}`))}catch(e){go(`silent sound failed: ${e.name}`)}
  r.timers.push(setTimeout(()=>go('silent sound: no end came'),1500));
}
function mtWords(r){
  if(r.done)return;
  if(MIC.rec||MIC.next||TK.ear||talkReads()){r.err='a reply or another listen came first';return mtDone(r)}  // while the silent sound played
  let rec;try{rec=new SR()}catch(e){r.err=e.message||String(e);return mtDone(r)}
  MIC.rec=rec;rec.lang=navigator.language||'en-US';rec.interimResults=true;rec.continuous=false;
  const over=()=>{rec.onend=null;micFree(rec);mtDone(r)};
  for(const k of ['start','audiostart','soundstart','speechstart','speechend','soundend','audioend','nomatch'])rec['on'+k]=()=>{mtLog(r,k);if(/^(audio|sound|speech)start$/.test(k))mtLive(r)};
  rec.onresult=e=>{mtLive(r);let n=0;for(let i=0;i<e.results.length;i++)n+=e.results[i][0].transcript.length;r.letters=Math.max(r.letters,n);mtLog(r,`result, ${n} letters`)};
  rec.onerror=e=>{r.err=(e.error||'')+(e.message?': '+e.message:'');mtLog(r,`error ${r.err}`)};
  rec.onend=()=>{mtLog(r,'end');over()};
  r.end=()=>{mtLog(r,'stop');try{rec.stop()}catch(e){}
    r.timers.push(setTimeout(()=>{if(r.done)return;mtLog(r,'no end came: aborted');try{rec.abort()}catch(e){}
      r.timers.push(setTimeout(()=>{if(!r.done)over()},MIC_WAIT))},MT_END))};
  if(r.kind!=='plain')soundAs('play-and-record');
  try{rec.start()}catch(e){r.err=e.message||String(e);mtLog(r,`start failed: ${r.err}`);return over()}
  r.timers.push(setTimeout(()=>{if(!r.on)mtStop(r)},MT_START));
}
/* the mic's sound with no recognizer: the loudest, and how often there is any. It stands in MIC.rec as a recognizer does,
   so no reply and no listen starts beside it */
function mtLevel(r){
  let stream=null, ctx=null;
  const own={stop:()=>over(),abort:()=>over(),onend:()=>over()};
  const over=()=>{if(r.done)return;
    if(stream)stream.getTracks().forEach(t=>t.stop());
    if(ctx)try{ctx.close()}catch(e){}
    micFree(own);mtDone(r)};
  MIC.rec=own;r.end=over;soundAs('play-and-record');
  const fail=e=>{r.err=(e&&e.name)||String(e);mtLog(r,`level failed: ${r.err}`);over()};
  let asked;
  try{const C=window.AudioContext||window.webkitAudioContext;ctx=new C();if(ctx.resume)Promise.resolve(ctx.resume()).catch(()=>{});  // made in the tap
    asked=navigator.mediaDevices.getUserMedia({audio:true})}catch(e){return fail(e)}
  asked.then(s=>{
    stream=s;
    if(r.done){s.getTracks().forEach(t=>t.stop());return}
    const t=s.getAudioTracks()[0];
    /* a device's name can hold a person's: only whether it is the phone's own mic */
    mtLog(r,`mic open, ${/iphone|ipad|built-in|default/i.test(t.label)?"the device's own mic":t.label?'another mic':'mic not named'}, ${t.muted?'muted':'not muted'}, sound reader ${ctx.state}`);
    t.onmute=()=>mtLog(r,'muted');t.onunmute=()=>mtLog(r,'not muted');t.onended=()=>mtLog(r,'mic ended');
    const an=ctx.createAnalyser(), buf=new Float32Array(an.fftSize=2048);ctx.createMediaStreamSource(s).connect(an);mtLive(r);
    const look=()=>{if(r.done)return;an.getFloatTimeDomainData(buf);let p=0;for(const v of buf)p=Math.max(p,Math.abs(v));
      r.looks++;r.reader=ctx.state;r.peak=Math.max(r.peak,p);if(p>0.02)r.loud++;if(r.looks%10===0)mtLog(r,`level ${p.toFixed(3)}, reader ${ctx.state}`);
      r.timers.push(setTimeout(look,100))};
    look();
  }).catch(fail);
}
const micTestText=()=>['Mic test',`version ${RUN_VERSION}`,navigator.userAgent,...MT.runs.map(r=>'\n'+micReport(r.trail,[`${(MT_TRIES.find(x=>x[0]===r.kind)||[])[1]}; earbuds ${r.ear||'not said'}`,r.trail.past]))].join('\n');
