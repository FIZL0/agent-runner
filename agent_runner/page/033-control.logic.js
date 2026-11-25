/* B851a: a pressed run control shows its result in the same frame (docs/STYLE.md, Instant feedback). A press is
   {key, cid, n, at, want}: want, what the run is to say once it took it ({paused}, {stopping}, {forced} or {slots}).
   ctlHold lays the presses still waited for over the snapshot (the Run card's words, buttons, the state pill and Home's
   chip all draw from it), as obHide does for the cards: until a snapshot agrees, the press's outbox item failed, or
   CTL_HOLD ms pass, when it says so in a plain error. */
const CTL_HOLD=15000;
const CTL_MARK={pause:'Pausing…',go_on:'Going on…',force:'Forcing past the caps…',caps_on:'Caps going back on…',
  stop:'Stopping…',stop_undo:'Taking the stop back…',slot_add:'Adding a slot…',slot_remove:'Removing a slot…',slots_set:'Setting the slots…'};
/* what the press of `key` asks of the run in `snap` (null: nothing held for it); n, Set slots' count */
function ctlWant(key,snap,n){
  const r=(snap&&snap.run)||{}, s=+((snap&&snap.slots)||0);
  if(!snap||snap.up===false)return null;
  return {pause:{paused:true},go_on:{paused:false},force:{forced:true},caps_on:{forced:false},stop:{stopping:true},
    stop_undo:{stopping:false},slot_add:{slots:s+1},slot_remove:{slots:Math.max(s-1,0)},
    slots_set:/^\d+$/.test(String(n||''))?{slots:+n}:null}[key]||null;
}
const ctlRaw=snap=>snap.run&&snap.run._held?snap._raw:{run:snap.run||{},slots:snap.slots,card:snap.card,shown:snap.shown};
const ctlAgrees=(raw,w)=>Object.keys(w).every(k=>k==='slots'?+raw.slots===w.slots:!!raw.run[k]===w[k]);
/* the presses still held, and the error of one that ran out: {held, err}; obs, the outbox */
function ctlSettle(snap,presses,obs,now){
  const raw=ctlRaw(snap);let err='';
  const held=(presses||[]).filter(p=>{
    const x=(obs||[]).find(o=>o.cid===p.cid);
    if(x&&x.state==='failed')return false;  // its outbox card says so, with Retry
    if(ctlAgrees(raw,p.want))return false;
    if(now-p.at>=CTL_HOLD){err=`The run has not shown ${p.say||p.key} after ${CTL_HOLD/1000} s: this is what it says now.`;return false}
    return true});
  return{held,err};
}
/* snap with the held presses laid over it (snap itself is changed, its own values kept in _raw) */
function ctlHold(snap,held){
  const raw=ctlRaw(snap);
  if(!held.length){if(snap.run&&snap.run._held)Object.assign(snap,{run:raw.run,slots:raw.slots,card:raw.card,shown:raw.shown});delete snap._raw;return snap}
  const run={...raw.run}, out={slots:raw.slots};
  for(const p of held)for(const k of Object.keys(p.want))if(k==='slots')out.slots=p.want.slots;else run[k]=p.want[k];
  run.state=run.stopping?'Stopping':run.paused?'Paused':run.forced?'Caps forced':'Running';
  run.mark=CTL_MARK[held[held.length-1].key]||'';run._held=true;
  const heldCard=(raw.card||[]).map(k=>k==='pause'||k==='go_on'?(run.paused?'go_on':'pause'):k==='stop'||k==='stop_undo'?(run.stopping?'stop_undo':'stop'):k);
  const heldShown=(raw.shown||[]).map(k=>k==='force'||k==='caps_on'?(run.forced?'caps_on':'force'):k);
  return Object.assign(snap,{_raw:raw,run,slots:out.slots,card:heldCard,shown:heldShown});
}
