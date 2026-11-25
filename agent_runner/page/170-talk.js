/* --- F93: Talk: the mic hears the person (Web Speech API), the words go to the Talk session (the `talk` action),
   and its reply is read aloud (F158: run speech, else speechSynthesis); the chat box under the mic works without either ------------- */
const TALK_FOR=':'+(HKEY||document.title), TALK_KEY='ar-talk'+TALK_FOR, TALK_OLD='ar-talkold'+TALK_FOR, TALK_START='ar-talkstart'+TALK_FOR;  /* the Talk session this browser opened ('new': none yet, the next message opens one), and the Talk chats New Talk chat left (F157) */
/* B177: Talk's own chat, per project (TALK_FOR: they can share an address) and per tab; a new tab takes the
   browser's last. '-': this tab has none, whatever another tab keeps. talkWas: the tab's chat, also once it has ended */
const talkKept=()=>{const v=tabStore.get(TALK_KEY);return v==='-'?'':v||store.get(TALK_KEY)}, talkKeep=v=>{tabStore.set(TALK_KEY,v||'-');store.set(TALK_KEY,v)}, talkWas=()=>{const v=tabStore.get(TALK_KEY);return/^c\d+$/.test(v)?v:''};
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
const TK={rec:null,heard:'',kept:'',trail:null,report:'',upAt:0,state:'',wait:null,said:'',unlocked:false,note:'',held:'',playing:'',later:[],watch:null,hold:false,holdId:null,again:false,ear:null,gen:0,starting:[]};  /* later, watch: talkNext(), soundWatch() (B174);  gen: counts New Talk chat presses; kept: words a listen did not send, as nothing was heard after them (micSent(), B216a1); starting: the sends that open a chat whose name is not known yet (F157); state: '', listening, thinking, speaking; ear: the listen under way (listen()); trail: what happened on the mic (micLog), report: the one to copy, upAt: when a hold ended; playing: the reply a play button reads; held: the reply the browser wants a tap for (F158) */
/* F124: Talk's settings (TALK_SET), and whether its dock shows the mic or the box, as this browser last had them */
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
/* one clip from the run. Its error's message is plain words; net: no answer came, so asking again can help (late: none in 25 s, asked once more) */
function clipGet(text,voice){
  const c=new AbortController(), t=setTimeout(()=>c.abort(),25000), fail=(out,net,late)=>Object.assign(new Error(out),{net,late});
  return fetch(tq('speech'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,voice}),signal:c.signal})
    .then(async r=>{if(r.ok)return r.blob();const j=await r.json().catch(()=>({}));throw fail(j.out||`error ${r.status}`,!j.out&&r.status>=500)})
    .catch(e=>{throw e.net!=null?e:e.name==='AbortError'?fail('no answer in time',true,true):fail('no connection',true)})
    .finally(()=>clearTimeout(t));
}
const CLIP_AGAIN=[500,2000], PLAY_AGAIN=600;  /* B178: ms before each new try for a clip, and before an unasked pause is undone */
/* clip number i of `clips`, and then the rest; `turn` is TK.turn while nothing stopped it. end(): read to its end;
   fall(rest, why, net): the run made no sound for the rest; held(): the browser wants a tap first. What it does goes
   into the mic report, with no words (B178) */
async function playClips(clips,voice,turn,end,fall,held){
  if(!TK.trail||(TK.trail.ev.length>60&&!TK.ear)){micLog('read a reply',true);TK.trail.used=true}
  const on=()=>TK.turn===turn, trail=TK.trail, wait=ms=>new Promise(r=>setTimeout(r,ms));
  const log=(x,bad)=>{if(!on())return;micLog('sound: '+x,false,trail);if(bad){trail.sound=true;TK.report=trail}};
  const get=async(p,i)=>{
    for(let n=0;;n++){
      const at=Date.now();log(`clip ${i+1} of ${clips.length} asked, ${p.length} letters`);
      try{const b=await clipGet(p,voice);log(`clip ${i+1} came, ${b.size} bytes, after ${Date.now()-at} ms`);return b}
      catch(e){
        log(`clip ${i+1} failed${e.net?', '+e.message:''}, after ${Date.now()-at} ms`,true);
        if(!e.net||n>=(e.late?1:CLIP_AGAIN.length)||!on())throw e;
        await wait(CLIP_AGAIN[n]);if(!on())throw e;
      }
    }};
  const ask=i=>{if(i>=clips.length)return null;const p=get(clips[i],i);p.catch(()=>{});return p};
  let next=ask(0), resumed=false;
  for(let i=0;i<clips.length;i++){
    try{
      const b=await next;if(!on())return;
      next=ask(i+1);  // made while this one plays, so there is no gap
      for(let n=0;!i&&MIC.rec&&n<15;n++){await wait(100);if(!on())return}  // B178: a mic still ending
      soundAs('playback');routeHold();
      const w=TK.watch&&TK.watch.turn===turn?TK.watch:{};
      await new Promise((done,no)=>{const a=audioSrc(b);
        w.clip=a;w.at=Date.now();w.spot=-1;w.quiet=0;  // B174
        a.onended=done;a.onerror=()=>{log(`clip ${i+1} error ${a.error?a.error.code:''}`,true);no(new Error('the clip did not play'))};
        for(const k of ['playing','waiting','stalled'])a['on'+k]=()=>log(k);
        a.onpause=()=>{  // a call, a route change; the lock screen's pause goes to pauseKeys()
          if(a.ended||!on())return;
          log(`paused at ${(a.currentTime||0).toFixed(1)} s, not by the page`,true);
          if(resumed)return hush(true);
          resumed=true;
          setTimeout(()=>{if(!on()||!a.paused||a.ended)return;
            if(MIC.rec||MIC.next||TK.ear)return hush(true);  // never into a mic that listens
            log('play again');soundAs('playback');routeHold();
            const q=a.play();if(q)q.catch(e=>{if(!on())return;log(`play again refused: ${e.name}`);if(e.name==='NotAllowedError')no(e);else hush(true)})},PLAY_AGAIN)};
        const p=a.play();if(p)p.then(()=>{AU.ok=true;pastSound('clips')}).catch(e=>{if(e&&e.name==='AbortError')return;log(`play refused: ${e&&e.name}`,true);no(e)})});  // AbortError: a pause came first, onpause has it
      w.clip=null;log(`clip ${i+1} ended`);
    }catch(e){if(!on())return;routeFree();log(e&&e.name==='NotAllowedError'?'held for a tap':`clip ${i+1} and on: the browser's own voice`,true);
      if(e&&e.name==='NotAllowedError'){AU.ok=false;return held()}
      return fall(clips.slice(i).join(' '),e&&e.net!=null?e.message:'the clip did not play',!!(e&&e.net))}
    if(!on())return;
  }
  routeFree();end();
}
const talkTyping=()=>!!micWhy()||store.get(TM_KEY)==='type';
function talkMode(m){store.set(TM_KEY,m==='type'?'type':'');S.pin=true;if(chatShown())toEnd(true);render(true);const t=m==='type'&&document.querySelector('[data-in]');if(t)kbFocus(t)}
/* F157: the Talk chats left by New Talk chat, kept over a reload */
function talkOld(){try{const l=JSON.parse(store.get(TALK_OLD)||'[]');return Array.isArray(l)?l:[]}catch(e){return []}}
function talkLeave(names){store.set(TALK_OLD,JSON.stringify([...new Set(talkOld().concat(names))]))}
const talkTitled=()=>(S.snap.sessions||[]).filter(s=>s.title==='Talk').map(s=>s.name);
/* the sends still opening a chat, kept over a reload: gen -1 for those New Talk chat left */
function talkStarts(l){if(l.length===TK.starting.length&&l.every((w,i)=>w===TK.starting[i]))return;TK.starting=l;talkStartsKeep()}
const talkStartsKeep=()=>store.set(TALK_START,TK.starting.length?JSON.stringify(TK.starting.map(w=>({at:w.at,gen:w.gen===TK.gen?0:-1}))):'');
function talkStartsRead(){try{const l=JSON.parse(store.get(TALK_START)||'[]');return Array.isArray(l)?l.filter(w=>w&&typeof w.at==='number').map(w=>({at:w.at,gen:w.gen,kept:true})):[]}catch(e){return []}}
/* the live Talk session. A chat that was still starting when New Talk chat was pressed is old as soon as it shows */
function talkFind(remembered){
  talkStarts(TK.starting.filter(w=>{
    const t=w.gen===TK.gen&&!w.kept?'':talkSession(S.snap.sessions,'',talkOld());
    if(t&&w.gen!==TK.gen)talkLeave([t]);
    return !t&&Date.now()-w.at<90000}));
  if(remembered==='new'){const more=talkTitled().filter(n=>!talkOld().includes(n));if(more.length)talkLeave(more)}
  return talkSession(S.snap.sessions,remembered,talkOld());
}
/* F157: New Talk chat: whatever Talk is doing stops, and the next message opens a fresh Talk session. The old one
   stays in Chats; a message on its way still reaches it */
function newTalk(){
  const was=talkName(), known=(S.snap.sessions||[]).map(s=>s.name);
  if(known.length)store.set(TALK_OLD,JSON.stringify(talkOld().filter(n=>known.includes(n))));  // a chat that is gone: its name can come again
  talkLeave([...talkTitled(),was,talkKept()].filter(n=>n&&n!=='new'));
  talkKeep('new');TK.gen++;talkStartsKeep();
  const rec=TK.rec, spoke=talkReads();
  if(TK.ear)micLog('stop by New Talk chat');
  TK.ear=TK.rec=null;TK.hold=TK.again=false;TK.wait=null;
  TK.state=TK.heard=TK.kept=TK.said=TK.note=TK.report=TK.playing='';TK.turn=(TK.turn||0)+1;
  if(rec)rec.stop();
  TK.held='';TK.later=[];
  if(spoke)shush();
  S.drawer=false;S.pin=true;render(true);
}
function talkName(){
  const n=talkFind(talkKept());if(n)return n;
  const w=TK.wait;return w&&Date.now()-w.at<90000?w.n:'';  /* just opened: not in the snapshot yet */
}
/* B133: the session a Talk reply is awaited from ('' for none): a wait opened with no session name takes the live
   chat titled Talk once the snapshot lists it */
function talkWaitName(){
  const w=TK.wait;if(!w)return '';
  if(!w.n){const t=talkFind('');if(t){w.n=t;talkStarts(TK.starting.filter(x=>x!==w));talkKeep(t)}}
  return w.n;
}
const micWhy=()=>micProblem(window.isSecureContext!==false,!!SR||talkRec());
/* F115: dictation into the message box: DK.rec the recognizer while it listens, DK.key the box it fills, DK.base
   what that box held when it started. The words go into the box to edit; nothing is sent. */
const DK={rec:null,key:'',base:''};
const dictWhy=()=>dictProblem(window.isSecureContext!==false,!!SR);
/* B162: one recognizer at a time (iOS allows one, and aborts the second): MIC.rec is the one under way or still
   ending, MIC.next the start that waits for its end. One whose end never comes is aborted after MIC_WAIT ms. */
const MIC={rec:null,next:null,timer:0}, MIC_WAIT=1500, MIC_RETRY=250, MIC_END=5000, MIC_PAUSE=2000, MIC_GAP=1000, MIC_DEAF=3000;
function micWhenFree(start,cancel){
  if(MIC.next&&MIC.next.cancel)MIC.next.cancel();
  MIC.next=null;clearTimeout(MIC.timer);
  const old=MIC.rec;if(!old)return start();
  MIC.next={start,cancel};
  /* the abort's own onend starts the next; with none after as long again, the old one is taken for gone */
  const gone=()=>{if(MIC.rec!==old)return;if(TK.trail)micLog('the old one is taken for gone');const end=old.onend;old.onresult=old.onerror=old.onend=null;if(end)end()};
  MIC.timer=setTimeout(()=>{if(MIC.rec!==old)return;MIC.timer=setTimeout(gone,MIC_WAIT);if(TK.trail)micLog('abort of the old one');try{old.abort()}catch(e){}},MIC_WAIT);
  if(TK.trail)micLog('stop by the next start');
  try{old.stop()}catch(e){}
}
function micFree(rec){
  if(MIC.rec!==rec)return;
  const n=MIC.next;MIC.rec=MIC.next=null;clearTimeout(MIC.timer);if(n)n.start();else talkNext();
}
function dictShow(words){
  const v=dictInsert(DK.base,words);store.set(DRAFT_KEY(DK.key),v);
  const ta=document.querySelector('[data-in]');if(ta&&boxKey()===DK.key){ta.value=v;grow(ta)}
}
function dictate(){
  const why=dictWhy();if(why)return toast(why,true);
  if(DK.rec){if(MIC.rec===DK.rec)DK.rec.stop();else{MIC.next=null;DK.rec=null;render(true)}return}  // B162: or it still waits for its turn
  if(TK.state==='listening')return toast("Talk's mic is listening: tap it to stop, then dictate.",true);  /* it has the recognizer */
  const ta=document.querySelector('[data-in]');if(!ta)return;
  let rec;try{rec=new SR()}catch(e){return toast(`The mic could not start: ${e.message||e}`,true)}
  DK.rec=rec;DK.key=boxKey();DK.base=ta.value;
  rec.lang=navigator.language||'en-US';rec.interimResults=true;rec.continuous=false;
  let final='', heard='';
  rec.onresult=e=>{let interim='';for(let i=e.resultIndex;i<e.results.length;i++){const x=e.results[i];if(x.isFinal)final+=x[0].transcript;else interim+=x[0].transcript}
    heard=final+interim;dictShow(heard)};
  rec.onerror=e=>{if(e.error==='not-allowed'||e.error==='service-not-allowed')toast('The browser did not let the page use the mic: allow it in the site settings, or type instead.',true);
    else if(e.error!=='no-speech'&&e.error!=='aborted')toast(`The mic stopped: ${e.error}`,true)};
  rec.onend=()=>{DK.rec=null;dictShow(final||heard);render(true);
    const t=document.querySelector('[data-in]');if(t&&boxKey()===DK.key){t.focus({preventScroll:true});t.setSelectionRange(t.value.length,t.value.length)}micFree(rec);soundAs('playback')};
  render(true);
  micWhenFree(()=>{MIC.rec=rec;recFree();soundAs('play-and-record');try{rec.start()}catch(e){DK.rec=null;toast(`The mic could not start: ${e.message||e}`,true);render(true);micFree(rec);soundAs('playback')}},()=>{DK.rec=null});
}
/* F115: a chat's terminal colours are the run app's own tokens */
const TERM={mode:''};
/* the words on their way to the Talk session show at once, until it has them */
const talkGoing=()=>TK.wait&&TK.wait.out?`<div class="msgs"><div class="u pending" data-k="talkout" data-t="${esc(tkey(talkShown(TK.wait.said)))}">${esc(talkShown(TK.wait.said))}</div></div>`:'';
function talkHTML(){
  const n=talkName(), going=talkGoing();
  if(!n&&!going&&!S.snap.at&&/^c\d+$/.test(talkKept()))return `<div class="col"><div class="think">${LOGO()}Loading…</div></div>`;  // B177: no greeting before the chat it had
  const was=!n&&!going&&!TK.wait?talkWas():'';  // B177: the chat this tab had has ended: its words stay until the next message
  if(was){if(!S.feeds[was]&&!TK.loading){TK.loading=true;loadFeed(was).finally(()=>{TK.loading=false})}
    if(!S.feeds[was]||S.feeds[was].ok)return `<div class="col">${talkConvo(was)}${S.feeds[was]?'<div class="small" style="text-align:center">Your next message opens a new Talk chat.</div>':''}</div>`}
  if(!n)return going?`<div class="col">${going}<div class="think">${LOGO()}${WAVE}Starting the chat…</div></div>`: `<div class="col"><div class="greet">${LOGO()}Talk to the run</div><div class="small" style="text-align:center">Tap the mic and ask, say, what is going on: the reply is read aloud. ${talkKept()==='new'?'Your next message opens a new Talk chat. The old one stays in Chats.':'Talk opens a chat of its own the first time.'}</div></div>`;
  if(!S.feeds[n]&&!TK.loading){TK.loading=true;loadFeed(n).finally(()=>{TK.loading=false})}  /* its first look */
  return `<div class="col">${talkConvo(n)}${going}</div>`;
}
/* F124, B174: the dock's mic, always the mic: the speaker (the stop while a reply is read) and the mic (64px), the keyboard beside them. Its markup never changes while it
   listens or speaks (talkDraw sets that), so a finger holding the mic keeps it */
const talkMic=()=>`<div class="talkline" id="talkline" role="status"></div><button type="button" class="btn" id="micrep" data-micreport hidden>Copy mic report</button><button type="button" class="btn" id="keptsend" data-keptsend hidden>Send as it is</button><div class="talkrow"><button type="button" class="spk" id="spk" data-spk></button><button type="button" class="mic" id="mic" data-mic></button><button type="button" class="kbd" data-talkmode="type" aria-label="Type instead" title="Type instead">${I.keys}</button></div>`;
const talkFoot=()=>{const why=micWhy();return why?esc(why):keysLine(!!modelOf(talkName()))};
function talkDraw(){
  const why=micWhy(), st=TK.state, hold=TS.mic==='hold', mic=$('mic'), spk=$('spk'), line=$('talkline');
  const reads=talkReads(), stop=$('spkbox'), open=!!REC.open&&!REC.open.rest;  // F161c
  $('dock').classList.toggle('typing',talkTyping());
  if(stop)stop.hidden=!reads;
  if(!mic)return;
  const ear=TK.ear, again=ear&&ear.again&&TK.hold&&!ear.stopped;  // B216a1: a restart in a hold
  const now=again&&!ear.on?'The mic is off, wait until it is on again':again&&ear.deaf?`Nothing is heard. Let go and press again${ear.gapAt||ear.kept?', these words are kept':''}`:TK.ear&&TK.ear.reading?'Getting the words…':TK.ear&&!TK.ear.on?'Starting the mic…':'Listening…';
  /* B216a1: after a pause in a hold the mic can be off for a moment, so the line says when it is on again */
  line.textContent=why||(st==='listening'?(TK.heard?TK.heard+(TK.ear&&(TK.ear.gapAt||TK.ear.kept||(again&&!ear.on))?' … '+now:''):now):st==='thinking'?'Thinking…':st==='speaking'?'Speaking…':(TK.kept?`“${TK.kept.length>90?'…'+TK.kept.slice(-90):TK.kept}” Not sent: nothing was heard after these words. ${hold?'Hold':'Tap'} to go on from them, or send them as they are. `+TK.note:TK.note||(hold?'Hold to talk':'Tap to talk')+(open?', the mic is open':'')).trim());
  $('micrep').hidden=!!why||!!st||!TK.report;$('keptsend').hidden=!!st||!TK.kept;
  const label=why||(st==='listening'?'Stop listening':(hold?'Hold to talk':'Talk')+(open?', the mic is open':''));
  mic.className='mic'+(hold?' hold':'')+(st==='listening'?' on':open?' open':'');mic.disabled=!!why;
  mic.setAttribute('aria-label',label);mic.title=label;setHTML(mic,I.talk);
  const sl=reads?'Stop speaking':TK.held?'Read the reply aloud':TS.read?'Read replies aloud: on':'Read replies aloud: off';
  spk.className='spk'+(reads?' on':TS.read?'':' off');spk.setAttribute('aria-label',sl);if(reads)spk.removeAttribute('aria-pressed');else spk.setAttribute('aria-pressed',String(TS.read));spk.title=sl;setHTML(spk,reads?I.stop:TS.read?I.speak:I.mute);
}
/* the person's words to the Talk session; true once sent */
async function talkSend(msg){
  const to=talkName(), len=to?feedOf(to).length:0, mark=to&&S.feeds[to]?feedMark(feedOf(to)):null;  // B134
  if(TK.state!=='speaking')TK.state='thinking';TK.said=msg;TK.note=TK.held='';S.pin=true;if(chatShown())toEnd(true);unlockSpeech();loadVoices();render(true);
  /* B133: the wait starts before the action, which can take up to 90 s while a new chat comes up: a reply that
     lands meanwhile is heard from the polls and snapshots (talkWaitName finds the new chat by its title) */
  const w={n:to,since:to?mark:0,at:Date.now(),last:'',said:msg,out:true,gen:TK.gen};TK.wait=w;
  const asked=talkKept()==='new';if(asked){talkLeave(talkTitled());talkKeep('')}  // F157: a Talk chat that shows from now on is the new one
  if(!to)talkStarts([...TK.starting,w]);
  render(true);
  const r=await act('talk',{text:msg,to});w.out=false;
  const left=w.gen!==TK.gen;  // F157: New Talk chat was pressed meanwhile: these words belong to the chat it left
  if(!r.ok||r.session)talkStarts(TK.starting.filter(x=>x!==w));
  if(!r.ok){if(TK.wait===w)TK.wait=null;if(!left){if(TK.state==='thinking')TK.state='';if(asked&&!talkKept())talkKeep('new')}render(true);return false}
  const n=r.session||to, fresh=n!==to;
  if(TK.wait===w){if(fresh){w.n=n;w.since=0;w.last=''}w.at=Date.now()}  /* not yet heard; n '': found by its title */
  if(n){if(left)talkLeave([n]);else{talkKeep(n);store.set(TALK_OLD,JSON.stringify(talkOld().filter(x=>x!==n)))}addSent(n,msg,r.at,{talk:true,...(fresh?{first:true}:{})},fresh?0:len);loadFeed(n)}
  else if(TK.wait===w&&!w.n){w.sent={text:msg,at:r.at};toast('Talk is opening its chat: it shows here once it is up')}
  render(true);return true;
}
/* a new feed for session n: once the Talk reply has stood for one poll, read it aloud */
function talkHear(n){
  const w=TK.wait;if(!w||talkWaitName()!==n)return;
  if(Date.now()-w.at>300000){TK.wait=null;if(TK.state==='thinking'){TK.state='';toast('No spoken reply came in five minutes: its chat shows where it is.',true);render(true)}return}
  const said=talkReply(feedOf(n),w.since,w.said);
  if(!said||said!==w.last){w.last=said;return}
  TK.wait=null;
  if(TK.state==='thinking')TK.state='';
  if(TS.read){TK.later.push(said);talkNext()}  // F124: else read replies aloud is off
  render(true);
}
function unlockSpeech(){  /* Safari speaks later only after a first utterance inside a tap */
  soundAs('playback');unlockAudio();  // F158
  try{if(window.speechSynthesis&&!TK.unlocked){speechSynthesis.speak(new SpeechSynthesisUtterance(''));TK.unlocked=true}}catch(e){}
}
/* F124: read text aloud; key, the reply a play button reads (a Talk reply read by itself has none). Auto listen:
   once a Talk reply was read to its end, the mic listens again */
function speak(text,key){
  const ss=window.speechSynthesis, rv=runVoice(AU.got,TS.voice);
  if(!(ss||rv)||!text){TK.state='';TK.later=[];render(true);return}
  if(key&&TK.ear){micLog('stop by a play button');const r=TK.rec;TK.ear=TK.rec=null;TK.heard='';if(r)r.stop()}  // a play button stops the mic, so it does not hear the reply; nothing is sent
  if(TK.held)TK.note='';
  TK.state=talkRest();TK.playing=TK.held='';shush();
  const parts=text.match(/[^.!?]+[.!?]*\s*/g)||[text];  /* sentence by sentence: Chrome cuts one long utterance short */
  const voice=pickVoice(voices(),TS.voice), turn=TK.turn=(TK.turn||0)+1;
  const ended=e=>{if(TK.turn!==turn||!(key?TK.playing===key:TK.state==='speaking'))return;
    if(TK.state==='speaking')TK.state=talkRest();TK.playing='';render(true);
    if(TK.later.length)talkNext();
    else if(!key&&!TK.wait&&TS.auto&&(!e||e.type!=='error')&&S.view==='talk'&&!S.thread&&!talkTyping()){TK.again=true;listen()}};
  const w={turn,own:!rv,clip:null,at:Date.now(),len:0,quiet:0,spot:-1,begun:false,hid:false,us:[],end:ended};  // B174; us: an utterance nobody holds can lose its end
  const own=ps=>{w.own=true;w.clip=null;w.quiet=0;w.begun=false;w.at=Date.now();w.len=ps[0].length;ps.forEach((p,i)=>{const u=new SpeechSynthesisUtterance(p.trim());u.lang=(voice&&voice.lang)||navigator.language||'en-US';if(voice)u.voice=voice;w.us.push(u);
    const log=x=>{if(rv&&TK.turn===turn&&TK.trail)micLog("sound: the browser's own voice "+x)};  // B178
    u.onstart=()=>{if(!w.begun)pastSound('voice');w.begun=true;w.quiet=0;w.at=Date.now();w.len=p.length;if(!i)log('started')};
    u.onend=u.onerror=e=>{w.at=Date.now();w.len=(ps[i+1]||'').length;if(i===ps.length-1){log(e&&e.type==='error'?'error '+e.error:'ended');ended(e)}};
    ss.speak(u)})};
  if(REC.open)recQuiet();soundAs('playback');soundWatch(w);  // F161c
  if(!rv)own(parts);
  else{
    unlockAudio();  // a play button's tap
    playClips(speechClips(text),rv,turn,ended,(rest,why,net)=>{
      const mine=/iPhone|Android/.test(navigator.userAgent||'')?"the phone's voice":"this device's voice";
      toast(net?ss?`No connection to the run; reading with ${mine}`:'No connection to the run; the reply is not read aloud':ss?`The run could not read this aloud (${why}), so this browser does.`:`The run could not read this aloud: ${why}`,true);
      if(ss)own(rest.match(/[^.!?]+[.!?]*\s*/g)||[rest]);else ended({type:'error'});
    },()=>{TK.playing='';if(TK.state==='speaking')TK.state=talkRest();TK.turn++;TK.held=text;TK.note='The browser wants a tap first. Tap the speaker to hear the reply';
      if(talkTyping())toast('The browser wants a tap first. Tap the play button on the reply to hear it.',true);render(true)});
  }
  if(key)TK.playing=key;else TK.state='speaking';
  render(true);
}
/* the reading stops: by the person (replies still waiting keep their play buttons), or, keep, by itself: the next is read */
function hush(keep){TK.playing='';if(!keep)TK.later=[];if(TK.state==='speaking')TK.state=talkRest();TK.turn=(TK.turn||0)+1;shush();render(true);if(keep)talkNext()}
/* a Talk reply's play button: reads that reply, or stops it */
function playReply(k){
  if(TK.playing===k)return hush();
  const n=talkName()||talkWas(), ms=talkMsgs(feedOf(n)), i=ms.findIndex((m,j)=>(m.k||n+':'+j)===k);
  if(i>=0)speak(plain(ms[i].text),k);
}
function listen(){
  const why=micWhy();if(why)return toast(why,true);
  if(TK.state==='listening'){micStop('a tap');return unlockAudio()}  // B166
  /* B132: no speechSynthesis call before rec.start() on a plain tap: on iOS it puts the audio session in playback
     and recognition hears nothing (talkSend unlocks speech). B174: a press during a reply cuts it and listens: clips
     stop here, the browser's voice right after rec.start(), or here when this listen must wait for a recognizer. */
  if(TS.way==='recorded'&&!talkRec())recLoad();  // F161b: an engine installed meanwhile
  const cut=talkReads();TK.playing='';TK.turn=(TK.turn||0)+1;
  if(cut)shush(!MIC.rec);else unlockEnd();
  TK.note=TK.held='';if(!(TK.report&&TK.report.sound))TK.report='';const again=TK.again;TK.again=false;  /* auto listen: one silent turn and it stops */
  /* B162: the listen: its tries, the words so far, and whether the person ended it (stopped) or held the mic again */
  const t=TK.ear={mode:again?'auto':TS.mic,tries:0,words:TK.kept||'',kept:!!TK.kept,gapAt:0,waited:false,failed:false,stopAt:0,spoke:false,again:false,deaf:false,idle:null,err:'',ms:null,stopped:false,more:false,on:false,was:false,fails:0,msg:'',by:'',until:0,timer:0,longer:false,cut:cut&&!MIC.rec};
  if(!TK.trail||TK.trail.used)micLog('listen',true);  // a press began it already
  TK.trail.used=true;t.trail=TK.trail;micLog(`listen ${t.mode}${MIC.rec?', waits for the last one to end':''}`);
  TK.state='listening';TK.heard=t.words;render(true);
  micWhenFree(()=>hear(t));
  if(!again)audioReady();  // B166
}
/* B162: one recognizer for the listen t. Aborted before any words, it is tried once more by itself */
function hear(t){
  if(TK.ear!==t)return;  // ended while it waited
  const cut=()=>{if(t.cut&&window.speechSynthesis)speechSynthesis.cancel();t.cut=false};  // B174
  let rec;try{rec=micRec(t)}catch(e){cut();t.failed=true;micLog(`no recognizer: ${e.message||e}`,false,t.trail);TK.report=t.trail;TK.ear=null;TK.state='';toast(`The mic could not start: ${e.message||e}`,true);render(true);if(t.words)micSent(t,'no recognizer');return talkNext()}
  if(!rec.recorded)recFree();  // F161b: one use of the mic at a time
  t.reading=false;MIC.rec=TK.rec=rec;t.tries++;t.err=t.msg='';t.ms=null;t.on=t.deaf=false;talkDraw();
  rec.lang=navigator.language||'en-US';rec.interimResults=true;rec.continuous=TK.hold&&!rec.recorded;
  /* B216a1: one recognizer stays through a Hold's pauses, for the next one may hear nothing (iOS); should it end all the
     same, it is started again as before */
  micLog(`try ${t.tries}${rec.recorded?'':rec.continuous?', continuous':', not continuous'}`);
  const log=x=>micLog(x,false,t.trail);  // a dropped one's late events stay in its own report
  const at=Date.now();let parts=[], got='', begun=false, slots=[], heardAt=at;
  const live=()=>{t.failed=false;if(!t.on&&TK.ear===t){t.on=t.was=true;talkDraw();if(t.again)setTimeout(deaf,MIC_DEAF)}};  // the mic takes sound: now is the time to speak
  /* B216a1: the one started again in a hold takes no speech: said while the button is held */
  const deaf=()=>{if(begun||TK.ear!==t||TK.rec!==rec||t.stopped||!TK.hold)return;t.deaf=true;log(`no speech ${MIC_DEAF} ms after the restart: said on the line`);talkDraw()};
  const hears=()=>{begun=true;if(t.deaf&&TK.ear===t&&TK.rec===rec){t.deaf=false;talkDraw()}};
  /* a continuous one no longer held (iOS took the touch) does not end at a silence by itself */
  t.idle=()=>{if(!rec.continuous||TK.rec!==rec||TK.hold||t.stopped)return;clearTimeout(t.timer);
    t.timer=setTimeout(()=>{if(TK.ear===t&&TK.rec===rec&&!TK.hold&&!t.stopped)micStop('a pause')},MIC_END)};
  /* B216: the wait after a pause: words end it, speech not yet words makes it longer once */
  const goesOn=()=>{if(TK.ear===t){t.until=t.gapAt=0;t.kept=t.spoke=t.waited=false;clearTimeout(t.timer)}};
  const wait=()=>{t.until=Date.now()+MIC_PAUSE;clearTimeout(t.timer);
    t.timer=setTimeout(()=>{if(TK.ear===t&&t.until&&!t.stopped&&!TK.hold)micStop('a pause')},MIC_PAUSE)};
  for(const k of ['start','audiostart','soundstart','speechstart','speechend','soundend','audioend','nomatch'])rec['on'+k]=()=>{log(k);if(/^(audio|sound|speech)start$/.test(k))live();if(k==='speechstart'){hears();if(TK.ear===t)t.idle()}if(k==='speechstart'&&(t.gapAt||t.waited))t.spoke=true;if(k==='speechstart'&&TK.ear===t&&t.until&&!t.longer){t.longer=true;wait()}};
  /* B216: all the results, each time: a piece not yet final counts as heard, and an empty final or an empty list does not unsay it */
  rec.onresult=e=>{live();const was=parts, had=got;parts=[];let fin=0;got='';
    for(let i=0;i<e.results.length;i++){const x=e.results[i], w=x[0].transcript, p=parts[i]=x.isFinal&&!w.trim()?was[i]||'':w;
      if(x.isFinal)fin+=p.length;got+=(i&&e.results[i-1].isFinal&&got&&p&&!/\s$/.test(got)&&!/^\s/.test(p)?' ':'')+p}
    if(rec.continuous){got=holdHear(slots,e.results,Date.now()-heardAt,MIC_PAUSE);if(got!==had)heardAt=Date.now()}
    if(got.trim()){hears();goesOn()}else{got=had;parts=was}
    log(`result, ${got.length} letters${!fin?'':e.results[e.results.length-1].isFinal?', final':`, ${fin} final`}`);if(TK.ear===t){TK.heard=(t.words+' '+got).trim();t.idle();render(true)}};
  rec.onerror=e=>{t.err=e.error||'';t.msg=e.message||'';t.ms=Date.now()-at;log(`error ${t.err}${t.msg?': '+t.msg:''}`);if(TK.ear!==t)return;
    if(e.error==='not-allowed'||e.error==='service-not-allowed')toast('The browser did not let the page use the mic: allow it in the site settings, or type below.',true);
    else if(e.error==='recorded')toast(e.message+'.',true);
    else if(e.error!=='no-speech'&&e.error!=='aborted')toast(`The mic stopped: ${e.error}`,true)};
  rec.onend=()=>{
    log('end');if(t.ms==null)t.ms=Date.now()-at;
    if(TK.rec===rec)TK.rec=null;
    if(TK.ear!==t){micFree(rec);return soundAs('playback')}  // dropped: nothing is sent
    const said=!!got.trim();t.words=(t.words+' '+got).trim();
    const on=TK.state==='listening', go=on&&!t.stopped&&S.view==='talk'&&!S.thread&&!talkTyping()&&!document.hidden;
    /* B162a1: silence, or the recognizer's own end, never ends a hold: it starts again. An abort is silence too once the
       mic took sound or its message says so (iOS); one before that failed, and two in a row end the listen */
    const quiet=!t.err||t.err==='no-speech'||(t.err==='aborted'&&(t.on||/no speech/i.test(t.msg)));
    t.fails=quiet?0:t.fails+1;if(!t.stopped)t.failed=!quiet;
    const again=go&&TK.hold&&quiet, retry=go&&t.err==='aborted'&&(TK.hold?t.fails<2:(!t.words||t.kept)&&t.tries<2);
    /* B216: words and then a silence in a listen that is not held (nor auto listen): it listens on, and sends when
       MIC_PAUSE ms bring no more */
    if(said&&go&&!TK.hold&&t.mode!=='auto'&&(!t.err||t.err==='no-speech'||/no speech/i.test(t.msg))){
      log('a pause: listens on');t.longer=false;t.waited=true;wait()}
    const waits=go&&!TK.hold&&Date.now()<t.until&&(quiet||(t.err==='aborted'&&t.fails<2));
    const fall=go&&!!rec.falls;if(fall)t.noRec=true;  // F161b: no recording: the browser's recognition hears this listen
    const more=on&&t.more;
    if(said&&((go&&TK.hold)||more))t.gapAt=Date.now();  // B216a1: words to come are only heard by the next one
    if(more){t.more=t.stopped=false;t.tries=t.fails=0}
    if(on&&TK.hold&&(again||retry||more||fall)){t.again=t.again||again||more||(retry&&t.was);t.on=t.deaf=false;talkDraw()}  // B216a1: the mic is off until the next one's audiostart
    micFree(rec);
    if(again)log('still held: starts again');
    if(fall)micWhenFree(()=>hear(t));
    else if(more||((again||waits)&&(said||t.ms>=1000)))micWhenFree(()=>hear(t));  // B216: at once after words: what is said meanwhile is lost
    else if(again||waits||retry)setTimeout(()=>{if(TK.ear===t)micWhenFree(()=>hear(t))},MIC_RETRY);
    else earEnd(t);
  };
  soundAs('play-and-record');
  try{rec.start();cut()}catch(e){
    cut();log(`start failed: ${e.message||e}`);t.failed=true;
    /* B216a1: a restart the browser refused is tried once more */
    if(t.words&&!t.kept&&TK.ear===t&&!t.stopped&&(TK.hold||Date.now()<t.until)&&++t.fails<2){
      TK.rec=null;micFree(rec);setTimeout(()=>{if(TK.ear===t)micWhenFree(()=>hear(t))},MIC_RETRY);return}
    TK.report=t.trail;TK.ear=null;TK.rec=null;TK.state='';toast(`The mic could not start: ${e.message||e}`,true);render(true);micFree(rec);soundAs('playback');if(t.words)micSent(t,'a start that failed')}
}
/* B216: a listen's words go out; its mic report says what ended it. B216a1: not when the mic restarted after them and
   nothing was heard before the end: they may be half of what was said, so they are kept (TK.kept) and the talk line
   says so. The next listen goes on from them. Let go within MIC_GAP ms, with no speech begun, there was no time to say more.
   Tap's silence is its end (t.waited), so there only speech begun with no words, or a restart that failed, keeps them */
function micSent(t,why){
  clearTimeout(t.timer);
  if(t.kept||(t.gapAt&&(!t.stopped||t.spoke||t.failed||t.stopAt-t.gapAt>=MIC_GAP))||(t.waited&&(t.spoke||t.failed))){
    micLog(`kept ${t.words.length} letters, not sent: nothing heard after them, ended by ${why}`,false,t.trail,true);
    TK.kept=t.words;TK.report=t.trail;TK.heard='';  // the talk line has it, not TK.note: the mic report copies that
    return render(true);
  }
  TK.kept='';
  micLog(`sent ${t.words.length} letters, ended by ${why}`,false,t.trail,true);
  return talkSend(t.words);
}
/* B216a1: Send as it is */
function keptSend(){if(TK.kept&&!TK.state){const w=TK.kept;TK.kept='';unlockAudio();return talkSend(w)}}
/* the listen is over: its words go out, or the talk line says why there are none */
function earEnd(t){
  TK.ear=null;TK.heard='';if(TK.state==='listening')TK.state='';
  soundAs('playback');  // B178
  clearTimeout(t.timer);
  if(!t.words&&t.tries)PAST.none++;  // B162b1
  if(t.words){const sent=micSent(t,t.stopped?t.by:t.err?`error ${t.err}`:'the recognizer');if(TK.kept)PAST.none++;else PAST.words++;talkNext();return sent}  // B174: what waited is read now
  if(t.tries&&!(t.mode==='auto'&&(!t.err||t.err==='no-speech')))TK.report=t.trail;  // the Copy mic report button
  TK.note=t.mode==='auto'&&t.err!=='aborted'?(TS.mic==='hold'?'Hold to talk':'Tap to talk'):t.err==='recorded'?t.msg:t.tries?heardNothing(t.err,t.mode,t.ms,t.tries,t.stopped,t.was,t.msg):'';
  render(true);talkNext();
}
/* a hold the system took: the mic goes on, and stops at a silence */
function holdLost(){TK.hold=false;const t=TK.ear;if(t&&t.idle)t.idle();talkNext()}
/* the person ends the listen: the recognizer gives its last words, or a start still waiting is off */
function micStop(by){
  const t=TK.ear;if(!t)return;
  t.stopped=true;t.stopAt=Date.now();t.more=false;t.by=by;micLog(`stop by ${by}`);
  const rec=TK.rec;if(!rec)return earEnd(t);
  rec.stop();
  if(TK.rec===rec&&!rec.recorded)setTimeout(()=>{if(TK.rec===rec&&TK.ear===t&&t.stopped){micLog('no end came: ended by force');micWhenFree(()=>{})}},MIC_END);  // B162: else the listen never ends
}
/* B162: the mic report to the clipboard, or shown to copy by hand where that is refused */
async function micCopy(){
  const rep=TK.report||TK.trail;if(!rep)return;
  let au='';try{au=navigator.audioSession?`${navigator.audioSession.type}, ${navigator.audioSession.state||''}`:'none'}catch(e){}
  const text=micReport(rep,['Mic report',TK.note,`mic ${TS.mic}, version ${RUN_VERSION}, audio session ${au}, media session ${navigator.mediaSession?navigator.mediaSession.playbackState:''}`,navigator.userAgent,...(rep.past?[rep.past]:[])]);
  return micCopyText('Mic report',text);
}
async function micCopyText(title,text){
  try{await navigator.clipboard.writeText(text);toast(`${title} copied: paste it into your reply`)}
  catch(e){S.out={title,text};openSheet('out')}
}

