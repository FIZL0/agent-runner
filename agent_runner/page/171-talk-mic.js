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
  DK.rec=rec;DK.put=false;DK.key=boxKey();DK.base=ta.value;
  rec.lang=navigator.language||'en-US';rec.interimResults=true;rec.continuous=false;
  let final='', heard='';
  rec.onresult=e=>{let interim='';for(let i=e.resultIndex;i<e.results.length;i++){const x=e.results[i];if(x.isFinal)final+=x[0].transcript;else interim+=x[0].transcript}
    heard=final+interim;dictShow(heard)};
  rec.onerror=e=>{if(e.error==='not-allowed'||e.error==='service-not-allowed')toast('The browser did not let the page use the mic: allow it in the site settings, or type instead.',true);
    else if(e.error!=='no-speech'&&e.error!=='aborted')toast(`The mic stopped: ${e.error}`,true)};
  rec.onend=()=>{DK.rec=null;dictShow(final||heard);render(true);
    const t=document.querySelector('[data-in]');if(t&&boxKey()===DK.key&&!DK.put){t.focus({preventScroll:true});t.setSelectionRange(t.value.length,t.value.length)}micFree(rec);soundAs('playback')};
  render(true);
  micWhenFree(()=>{MIC.rec=rec;recFree();soundAs('play-and-record');try{rec.start()}catch(e){DK.rec=null;toast(`The mic could not start: ${e.message||e}`,true);render(true);micFree(rec);soundAs('playback')}},()=>{DK.rec=null});
}
/* F115: a chat's terminal colours are the run app's own tokens */
const TERM={mode:''};
