/* why the mic cannot listen here ('' when it can): Chrome gives the mic only to https or localhost; B130: Safari
   hides speech recognition outside a secure context, so plain http is checked first */
function micProblem(secure,hasRecognition){
  if(!secure)return 'The mic needs https or localhost, and this address is plain http: open the https link (run status prints it when Tailscale Serve gives one). Type below instead.';
  if(!hasRecognition)return 'This browser cannot turn speech into text (Chrome, Edge and Safari can). Type below instead.';
  return '';
}
/* F115: dictation in the message box: why its mic cannot listen ('' when it can), as micProblem says for Talk */
const dictProblem=(secure,hasRecognition)=>micProblem(secure,hasRecognition).replace('Type below instead.','Type your message instead.');
/* the mic button beside attach: `why` (dictProblem) keeps it tappable, to say why; `on` while it listens */
function dictButton(why,on,icon){
  const e=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const label=why||(on?'Stop dictating':'Dictate: your words go into the box to edit');
  return `<button type="button" class="tool dict${on?' on':''}${why?' off':''}" data-dict aria-pressed="${!!on}" aria-label="${e(label)}" title="${e(label)}">${icon||''}</button>`;
}
/* the box's words while dictating: what it held when the mic started, then the words heard */
function dictInsert(draft,words){
  const d=String(draft||''), w=String(words||'').trim();
  if(!w)return d;
  return d.trim()?d.replace(/\s+$/,'')+' '+w:w;
}
/* B132: the talk line after a listen that ended with no words, naming the last error the recognizer gave */
/* B162: with how the mic was started (tap, hold, auto) and how long it ran before the error; a mic cut off
   ('aborted') gets what to try, in plain words, unless the person stopped it */
function heardNothing(err,mode,ms,tries,stopped,on,msg){
  const d=(msg?': '+msg:'')+[mode||'',ms==null?'':`after ${(ms/1000).toFixed(1)} s`,tries>1?`${tries} tries`:''].filter(Boolean).map(x=>', '+x).join('');
  if(!err){const x=d?` (${d.slice(2)})`:'';return stopped&&on===false?`${MIC_EARLY}.${x}`:`Heard nothing${x}`}
  if(err==='aborted'&&!stopped)return `The mic was cut off before it heard anything. Stop any other app that uses sound or the mic, then try again. (${err}${d})`;
  if(err==='aborted')return `${on===false?MIC_EARLY:'The mic was on, but no words reached it before it was stopped. Stop any other app that uses sound or the mic, then try again'}. (${err}${d})`;
  return `Heard nothing (error: ${err}${d})`;
}
const MIC_EARLY='The mic was stopped before it was on. Allow it if the browser asks, wait until this line says Listening…, then speak';
/* B162: the mic report: what happened from the press on the mic to its end, each with its ms. WebKit's 'aborted' is
   any failure of the system's recognizer (silence too), and only the error's message tells them apart; a stop before
   its start gives an end with no error. Words heard are counted, not kept. B216: a run of growing results is one line,
   the newest; must: the line goes in a full report too */
function micLog(what,fresh,own,must){
  if(!own&&(fresh||!TK.trail))TK.trail={at:Date.now(),ev:[],more:0,past:micPast()};
  const t=own||TK.trail;
  const ev=`${Date.now()-t.at} ms ${what}`, grows=/ ms result, \d+ letters(, \d+ final)?$/;
  if(grows.test(ev)&&grows.test(t.ev[t.ev.length-1]||''))t.ev[t.ev.length-1]=ev;
  else if(must||t.ev.length<120)t.ev.push(ev);else t.more++;
}
/* B178: what the sound is for, where the browser lets a page say (iOS): 'play-and-record' for the mic, which puts
   Bluetooth earbuds in the hands-free profile, 'playback' once no mic is on or about to be */
function soundAs(type){
  try{const a=navigator.audioSession;if(!a||a.type===type||(type==='playback'&&(MIC.rec||MIC.next||TK.ear)))return;
    a.type=type;micLog(`audio session ${type}, ${a.state||''}`)}catch(e){}
}
/* B166: a run voice reads, or may once the run has said which it has */
const audioWanted=()=>!!(AU.got?runVoice(AU.got,TS.voice):TS.voice!=='system');
/* B166: in the press that starts the mic, after rec.start(): the audio elements load the silent clip and play nothing, for
   Safari lets one play later whose load() a tap called. So a listen that ends with no second tap has had its tap too */
function audioReady(){
  if(AU.ok||!audioWanted())return;
  try{audioSrc(new Blob([silentWav()],{type:'audio/wav'})).load();holdEl().load()}catch(e){}
}
/* B174: a reply is read now, by itself or by its play button; and what Talk's state is once nothing is read */
const talkReads=()=>TK.state==='speaking'||!!TK.playing, talkRest=()=>TK.wait?'thinking':'';
/* B174: the replies that landed while the mic was on (or another was read), played in order once it has ended */
function talkNext(){
  if(!TK.later||!TK.later.length)return;
  if(!TS.read){TK.later=[];return}
  if(!(TK.ear||TK.hold||MIC.rec||MIC.next||TK.held||talkReads()))speak(TK.later.shift());
}
/* B174: iOS can skip a sound's last event, so a look each second while a reply is read ends one that makes no sound.
   w: turn, the reply's TK.turn; own, the browser's voice reads; clip, the element that plays a clip; at, the last sign
   of sound, and len, the letters the browser's voice is at; begun, heard at all; hid, the page was hidden; end(e) */
const SOUND_LOOK=1000, SOUND_LIMIT=10000;
function soundWatch(w){TK.watch=w;setTimeout(()=>soundCheck(w,true),SOUND_LOOK)}
function soundCheck(w,more){
  if(TK.watch!==w||TK.turn!==w.turn||!talkReads())return;
  if(more)setTimeout(()=>soundCheck(w,true),SOUND_LOOK);
  const ss=window.speechSynthesis, a=w.clip, late=Date.now()-w.at>SOUND_LIMIT+(w.own&&ss.speaking?200*w.len:0);
  if(w.own){
    const quiet=ss.paused||!(ss.speaking||ss.pending);
    w.quiet=quiet?w.quiet+1:0;
    if(!late&&w.quiet<(w.begun?2:4))return;
    if(TK.trail)micLog(`sound: the browser's own voice ${w.begun?'ended, with no event':'never started'}`);
    const ok=quiet&&w.begun&&!w.hid&&!ss.paused;  // read to its end: auto listen may follow, so no speechSynthesis call (B132)
    if(!ok)ss.cancel();
    w.end(ok?null:{type:'error'});
  }else if(a){
    if(a.ended){if(a.onended)a.onended()}
    else if(a.error){if(a.onerror)a.onerror()}
    else if(a.paused){if(++w.quiet>1){if(TK.trail)micLog('sound: the clip stays paused');hush(true)}}
    else if(a.currentTime!==w.spot){w.spot=a.currentTime;w.at=Date.now();w.quiet=0}
    else if(late){if(TK.trail)micLog('sound: the clip stands still');hush(true)}
  }
}
/* the page was hidden, or shows again: look at once, with 3 s left for a sound that goes on */
function soundSeen(hidden){
  const w=TK.watch;if(!w)return;
  if(hidden){w.hid=true;return}
  w.at=Math.max(w.at,Date.now()-SOUND_LIMIT+3000);soundCheck(w);
}
/* B178: an error in plain words: a fetch with no answer is 'Load failed' in Safari, 'Failed to fetch' elsewhere */
const plainErr=e=>e&&((e.name==='TypeError'&&/load failed|fetch|network|connection|offline|cancelled|hostname|timed out/i.test(e.message))||e.name==='NetworkError'||e.name==='AbortError')?'no connection':e&&e.name==='SyntaxError'?'its answer made no sense':String((e&&e.message)||e);
const micReport=(t,head)=>[...head,...t.ev,...(t.more?[`and ${t.more} more`]:[])].join('\n');
/* a Talk message as the person said it: without the first message's brief or a later one's reminder */
const talkShown=t=>{t=String(t||'');const i=t.indexOf('\n\nThey said: ');
  return (/^Talk mode:/.test(t)&&i>=0?t.slice(i+13):t.replace(/^\(Talk: [^)]*\) /,'')).trim()};
/* the reply to read aloud: the session's words after `mark` (feedMark at the send; a number is an index), once its
   last entry is its words ('' while it still works or has said nothing new). said: the person's words, for a send
   with no mark */
function talkReply(entries,mark,said){
  const es=feedAfter(entries,mark===undefined?0:mark,said);
  if(!es.length||es[es.length-1].kind!=='say')return '';
  return es.filter(e=>e.kind==='say').map(e=>plain(e.text)).join(' ').trim();
}
/* F118: the chats picked for delete after a click on `name`: `names` the chats in list order, `sel` those picked,
   `last` the last one clicked, `how` 'toggle' (Ctrl/Cmd+click: in or out), 'range' (Shift+click: every chat from
   `last` to `name`), else a plain click (nothing picked, `name` the new last). */
function chatPick(names,sel,last,name,how){
  names=names||[];const ok=n=>names.includes(n);
  const order=s=>names.filter(n=>s.has(n));
  let s=new Set((sel||[]).filter(ok));
  if(how==='range'&&names.includes(name)&&names.includes(last)){
    const [a,b]=[names.indexOf(last),names.indexOf(name)].sort((x,y)=>x-y);
    return{sel:order(new Set(names.slice(a,b+1).filter(ok))),last};
  }
  if(how==='toggle'||how==='range'){if(ok(name)){s.has(name)?s.delete(name):s.add(name)}return{sel:order(s),last:name}}
  return{sel:[],last:name};
}
/* F133: the Chats list once `name` is dropped at place `to` (counted without it); pinned chats (`pins`) stay first */
