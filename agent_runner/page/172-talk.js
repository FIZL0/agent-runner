/* --- F161b: Recorded, the page: the mic's sound is kept here while the person talks, posted to the run as WAV, and the words
   come back. A Recorder does what a browser's recognizer does (start, stop, abort; onaudiostart, onresult, onerror, onend),
   so hear() and the one-recognizer rules (MIC) treat both the same ------------- */
const REC_TAIL=200, REC_SILENT=8000, REC_FIRST=3000, REC_POST=50000, REC_AGAIN=500, REC_LOOK=500, REC_MIN=0.15, REC_PRE=1, REC_WAKE=1000;  // ms: sound still taken after a stop; a listen nobody speaks in; the mic's first sound; an answer; s: the shortest clip; what is kept from before a press; ms: the sound's start
/* the mic's sound in pieces of 2048; its output stays silent, and is there so that every browser runs it */
const REC_WORKLET=`registerProcessor('rec',class extends AudioWorkletProcessor{
  constructor(){super();this.b=new Float32Array(2048);this.n=0;this.port.onmessage=e=>{if(e.data==='flush'&&this.n)this.port.postMessage(this.b.slice(0,this.n));this.n=0}}
  process(i){const c=i[0]&&i[0][0];if(c)for(const x of c){this.b[this.n++]=x;if(this.n===2048){this.port.postMessage(this.b.slice());this.n=0}}return true}})`;
/* the kept stream takes sound now, so a press needs to wait for nothing */
const recLive=()=>!!REC.open&&!REC.open.rest&&REC.open.track.readyState==='live'&&REC.open.ctx.state==='running';
function recWake(o){
  if(o.rest){o.rest=false;o.node.port.postMessage('clear')}
  o.track.enabled=true;
  return Promise.resolve(o.ctx.resume()).then(()=>o);
}
/* the stream, asked for once and kept: a press uses the open one, or waits for the Allow under way */
function recOpen(){
  const o=REC.open;
  if(o&&o.track.readyState==='live')return recWake(o);
  if(o)recFree('track ended by the browser');
  const on=REC.asking;
  if(on){
    if(on.ctx)try{Promise.resolve(on.ctx.resume()).catch(()=>{})}catch(e){}  // in the press: iOS starts it only there
    return on.then(recWake,e=>{if(on.own)return recOpen();throw e});  // the page's own opening failed: the press asks itself
  }
  return recBegin(false);
}
/* own: opened by the page, not by a press */
function recBegin(own){
  const box=REC.took={at:Date.now(),gum:null,no:'',up:null,ctx:null}, p=REC.asking=recAsk(REC.gen,own,box), done=()=>{if(REC.asking===p)REC.asking=null};
  p.own=own;p.ctx=box.ctx;p.then(done,done);
  return p;
}
async function recAsk(gen,own,box){
  let ctx=null, stream=null;
  try{
    ctx=box.ctx=new (window.AudioContext||window.webkitAudioContext)();  // in the press: iOS starts it only there
    const t0=Date.now(), ran=()=>{if(box.up==null&&ctx.state==='running')box.up=Date.now()-t0};
    const up=Promise.resolve(ctx.resume()).then(ran).catch(()=>{});
    try{stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}})}
    catch(e){box.no=(e&&e.name)||'failed';throw e}finally{box.gum=Date.now()-t0}
    const url=URL.createObjectURL(new Blob([REC_WORKLET],{type:'text/javascript'}));
    try{await ctx.audioWorklet.addModule(url)}finally{URL.revokeObjectURL(url)}
    const on=Promise.resolve(ctx.resume()).then(ran).catch(()=>{});  // again: a page with the mic may start it with no press
    if(!own)await Promise.race([up,on,new Promise(r=>setTimeout(r,REC_WAKE))]);  // with no press it may never settle
    if(gen!==REC.gen)throw new Error('the mic was closed meanwhile');
    const node=new AudioWorkletNode(ctx,'rec'), track=stream.getAudioTracks()[0], o={ctx,stream,node,track,ring:[],kept:0,rest:false,box};
    ctx.createMediaStreamSource(stream).connect(node);node.connect(ctx.destination);
    node.port.onmessage=e=>{if(REC.now&&REC.now.on)REC.now.take(e.data);else recRing(o,e.data)};
    track.onended=()=>{if(REC.open!==o)return;const r=REC.now;recFree('track ended by the browser');REC.shut=true;if(r)r.cut();recLook()};
    REC.why='';REC.open=o;recLook();
    return o;
  }catch(e){
    if(gen===REC.gen)REC.why=`opening failed: ${(e&&e.name)||e}`;
    if(stream)for(const t of stream.getTracks())t.stop();
    if(ctx)try{const q=ctx.close();if(q)q.catch(()=>{})}catch(x){}
    throw e;
  }
}
/* F161c: between listens the last second is kept for the next press and what is older is dropped. A mic held again while
   the last words are made keeps all since */
function recRing(o,x){
  if(o.rest)return;
  o.ring.push(x);o.kept+=x.length;
  if(!(TK.ear&&TK.ear.more))while(o.kept>REC_PRE*o.ctx.sampleRate)o.kept-=o.ring.shift().length;
}
/* while a reply plays no sound is taken. Where the browser allows the mic for good the stream closes, so the sound is as
   with no mic; where a new one could ask again it only rests */
function recQuiet(){
  const o=REC.open;if(!o||REC.now||o.rest)return;
  if(REC.may)return recFree('freed for a reply');
  o.rest=true;o.ring=[];o.kept=0;o.track.enabled=false;
  try{const p=o.ctx.suspend();if(p)p.catch(()=>{})}catch(e){}
}
/* Talk's mic is on screen, Recorded can be used, and the Mic test is closed. A listen under way goes on beside the message box */
const recShown=()=>!document.hidden&&S.view==='talk'&&!S.thread&&S.sheet!=='mictest'&&(!!REC.now||(talkRec()&&!talkTyping()));
/* B804a: why recShown() does not hold, for the mic report */
const recGone=()=>document.hidden?'page hidden':S.view!=='talk'||S.thread?'Talk left':S.sheet==='mictest'?'freed for the Mic test':talkTyping()?'freed for typing':'Recorded could not be used';
/* F161c: the mic is open while Talk shows: opened with no press only where the browser already allows it, closed while a
   reply plays. Talk left or hidden, or the Mic test: a recording ends with its words, then the mic is released */
function recLook(){
  clearTimeout(REC.timer);REC.timer=0;
  if(TS.way!=='recorded'&&!REC.open)REC.shut=false;
  else{
    REC.timer=setTimeout(recLook,REC_LOOK);
    if(!recShown()){
      REC.shut=false;
      if(REC.now){if(REC.open)REC.now.over('Talk left')}
      else if(REC.open){recFree(recGone());soundAs('playback')}
      else if(REC.asking&&REC.asking.own){recFree(recGone());soundAs('playback')}
    }else if(talkReads())recQuiet();
    else if(REC.open&&REC.open.rest){soundAs('play-and-record');recWake(REC.open).catch(()=>{})}
    else recAhead();
  }
  const sign=!!REC.open&&!REC.open.rest;
  if(REC.sign!==sign){REC.sign=sign;if(S.view==='talk'&&!S.thread)talkDraw()}
}
const recMayOpen=()=>TS.way==='recorded'&&talkRec()&&recShown()&&!REC.open&&!REC.asking&&!REC.now&&!REC.shut&&!talkReads()&&!MIC.rec&&!MIC.next&&!TK.ear&&!DK.rec;
async function recAhead(){
  if(REC.query||!recMayOpen())return;
  REC.query=true;
  let st='';try{st=(await navigator.permissions.query({name:'microphone'})).state}catch(e){}  // a browser that cannot say: the first press opens it
  REC.query=false;REC.perm=st||'the browser cannot say';
  if(!recMayOpen())return;
  REC.may=st==='granted';
  if(!REC.may)return;
  soundAs('play-and-record');
  const gen=REC.gen;
  recBegin(true).catch(()=>{if(gen===REC.gen)REC.shut=true;soundAs('playback')});  // not tried again by itself until Talk shows anew
}
/* B804a: the permission at a press, for the mic report */
function recAsked(log){
  try{navigator.permissions.query({name:'microphone'}).then(p=>{REC.perm=p.state;log(`permission: ${p.state}`)},()=>log('permission: the browser cannot say'))}
  catch(e){log('permission: the browser cannot say')}
}
class Recorder{
  constructor(){this.recorded=true;this.parts=[];this.n=this.pre=0;this.came=false;this.level={floor:null,spoke:false,quiet:0,all:0}}
  start(again){
    REC.now=this;
    if(recLive())return this.begin(REC.open,again);  // F161c: in the press itself
    /* B804a: the mic report: why it was not open, and what the opening took, also where the listen ended meanwhile */
    const t=TK.rec===this?TK.ear:null, log=x=>{if(t)micLog(x,false,t.trail)}, at=Date.now(), kept=REC.open, was=REC.asking&&REC.took;
    const lost=()=>{if(was&&was!==REC.took)log(`mic not opened by the page: ${recTook(was,at)}`)};  // the press asked again itself
    log(recNotOpen(kept,REC.asking,REC.why,document.hidden,REC.perm,REC.shut));
    if(t)recAsked(log);
    recOpen().then(o=>{
      lost();
      log(o===kept?`mic woken: context ${o.ctx.state} after ${Date.now()-at} ms`:`mic opened: ${recTook(o.box,at)}`);
      if(!this.done&&!this.stopping)this.begin(o,again);
    },e=>{lost();log(`mic not opened${REC.took?': '+recTook(REC.took,at):''}`);throw e}).catch(e=>this.refused(e));
  }
  /* it listens, from the second before the press */
  begin(o,again){
    REC.shut=false;this.rate=o.ctx.sampleRate;this.on=true;
    this.parts=o.ring;this.n=this.pre=o.kept;o.ring=[];o.kept=0;
    if(this.onstart)this.onstart();
    if(this.n){if(TK.ear)micLog(`kept ${Math.round(1000*this.n/this.rate)} ms from before`,false,TK.ear.trail);if(this.onaudiostart)this.onaudiostart()}
    clearTimeout(this.first);
    this.first=setTimeout(()=>{if(this.came||this.done||this.stopping)return;
      recFree('no sound came from it');this.on=false;talkDraw();
      if(!again)this.start(true);else this.fail('No sound came from the mic',true)},REC_FIRST);  // a kept stream can go mute: it is opened afresh once
  }
  refused(e){
    if(this.done)return;
    const n=e&&e.name;
    if(n==='NotAllowedError'||n==='SecurityError'){REC.no='the browser did not let the page use the mic';return this.fail('The browser did not let the page use the mic',true)}
    this.fail(n==='NotFoundError'?'No mic was found':n==='NotReadableError'?'The mic is in use by something else':'The recording could not start',true);
  }
  /* falls: nothing was recorded, so the browser's recognition can hear instead */
  fail(why,falls){if(this.done)return;if(falls)REC.shut=true;this.falls=!!falls&&!!SR;if(this.onerror)this.onerror({error:'recorded',message:why+(this.falls?", so the browser's recognition is used":'')});this.end()}
  take(x){
    if(this.done||!this.on||this.posted||!this.rate)return;
    this.came=true;
    const most=(REC.engine&&REC.engine.seconds)||120;
    if(this.n/this.rate>=most-0.5)return;  // the tail too stays under the run's limit
    if(!this.n&&this.onaudiostart)this.onaudiostart();
    this.parts.push(x);this.n+=x.length;
    if(this.stopping)return;
    let sq=0;for(const y of x)sq+=y*y;
    const now=recLevel(this.level,Math.sqrt(sq/x.length),1000*x.length/this.rate,MIC_PAUSE,REC_SILENT);
    if(this.n/this.rate>=most-1){toast(`A recording is at most ${most} seconds: it goes out now.`);this.over('the longest clip')}
    else if(!TK.hold&&now){this.mute=now==='silence';this.over(now==='silence'?'silence':'a pause')}
  }
  over(by){if(TK.rec===this)micStop(by);else this.stop()}
  /* the mic went away (a call): what was recorded goes out */
  cut(){if(!this.on)return this.fail('The mic was closed',true);this.over('the mic, closed')}
  stop(){
    if(this.done||this.stopping)return;
    if(TK.rec!==this)return this.abort();  // dropped (New Talk chat, a play button): nothing is posted
    this.stopping=true;this.said=this.n-this.pre;
    if(!this.on)return this.end();
    const o=REC.open, go=()=>this.post();
    setTimeout(()=>{if(o&&REC.open===o)o.node.port.postMessage('flush');setTimeout(go,20)},REC_TAIL);
  }
  abort(){
    if(this.done)return;
    if(this.ctl)this.ctl.abort();
    if(this.onerror)this.onerror({error:'aborted',message:''});
    this.end();
  }
  async post(){
    if(this.done||this.posted)return;
    this.posted=true;if(REC.now===this)REC.now=null;recLook();
    if(this.mute||(this.pre?this.said:this.n)<REC_MIN*this.rate){this.parts=[];if(this.mute&&this.onerror)this.onerror({error:'no-speech',message:''});return this.end()}
    const t=TK.ear;if(t&&TK.rec===this){t.reading=true;talkDraw()}
    const wav=recWav(this.parts,this.rate), at=Date.now(), log=x=>{if(t)micLog(x,false,t.trail)};
    this.parts=[];log(`clip, ${(this.n/this.rate).toFixed(1)} s`);
    let got, again=false;
    for(;;){
      try{got=await this.ask(wav);break}
      catch(e){
        if(this.done)return;
        if(e.net&&!again){again=true;await new Promise(r=>setTimeout(r,REC_AGAIN));if(this.done)return;continue}  // once more
        log(`no words after ${Date.now()-at} ms: ${e.message}`);recLoad();  // an engine that is gone: the next listen is the browser's
        return this.fail(e.net||e.late?'The run did not answer, so your words are lost. Try again':`The run made no words: ${e.message}`);
      }
    }
    if(this.done)return;
    log(got?`words came after ${Date.now()-at} ms`:`no words after ${Date.now()-at} ms: an empty answer`);
    if(got&&this.onresult)this.onresult({resultIndex:0,results:[Object.assign([{transcript:got}],{isFinal:true})]});
    this.end();
  }
  async ask(wav){
    const c=this.ctl=new AbortController(), timer=setTimeout(()=>{c.late=true;c.abort()},REC_POST);
    try{
      let r;try{r=await fetch(tq('recorded'),{method:'POST',headers:{'Content-Type':'audio/wav'},body:wav,signal:c.signal})}
      catch(e){throw Object.assign(new Error(c.late?'no answer in time':'no connection'),{net:!c.late,late:!!c.late})}
      const j=await r.json().catch(()=>null);
      if(!r.ok||!j||!j.ok)throw new Error((j&&j.out)||`error ${r.status}`);
      return String(j.words||'').trim();
    }finally{clearTimeout(timer)}
  }
  end(){
    if(this.done)return;
    this.done=true;this.parts=[];clearTimeout(this.first);
    if(REC.now===this){REC.now=null;recLook()}
    if(this.onend)this.onend();
  }
}
/* Talk settings: the way speech becomes words is picked (talkSet): Recorded is tried afresh, the browser's needs no stream */
function recPick(){REC.no='';REC.shut=false;if(TS.way==='recorded')recLoad();else if(!REC.now)recFree('Recorded was not picked');recLook()}
/* the setting's row in Talk settings */
function recRow(){
  if(!REC.asked)recLoad();
  const on=TS.way==='recorded', why=recWhy(), wait=why&&!REC.engine&&!REC.no&&recCan()&&window.isSecureContext!==false;
  const inst=REC.engine&&!REC.engine.engine&&!HOME_PAGE&&why===REC.engine.why?' Ask a chat to install one.':'';
  return `<label class="it setrow"><span class="grow">Speech to words</span><select class="fld" data-ts="way"><option value="browser" ${on?'':'selected'}>The browser's recognition</option><option value="recorded" ${on?'selected':''}>Recorded</option></select></label>
      ${why&&(on||!wait)?`<div class="small">${esc(on?`Recorded is not used now: ${why}.${inst}${SR?" The browser's recognition is used.":''}`:`Recorded cannot be used: ${why}.${inst}`)}</div>`:on?'<div class="small">The page records what you say, and the run\'s machine makes the words. The mic is open while Talk shows, with a dot on it: the second before a press is kept, what is older is dropped.</div>':''}
      ${on&&isSafari(navigator.userAgent)?'<div class="small">If Safari asks for the mic again after a reload: in the address bar\'s page menu, Website Settings, Microphone, Allow.</div>':''}`;
}
if(TS.way==='recorded'){recLoad();REC.timer=setTimeout(recLook,0)}
document.addEventListener('visibilitychange',()=>recLook());  // at once: a hidden page's timers stop
