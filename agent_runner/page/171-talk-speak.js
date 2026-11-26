function unlockSpeech(){  /* Safari speaks later only after a first utterance inside a tap. Call it only in a real tap, after rec.start() (B132);
     B166a: the voice counts as unlocked only once that utterance started */
  soundAs('playback');unlockAudio();  // F158
  try{if(window.speechSynthesis&&!TK.unlocked){const u=new SpeechSynthesisUtterance('');u.volume=0;u.onstart=()=>{TK.unlocked=true};speechSynthesis.speak(u)}}catch(e){}
}
/* B166a: the last Talk reply, '' when there is none */
function talkLastReply(){const ms=talkMsgs(feedOf(talkName()||talkWas())).filter(m=>m.w==='a');return ms.length?plain(ms[ms.length-1].text):''}
/* B166a: the speaker's tap: stops a reading, reads a held reply, or turns read aloud on or off; on reads the last reply at once */
function speakerTap(){
  if(talkReads())return hush();
  if(TK.held&&!TK.ear&&TK.state!=='thinking')return speak(TK.held);  // the reading itself is the tap's utterance
  const on=!TS.read;talkSet('read',on);
  if(!on){unlockAudio();toast('Replies are not read aloud');return render(true)}
  const last=!TK.ear&&TK.state!=='thinking'&&!TK.wait?talkLastReply():'';
  if(last){unlockAudio();speak(last)}else{unlockSpeech();toast('Replies are read aloud');render(true)}  // no blank utterance ahead of a reply
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
    u.onstart=()=>{TK.unlocked=true;if(!w.begun)pastSound('voice');w.begun=true;w.quiet=0;w.at=Date.now();w.len=p.length;if(!i)log('started')};
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
/* B836: Talk was left (render() says so, whatever the way out): what is read stops and what waits to be read is
   dropped; their play buttons stay. No render() here, as one is under way */
function talkAway(){
  TK.later=[];
  if(!talkReads())return;
  if(TK.trail)micLog('sound: Talk was left');
  TK.playing='';if(TK.state==='speaking')TK.state=talkRest();TK.turn=(TK.turn||0)+1;shush();
}
addEventListener('pagehide',talkAway);  // B836: another project's page, or Home's: the browser's voice can outlive this one
/* a Talk reply's play button: reads that reply, or stops it */
function playReply(k){
  if(TK.playing===k)return hush();
  const n=talkName()||talkWas(), ms=talkMsgs(feedOf(n)), i=ms.findIndex((m,j)=>(m.k||n+':'+j)===k);
  if(i>=0)speak(plain(ms[i].text),k);
}
