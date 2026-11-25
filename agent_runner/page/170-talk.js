/* --- F93: Talk: the mic hears the person (Web Speech API), the words go to the Talk session (the `talk` action),
   and its reply is read aloud (F158: run speech, else speechSynthesis); the chat box under the mic works without either ------------- */
const TALK_FOR=':'+(HKEY||document.title), TALK_KEY='ar-talk'+TALK_FOR, TALK_OLD='ar-talkold'+TALK_FOR, TALK_START='ar-talkstart'+TALK_FOR;  /* the Talk session this browser opened ('new': none yet, the next message opens one), and the Talk chats New Talk chat left (F157) */
/* B177: Talk's own chat, per project (TALK_FOR: they can share an address) and per tab; a new tab takes the
   browser's last. '-': this tab has none, whatever another tab keeps. talkWas: the tab's chat, also once it has ended */
const talkKept=()=>{const v=tabStore.get(TALK_KEY);return v==='-'?'':v||store.get(TALK_KEY)}, talkKeep=v=>{tabStore.set(TALK_KEY,v||'-');store.set(TALK_KEY,v)}, talkWas=()=>{const v=tabStore.get(TALK_KEY);return/^c\d+$/.test(v)?v:''};
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
const TK={rec:null,heard:'',kept:'',trail:null,report:'',upAt:0,state:'',wait:null,said:'',unlocked:false,note:'',held:'',playing:'',later:[],watch:null,hold:false,holdId:null,again:false,ear:null,gen:0,starting:[]};  /* later, watch: talkNext(), soundWatch() (B174);  gen: counts New Talk chat presses; kept: words a listen did not send, as nothing was heard after them (micSent(), B216a1); starting: the sends that open a chat whose name is not known yet (F157); state: '', listening, thinking, speaking; ear: the listen under way (listen()); trail: what happened on the mic (micLog), report: the one to copy, upAt: when a hold ended; playing: the reply a play button reads; held: the reply the browser wants a tap for (F158) */
/* F124: Talk's settings (TALK_SET), as this browser last had them, and whether its dock shows the mic or the box, as this tab has it */
const TS_KEY='ar-talkset', TM_KEY='ar-talkmode';
let TS=talkSetParse(store.get(TS_KEY));
TK.starting=talkStartsRead();  // F157
function talkSet(k,v){TS=talkSetParse(JSON.stringify({...TS,[k]:v}));store.set(TS_KEY,JSON.stringify(TS));if(k==='way')recPick();render(true)}
const voices=()=>{try{return window.speechSynthesis?speechSynthesis.getVoices():[]}catch(e){return[]}};
if(window.speechSynthesis&&speechSynthesis.addEventListener)speechSynthesis.addEventListener('voiceschanged',()=>{if(S.sheet==='talk')render(true)});
/* F158: run speech: clips made on the run's machine, played one after another in one audio element (`AU.el`), which a
   tap on the speaker unlocks for good. AU.got: the run's voices, null until it answered; AU.ok: it has played */
const AU={el:null,got:null,ok:false,url:'',hold:null,holding:false};  /* B178: hold: the element that plays silence, holding: for a reply */
const runVoices=()=>(AU.got&&AU.got.voices)||[];
function loadVoices(){if(HOME_PAGE){AU.got={voices:[]};return}fetch(tq('speech')).then(r=>r.ok?r.json():null).then(j=>{if(j&&Array.isArray(j.voices)){AU.got=j;if(S.sheet==='talk')render(true)}}).catch(()=>{})}
loadVoices();
try{if(navigator.audioSession)navigator.audioSession.onstatechange=()=>{if(TK.trail)micLog(`audio session is ${navigator.audioSession.state}`)}}catch(e){}  // B178
/* the Voice setting's first options: with run voices, the default one, theirs by engine, then this device's (a group left open) */
function voiceOpts(){
  const vs=runVoices(), o=(v,t)=>`<option value="${esc(v)}" ${TS.voice===v?'selected':''}>${esc(t)}</option>`;
  if(!vs.length)return '<option value="">System voice</option>';
  const d=vs.find(v=>v.id===AU.got.default);
  return o('',`Default${d?` (${d.name})`:''}`)+[...new Set(vs.map(v=>v.engine))].map(e=>`<optgroup label="${esc(e==='Piper'?'Piper, light':e)}">${vs.filter(v=>v.engine===e).map(v=>o(v.id,v.name+(v.lang?` (${v.lang})`:''))).join('')}</optgroup>`).join('')+'<optgroup label="This device">'+o('system','System voice');
}
function audioEl(){return AU.el||(AU.el=new Audio())}
function audioSrc(blob){const a=audioEl();a.onended=a.onerror=a.onpause=null;if(AU.url)URL.revokeObjectURL(AU.url);a.src=AU.url=URL.createObjectURL(blob);return a}
/* inside a tap: the silent clip, so a later reply plays by itself. Not while a clip plays, nor while the mic listens: a tap
   that ends a listen (B166) plays it once the recognizer was told to stop */
function unlockAudio(){
  if(AU.ok||(TK.ear&&!TK.ear.stopped)||TK.state==='speaking'||TK.playing||!audioWanted())return;
  soundAs('playback');
  try{const h=holdEl(), q=h.play();if(q)q.then(()=>{if(!AU.holding)h.pause()}).catch(()=>{})}catch(e){}
  try{const p=audioSrc(new Blob([silentWav()],{type:'audio/wav'})).play();if(p)p.then(()=>{AU.ok=true;pastSound('silent')}).catch(()=>{})}catch(e){}
}
/* B178: while a reply is read, a second element plays silence without end, so the Bluetooth route is not closed and
   reopened between clips. The pause of the lock screen or the earbuds is the person's: it stops the reply */
function holdEl(){
  if(!AU.hold){AU.hold=new Audio(URL.createObjectURL(new Blob([silentWav(40000)],{type:'audio/wav'})));AU.hold.loop=true}
  return AU.hold;
}
function pauseKeys(f){try{const m=navigator.mediaSession;if(m)for(const k of ['pause','stop'])m.setActionHandler(k,f)}catch(e){}}
function routeHold(){
  AU.holding=true;pauseKeys(()=>{if(TK.trail)micLog('sound: stopped by the person');hush()});
  try{const h=holdEl(), p=h.play();h.onpause=()=>{if(AU.holding&&TK.trail)micLog('sound: the silence paused, not by the page')};
    if(p)p.then(()=>pastSound('silent')).catch(e=>{if(AU.holding&&TK.trail)micLog(`sound: the silence refused: ${e.name}`)})}catch(e){}
}
function routeFree(){
  if(!AU.holding)return;
  AU.holding=false;pauseKeys(null);if(AU.hold)AU.hold.pause();
}
/* what reads now stops, whichever of the two it is; clips: only the run's */
function shush(clips){
  if(AU.holding)routeFree();
  if(window.speechSynthesis&&!clips)speechSynthesis.cancel();
  const a=AU.el;if(a){a.onended=a.onerror=a.onpause=null;if(!a.paused)a.pause()}
}
