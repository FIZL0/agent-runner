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
  const t=TK.ear={mode:again?'auto':TS.mic,tries:0,words:TK.kept||'',kept:!!TK.kept,gapAt:0,waited:false,failed:false,stopAt:0,spoke:false,again:false,deaf:false,idle:null,err:'',ms:null,stopped:false,more:false,on:false,was:false,fails:0,msg:'',by:'',early:false,onAt:0,until:0,timer:0,longer:false,cut:cut&&!MIC.rec};
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
  t.reading=false;MIC.rec=TK.rec=rec;t.tries++;t.err=t.msg='';t.ms=null;t.on=t.deaf=t.early=false;t.late=false;talkDraw();
  rec.lang=navigator.language||'en-US';rec.interimResults=true;rec.continuous=TK.hold&&!rec.recorded;
  /* B216a1: one recognizer stays through a Hold's pauses, for the next one may hear nothing (iOS); should it end all the
     same, it is started again as before */
  micLog(`try ${t.tries}${rec.recorded?'':rec.continuous?', continuous':', not continuous'}`);
  const log=x=>micLog(x,false,t.trail);  // a dropped one's late events stay in its own report
  const at=Date.now();let parts=[], got='', begun=false, slots=[], heardAt=at, opened=false;
  const live=()=>{t.failed=false;if(!t.on&&TK.ear===t){t.on=t.was=true;t.onAt=Date.now();talkDraw();if(t.again)setTimeout(deaf,MIC_DEAF)}};  // the mic takes sound: now is the time to speak
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
  for(const k of ['start','audiostart','soundstart','speechstart','speechend','soundend','audioend','nomatch'])rec['on'+k]=()=>{log(k);if(k==='start'&&rec.recorded){if(opened)t.late=true;opened=true;t.on=false;talkDraw()}if(/^(audio|sound|speech)start$/.test(k))live();if(k==='speechstart'){hears();if(TK.ear===t)t.idle()}if(k==='speechstart'&&(t.gapAt||t.waited))t.spoke=true;if(k==='speechstart'&&TK.ear===t&&t.until&&!t.longer){t.longer=true;wait()}};
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
    if(on&&TK.hold&&!rec.recorded&&(again||retry||more||fall)){t.again=t.again||again||more||(retry&&t.was);t.on=t.deaf=false;talkDraw()}  // B216a1: the mic is off until the next one's audiostart
    micFree(rec);
    if(again)log('still held: starts again');
    if(fall)micWhenFree(()=>hear(t));
    else if(more||((again||waits)&&(said||t.ms>=1000)))micWhenFree(()=>hear(t));  // B216: at once after words: what is said meanwhile is lost
    else if(again||waits||retry)setTimeout(()=>{if(TK.ear===t)micWhenFree(()=>hear(t))},MIC_RETRY);
    else earEnd(t);
  };
  soundAs('play-and-record');
  try{rec.start();t.late=!!rec.recorded&&!rec.on;cut()}catch(e){
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
  TK.note=t.mode==='auto'&&t.err!=='aborted'?(TS.mic==='hold'?'Hold to talk':'Tap to talk'):t.err==='recorded'?t.msg:t.tries?heardNothing(t.err,t.mode,t.ms,t.tries,t.stopped,t.was,t.msg,t.early):'';
  render(true);talkNext();
}
/* a hold the system took: the mic goes on, and stops at a silence */
function holdLost(){TK.hold=false;const t=TK.ear;if(t&&t.idle)t.idle();talkNext()}
/* the person ends the listen: the recognizer gives its last words, or a start still waiting is off */
function micStop(by){
  const t=TK.ear;if(!t)return;
  t.stopped=true;t.stopAt=Date.now();t.more=false;t.by=by;micLog(`stop by ${by}`);
  const rec=TK.rec;t.early=micEarly(t,rec,by);if(!rec)return earEnd(t);
  rec.stop();
  if(TK.rec===rec&&!rec.recorded)setTimeout(()=>{if(TK.rec===rec&&TK.ear===t&&t.stopped){micLog('no end came: ended by force');micWhenFree(()=>{})}},MIC_END);  // B162: else the listen never ends
}
/* B216b1: which page is open, and the one the run serves: an open page not reloaded since a fix is told apart */
function micPage(){
  const mine=PAGE_PRINT.startsWith('/*')?'':PAGE_PRINT, run=S.snap&&S.snap.page||'';
  return `open page ${mine||'not known'}${!run?', the run\'s page not known':!mine?`, the run's page ${run}`:run===mine?", the same as the run's":`, not the run's (${run}): not reloaded since it changed`}`;
}
/* B162: the mic report to the clipboard, or shown to copy by hand where that is refused */
async function micCopy(){
  const rep=TK.report||TK.trail;if(!rep)return;
  let au='';try{au=navigator.audioSession?`${navigator.audioSession.type}, ${navigator.audioSession.state||''}`:'none'}catch(e){}
  const text=micReport(rep,['Mic report',TK.note,`mic ${TS.mic}, the run's version ${RUN_VERSION}, ${micPage()}, audio session ${au}, media session ${navigator.mediaSession?navigator.mediaSession.playbackState:''}`,navigator.userAgent,...(rep.past?[rep.past]:[])]);
  return micCopyText('Mic report',text);
}
async function micCopyText(title,text){
  try{await navigator.clipboard.writeText(text);toast(`${title} copied: paste it into your reply`)}
  catch(e){S.out={title,text};openSheet('out')}
}

