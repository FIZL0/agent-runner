/* --- F161b: Recorded, the page: the mic's sound is kept here while the person talks, posted to the run as WAV, and the words
   come back. A Recorder does what a browser's recognizer does (start, stop, abort; onaudiostart, onresult, onerror, onend),
   so hear() and the one-recognizer rules (MIC) treat both the same ------------- */
const REC_TAIL=200, REC_SILENT=8000, REC_FIRST=3000, REC_POST=50000, REC_AGAIN=500, REC_LOOK=500, REC_MIN=0.15;  // ms: sound still taken after a stop; a listen nobody speaks in; the mic's first sound; an answer; s: the shortest clip
/* the mic's sound in pieces of 2048; its output stays silent, and is there so that every browser runs it */
const REC_WORKLET=`registerProcessor('rec',class extends AudioWorkletProcessor{
  constructor(){super();this.b=new Float32Array(2048);this.n=0;this.port.onmessage=e=>{if(e.data==='flush'&&this.n)this.port.postMessage(this.b.slice(0,this.n));this.n=0}}
  process(i){const c=i[0]&&i[0][0];if(c)for(const x of c){this.b[this.n++]=x;if(this.n===2048){this.port.postMessage(this.b.slice());this.n=0}}return true}})`;
/* the stream, asked for once and kept: a press uses the open one, or waits for the Allow under way */
function recOpen(){
  const o=REC.open;
  if(o&&o.track.readyState==='live'){o.track.enabled=true;return Promise.resolve(o.ctx.resume()).then(()=>o)}
  if(o)recFree();
  if(REC.asking)return REC.asking.then(x=>{x.track.enabled=true;return Promise.resolve(x.ctx.resume()).then(()=>x)});
  const p=REC.asking=recAsk(REC.gen), done=()=>{if(REC.asking===p)REC.asking=null};
  p.then(done,done);
  return p;
}
async function recAsk(gen){
  let ctx=null, stream=null;
  try{
    ctx=new (window.AudioContext||window.webkitAudioContext)();  // in the press: iOS starts it only there
    const up=Promise.resolve(ctx.resume()).catch(()=>{});
    stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    const url=URL.createObjectURL(new Blob([REC_WORKLET],{type:'text/javascript'}));
    try{await ctx.audioWorklet.addModule(url)}finally{URL.revokeObjectURL(url)}
    await up;
    if(gen!==REC.gen)throw new Error('the mic was closed meanwhile');
    const node=new AudioWorkletNode(ctx,'rec'), track=stream.getAudioTracks()[0], o={ctx,stream,node,track};
    ctx.createMediaStreamSource(stream).connect(node);node.connect(ctx.destination);
    node.port.onmessage=e=>{if(REC.now)REC.now.take(e.data)};  // no listen: the sound is dropped
    track.onended=()=>{if(REC.open!==o)return;const r=REC.now;recFree();if(r)r.cut()};
    REC.open=o;recWatch();
    if(!REC.now)recRest();
    return o;
  }catch(e){
    if(stream)for(const t of stream.getTracks())t.stop();
    if(ctx)try{const q=ctx.close();if(q)q.catch(()=>{})}catch(x){}
    throw e;
  }
}
/* between listens the stream stays, with no sound taken from it */
function recRest(){const o=REC.open;if(!o)return;o.track.enabled=false;try{const p=o.ctx.suspend();if(p)p.catch(()=>{})}catch(e){}}
/* Talk left or hidden, or the Mic test, which needs the mic: a recording ends with its words, then the mic is released */
function recWatch(){
  const o=REC.open;if(!o)return;
  setTimeout(()=>{if(REC.open===o)recWatch()},REC_LOOK);
  if(!document.hidden&&S.view==='talk'&&!S.thread&&S.sheet!=='mictest')return;
  if(REC.now)REC.now.over('Talk left');else recFree();
}
class Recorder{
  constructor(){this.recorded=true;this.parts=[];this.n=0;this.level={floor:null,spoke:false,quiet:0,all:0}}
  start(again){
    REC.now=this;
    recOpen().then(o=>{
      if(this.done||this.stopping){if(!REC.now)recRest();return}
      this.rate=o.ctx.sampleRate;o.node.port.postMessage('clear');this.on=true;
      if(this.onstart)this.onstart();
      clearTimeout(this.first);
      this.first=setTimeout(()=>{if(this.n||this.done||this.stopping)return;
        recFree();this.on=false;
        if(!again)this.start(true);else this.fail('No sound came from the mic',true)},REC_FIRST);  // a kept stream can go mute: it is opened afresh once
    }).catch(e=>this.refused(e));
  }
  refused(e){
    if(this.done)return;
    const n=e&&e.name;
    if(n==='NotAllowedError'||n==='SecurityError'){REC.no='the browser did not let the page use the mic';return this.fail('The browser did not let the page use the mic',true)}
    this.fail(n==='NotFoundError'?'No mic was found':n==='NotReadableError'?'The mic is in use by something else':'The recording could not start',true);
  }
  /* falls: nothing was recorded, so the browser's recognition can hear instead */
  fail(why,falls){if(this.done)return;this.falls=!!falls&&!!SR;if(this.onerror)this.onerror({error:'recorded',message:why+(this.falls?", so the browser's recognition is used":'')});this.end()}
  take(x){
    if(this.done||!this.on||this.posted||!this.rate)return;
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
    this.stopping=true;
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
    this.posted=true;if(REC.now===this)REC.now=null;recRest();
    if(this.mute||this.n<REC_MIN*this.rate){this.parts=[];if(this.mute&&this.onerror)this.onerror({error:'no-speech',message:''});return this.end()}
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
    log(`words came after ${Date.now()-at} ms`);
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
    if(REC.now===this){REC.now=null;recRest()}
    if(this.onend)this.onend();
  }
}
/* Talk settings: the way speech becomes words is picked (talkSet): Recorded is tried afresh, the browser's needs no stream */
function recPick(){REC.no='';if(TS.way==='recorded')recLoad();else if(!REC.now)recFree()}
/* the setting's row in Talk settings */
function recRow(){
  if(!REC.asked)recLoad();
  const on=TS.way==='recorded', why=recWhy(), wait=why&&!REC.engine&&!REC.no&&recCan()&&window.isSecureContext!==false;
  const inst=REC.engine&&!REC.engine.engine&&!HOME_PAGE&&why===REC.engine.why?' Ask a chat to install one.':'';
  return `<label class="it setrow"><span class="grow">Speech to words</span><select class="fld" data-ts="way"><option value="browser" ${on?'':'selected'}>The browser's recognition</option><option value="recorded" ${on?'selected':''}>Recorded</option></select></label>
      ${why&&(on||!wait)?`<div class="small">${esc(on?`Recorded is not used now: ${why}.${inst}${SR?" The browser's recognition is used.":''}`:`Recorded cannot be used: ${why}.${inst}`)}</div>`:on?'<div class="small">The page records what you say, and the run\'s machine makes the words.</div>':''}
      ${on&&isSafari(navigator.userAgent)?'<div class="small">If Safari asks for the mic again after a reload: in the address bar\'s page menu, Website Settings, Microphone, Allow.</div>':''}`;
}
if(TS.way==='recorded')recLoad();
