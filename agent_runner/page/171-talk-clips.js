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
