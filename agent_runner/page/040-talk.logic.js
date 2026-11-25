const pickVoice=(voices,name)=>name?(voices||[]).find(v=>v.name===name)||null:null;
/* F158: the run voice (speech made on the run's machine) that reads, '' for the browser's own: `got` is the run's
   /speech answer, `name` the voice set in Talk settings. A run voice that is gone gives the run's default */
function runVoice(got,name){
  const vs=(got&&got.voices)||[];if(!vs.length||name==='system')return '';
  if(!name||/^(kokoro|piper):/.test(name))return vs.some(v=>v.id===name)?name:got.default||'';
  return '';  // a voice of this device
}
/* F158: a reply as the clips it is read in: its first sentence alone, so sound starts soon, then about 200 letters, then
   400 each (B178: few clips, for each new one can make Bluetooth reopen) */
function speechClips(text){
  const out=[];
  for(const s of String(text||'').match(/\S[\s\S]*?(?:[.!?]+(?=\s|$)|$)/g)||[])
    for(let i=0;i<s.length;i+=1000){const p=s.slice(i,i+1000).trim(), l=out.length-1;if(!p)continue;
      if(out.length&&(l>0||out[0].length<15)&&out[l].length+p.length<(l>1?400:200))out[l]+=' '+p;else out.push(p)}
  return out;
}
/* F158: 0.1 s of silence as a WAV file's bytes: played in a tap, it lets the page's audio element play later without one */
function silentWav(n=800){
  const b=new Uint8Array(44+n).fill(128), v=new DataView(b.buffer), s=(i,t)=>[...t].forEach((c,j)=>b[i+j]=c.charCodeAt(0));
  s(0,'RIFF');v.setUint32(4,36+n,true);s(8,'WAVEfmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);
  v.setUint32(24,8000,true);v.setUint32(28,8000,true);v.setUint16(32,1,true);v.setUint16(34,8,true);s(36,'data');v.setUint32(40,n,true);
  return b;
}
/* B162b1: what the page did before a press, for the mic report: the time since its load, the sounds it played (clips of run
   speech, the browser's own voice, silent ones that unlock or test), and the listens that ended with words and with none */
const PAST={at:Date.now(),last:0,clips:0,voice:0,silent:0,words:0,none:0};
function pastSound(kind){PAST[kind]++;PAST.last=Date.now()}
const micPast=()=>{const s=t=>Math.round((Date.now()-t)/1000)+' s';
  return `page open ${s(PAST.at)}; sounds started before: ${PAST.clips} clips, ${PAST.voice} of the browser's own voice, ${PAST.silent} silent${PAST.last?`, the last ${s(PAST.last)} ago`:''}; listens before: ${PAST.words} with words, ${PAST.none} without`};
/* B134: where a feed ends at a send, so what comes after it is found in a later feed even once the feed is capped and
   its indexes move: the last entry's own id, else (a transcript without ids) all its entries */
/* F161b: Recorded: the page records a clip and the run's machine makes the words (172-talk.js). REC: engine, the run's /recorded
   answer (null until it came); asked, it was asked for; no, why the mic was refused; open, the kept stream; asking, its
   Allow under way; now, the Recorder that takes sound; gen counts releases. F161c: may, the browser allows the mic for good; shut, no
   opening by itself until Talk shows anew; query, timer, sign: recLook()'s. B804a, for the mic report: why, what closed the
   last stream; perm, the permission last seen; took, the last opening's times */
const REC={engine:null,asked:false,no:'',open:null,asking:null,now:null,gen:0,may:false,shut:false,query:false,timer:0,sign:false,why:'',perm:'',took:null};
/* why Recorded cannot be used here, '' when it can */
function recProblem(secure,can,engine,refused){
  if(!secure)return 'it needs https or localhost, and this address is plain http';
  if(!can)return 'this browser cannot record in a page';
  if(refused)return refused;
  if(!engine)return 'the run has not said yet whether it can make words';
  return engine.engine?'':(engine.why||'the run has no speech recognition');
}
const recCan=()=>!!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia&&window.AudioWorkletNode);
const recWhy=()=>recProblem(window.isSecureContext!==false,recCan(),REC.engine,REC.no);
/* a listen records: Recorded is set and can be used, else the browser's recognition hears */
const talkRec=()=>TS.way==='recorded'&&!recWhy();
const micRec=t=>talkRec()&&!t.noRec?new Recorder():new SR();
function recLoad(){
  REC.asked=true;
  if(HOME_PAGE){REC.engine={engine:false,why:'open a project first'};return}
  fetch(tq('recorded')).then(r=>r.ok?r.json():null).then(j=>{if(j&&typeof j.engine==='boolean'){REC.engine=j;render(true)}}).catch(()=>{});
}
/* the kept stream closes, and with it the browser's sign that the mic is open */
function recFree(why){
  const o=REC.open;if(o||REC.asking)REC.why=why||"freed for the browser's recognition or dictation";
  REC.gen++;REC.open=REC.asking=null;if(!o)return;
  o.track.onended=null;o.node.port.onmessage=null;
  for(const t of o.stream.getTracks())t.stop();
  try{const p=o.ctx.close();if(p)p.catch(()=>{})}catch(e){}
}
/* B804a: why no stream was open at a press, for the mic report: o the kept stream, on its opening under way */
function recNotOpen(o,on,why,hidden,perm,shut){
  const was=why||'none yet', ctx=o?o.ctx:on&&on.ctx;
  const x=o?(o.track.readyState!=='live'?'track ended by the browser':o.rest?'resting':`its context is ${o.ctx.state}`)
    :on?`opening under way${on.own?', begun by the page':''}; before it: ${was}`:was;
  return `mic not open: ${x}${hidden?'; page hidden':''}${shut?'; not opened by itself until Talk shows anew':''}; permission last seen: ${perm||'not asked'}; context: ${ctx?ctx.state:'none'}`;
}
/* B804a: what an opening took: b = {at, gum, no, up, ctx}, its begin, ms of getUserMedia and of the context's start, press: when the press came */
function recTook(b,press){
  return `${b.at<press?`opening begun ${press-b.at} ms before: `:''}getUserMedia ${b.gum==null?'not answered':`${b.gum} ms`}${b.no?`, ${b.no}`:''}, context start ${b.up==null?`not seen (${b.ctx?b.ctx.state:'none'})`:`${b.up} ms`}`;
}
/* where the sound stands after a piece of `ms` with loudness `rms`: s = {floor, spoke, quiet, all}; floor follows the room's
   noise. Returns 'pause' (words, then pauseMs of quiet), 'silence' (nothing said in silentMs) or '' */
function recLevel(s,rms,ms,pauseMs,silentMs){
  s.floor=s.floor==null?Math.min(rms,0.01):rms<s.floor?rms:Math.min(0.03,s.floor+(rms-s.floor)*Math.min(1,ms/8000));
  s.all+=ms;
  if(rms>Math.max(0.008,s.floor*3)){s.spoke=true;s.quiet=0}else s.quiet+=ms;
  return s.spoke?s.quiet>=pauseMs?'pause':'':s.all>=silentMs?'silence':'';
}
/* Float32 pieces at `rate` as the 16 kHz mono 16-bit WAV the run takes; each sample a triangular mean, so what 16 kHz
   cannot hold does not fold back */
function recWav(parts,rate){
  const n=parts.reduce((a,p)=>a+p.length,0), x=new Float32Array(n);let at=0;
  for(const p of parts){x.set(p,at);at+=p.length}
  const step=rate/16000, m=Math.floor(n/step), b=new Uint8Array(44+m*2), v=new DataView(b.buffer), s=(i,t)=>[...t].forEach((c,j)=>b[i+j]=c.charCodeAt(0));
  s(0,'RIFF');v.setUint32(4,36+m*2,true);s(8,'WAVEfmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);
  v.setUint32(24,16000,true);v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);s(36,'data');v.setUint32(40,m*2,true);
  const w=Math.max(1,step);
  for(let i=0;i<m;i++){
    const c=i*step;let sum=0, all=0;
    for(let j=Math.max(0,Math.ceil(c-w));j<=c+w&&j<n;j++){const k=1-Math.abs(j-c)/w;if(k>0){sum+=x[j]*k;all+=k}}
    const y=Math.max(-1,Math.min(1,all?sum/all:0));v.setInt16(44+i*2,Math.round(y*32767),true);
  }
  return b;
}
/* Safari, also on iOS; the other browsers there have their own place for the mic's permission */
const isSafari=ua=>/Safari\//.test(ua||'')&&!/Chrome|Chromium|CriOS|FxiOS|Edg|OPiOS|Android/.test(ua||'');
