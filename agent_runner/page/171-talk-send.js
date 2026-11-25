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
  const now=again&&!ear.on?'The mic is off, wait until it is on again':again&&ear.deaf?`Nothing is heard. Let go and press again${ear.gapAt||ear.kept?', these words are kept':''}`:TK.ear&&TK.ear.reading?'Getting the words…':TK.ear&&(!TK.ear.on||micOpening(TK.rec))?'Starting the mic…':'Listening…';
  /* B216a1: after a pause in a hold the mic can be off for a moment, so the line says when it is on again */
  line.textContent=why||(st==='listening'?(TK.heard?TK.heard+(TK.ear&&(TK.ear.gapAt||TK.ear.kept||(again&&!ear.on))?' … '+now:''):now):st==='thinking'?'Thinking…':st==='speaking'?'Speaking…':(TK.kept?`“${TK.kept.length>90?'…'+TK.kept.slice(-90):TK.kept}” Not sent: nothing was heard after these words. ${hold?'Hold':'Tap'} to go on from them, or send them as they are. `+TK.note:TK.note||(hold?'Hold to talk':'Tap to talk')+(open?', the mic is open, not listening':'')).trim());
  $('micrep').hidden=!!why||!!st||!TK.report;$('keptsend').hidden=!!st||!TK.kept;
  const label=why||(st==='listening'?'Stop listening':(hold?'Hold to talk':'Talk')+(open?', the mic is open, not listening':''));
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
  if(said&&!chatShown())w.away=true;  // B836: it landed while Talk was left, so it is not read, then or on the way back
  if(!said||said!==w.last){w.last=said;return}
  TK.wait=null;
  if(TK.state==='thinking')TK.state='';
  if(TS.read&&!w.away){TK.later.push(said);talkNext()}  // F124: else read replies aloud is off
  render(true);
}
