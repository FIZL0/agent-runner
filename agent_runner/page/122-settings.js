/* --- F202b: the Settings page's bar: changes collect in S.draft (draftParse and the rest in the logic script), kept per browser
   and shared by its tabs; Save writes them all, Undo drops them, and after a Save Undo puts the earlier values back ----------- */
const SETBAR_KEY='ar-setbar'+(HKEY?':'+HKEY:''), SETBAR={kept:true};  // kept: this browser stores it
Object.assign(S,{draft:{},setUndo:[]});
function draftLoad(){if(!SETBAR.kept)return;const x=draftParse(store.get(SETBAR_KEY));S.draft=x.draft;S.setUndo=x.undo}
function draftChange(fn){
  draftLoad();fn();
  const t=Object.keys(S.draft).length||S.setUndo.length?JSON.stringify({draft:S.draft,undo:S.setUndo}):'';
  store.set(SETBAR_KEY,t);SETBAR.kept=store.get(SETBAR_KEY)===t;S.draftLost=!SETBAR.kept&&!!Object.keys(S.draft).length;
}
const draftFields=()=>{for(const [f,d] of Object.entries(S.draft))if(!d.unset)S.f[f]=d.text};
draftLoad();draftFields();
/* the setting as it is once the change of it that is on its way is saved */
function settingSoon(k,side){
  const c=setGoing(settingId(k),side);if(!c)return k;
  const v=c.unset?resetValue(k,side):c.value;
  return{...k,['has_'+side]:!c.unset,[side]:v,value:v};
}
/* a change of setting `id` on `side`: d = {text} or {unset:true}; one that changes nothing leaves the draft */
function draftSet(id,side,d){
  const k=settingOf(id), f=setField(id,side), x={id,side,...d};if(!k)return;
  if(d.unset){delete S.f[f];delete S.f[otherField(id,side)]}
  draftChange(()=>{if(draftSame(settingSoon(k,side),x))delete S.draft[f];else S.draft[f]=x});
}
function draftDrop(f){draftChange(()=>{delete S.draft[f]})}
/* words typed in a row: the bar counts them at once; the view is drawn again once the field is left */
function draftType(el){
  const other=el.dataset.f.startsWith('setother:'), [,side,...rest]=el.dataset.f.split(':'), id=rest.join(':');
  if(other&&!el.value.trim())draftDrop(setField(id,side));
  else draftSet(id,side,{text:other?el.value.trim():el.value});
  setBarDraw();
}
/* the settings were read: changes that are there by now, or whose setting is gone, leave the draft */
function draftTidy(){
  const gone=Object.entries(S.draft).filter(([,d])=>{const k=settingOf(d.id);return !k||draftSame(settingSoon(k,d.side),d)}).map(([f])=>f);
  if(gone.length)draftChange(()=>{for(const f of gone)delete S.draft[f]});
}
const setLeave=()=>{const a=document.activeElement;if(a&&a.dataset&&a.dataset.f&&/^set(other)?:/.test(a.dataset.f))a.blur()};  // its last words are in first
function settingsUndrop(){
  setLeave();
  draftChange(()=>{for(const [f,d] of Object.entries(S.draft)){delete S.f[f];delete S.f[otherField(d.id,d.side)]}S.draft={}});
  render(true);
}
function settingsSave(){
  setLeave();draftLoad();
  const all=settingsAll(S.set), {changes,errs}=draftChanges(S.draft,all), bad=Object.keys(errs);
  if(bad.length){
    draftChange(()=>{for(const f of bad)if(S.draft[f])S.draft[f].err=errs[f]});
    toast(`${settingOf(S.draft[bad[0]].id).name}: ${errs[bad[0]]}`,true);render(true);return}
  if(!changes.length)return;
  const n=draftCount(S.draft,all);
  draftChange(()=>{S.draft={};S.setUndo=[]});  // the Undo offered is always the last Save's
  outbox('settings_save',{changes},{setbar:'save',n,say:`Save ${changeWords(n)} in Settings`});
}
function settingsUndo(){
  draftLoad();const n=undoCount(S.setUndo);if(!n)return;
  const changes=undoChanges(S.setUndo), was=S.setUndo;
  draftChange(()=>{S.setUndo=[]});
  outbox('settings_save',{changes},{setbar:'undo',n,was,say:`Undo ${changeWords(n)} in Settings`});
}
function setUndoClose(){draftChange(()=>{S.setUndo=[]});render(true)}
/* the run answered a Save or an Undo: what it did not take is in the bar again, with why. An older run's refusal is the outbox's */
function settingsDone(it,j){
  const ok=!!(j&&j.ok), sent=it.args.changes, bad=(j&&j.bad)||(ok?[]:sent.map(c=>({...c,why:String((j&&j.out)||'it did not work').split('\n')[0]})));
  const at=c=>setField(`${c.table}.${c.key}`,c.side), lost=new Map(bad.map(b=>[at(b),b]));
  if(!ok)obChange(b=>obDrop(b,it.cid));
  draftChange(()=>{
    if(it.setbar==='undo'){const left=it.was.filter(x=>lost.has(at(x))&&!lost.get(at(x)).changed);if(left.length)S.setUndo=left;return}
    if(((j&&j.was)||[]).length)S.setUndo=j.was;
    for(const c of sent){const f=at(c), b=lost.get(f);if(!b||S.draft[f])continue;
      S.draft[f]={id:`${c.table}.${c.key}`,side:c.side,...(c.unset?{unset:true}:{text:settingText(c.value),set:true}),err:b.why}}
  });
  draftFields();
  const was=Object.fromEntries(sent.map(c=>[at(c),S.f[at(c)]]));
  loadSettings().then(()=>{  // the fields show what is kept again
    for(const c of sent){const f=at(c);if(!S.draft[f]&&S.f[f]===was[f]){delete S.f[f];delete S.f[otherField(`${c.table}.${c.key}`,c.side)]}}
    render(true)});
  const say=bad.length?bad[0].why:j.say||(it.setbar==='undo'?`${changeWords(it.n)} put back`:S.setUndo.length?'':'Saved');  // a Save's own words are the bar's
  if(say)toast(String(say).split('\n')[0],!!(bad.length||j.warn));
}
/* what the bar says: changes not saved, else a Save or Undo on its way, else the Undo of the last Save; '' for none */
function setBarHTML(){
  if(!S.set||!S.set.tables)return '';
  const n=draftCount(S.draft,settingsAll(S.set)), its=S.ob.filter(x=>x.setbar), it=its.filter(x=>x.state!=='failed').pop(), bad=its.filter(x=>x.state==='failed');
  const row=(words,btns,live)=>`<div class="row">${live?'<span class="livedot"></span>':''}<span class="grow" role="status">${words}</span><div class="btns">${btns}</div></div>`;
  const going=it=>row(`${it.setbar==='undo'?'Undoing':'Saving'} ${changeWords(it.n)}: ${esc(obState(it))}`,it.state==='failed'?obBtns(it):'',it.state!=='failed'), lost=bad.map(going).join('');
  if(n)return lost+row(`${changeWords(n)} not saved${draftSides(S.draft)?`: ${draftSides(S.draft)}`:''}`,'<button class="btn" data-setdrop>Undo</button><button class="btn acc" data-setall>Save</button>');
  if(it||lost)return lost+(it?going(it):'');
  const u=undoCount(S.setUndo), waits=u?loginWaits(S.setUndo,loginsNow(S.set,S.logins),baseProvider()):'';
  return u?row(`${changeWords(u)} saved${waits?`. ${esc(waits)}`:''}`,`<button class="btn" data-setundo>Undo</button><button class="icon" data-setundox aria-label="Close" title="Close">${I.x}</button>`):'';
}
function setBarDraw(){
  const el=$('setbar'), h=!HOME_PAGE&&!S.thread&&S.view==='settings'?setBarHTML():'', was=el.hidden;
  el.hidden=!h;
  if(setHTML(el,h)&&h&&was&&S.live)moAnim(el,[{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'none'}],{ease:'--ease',dur:'--dur'});
  loopsInStep(el);
}
document.addEventListener('click',e=>{
  const q=s=>e.target.closest&&e.target.closest(s);
  if(q('[data-setall]'))settingsSave();
  else if(q('[data-setdrop]'))settingsUndrop();
  else if(q('[data-setundo]'))settingsUndo();
  else if(q('[data-setundox]'))setUndoClose();
});
addEventListener('storage',e=>{  // another tab
  if(e.key!==SETBAR_KEY)return;
  const was=S.draft;draftLoad();
  for(const f of Object.keys(was))if(!S.draft[f])delete S.f[f];
  draftFields();
  if(S.set&&S.view==='settings')loadSettings();else render(true);
});
/* --- F460a: Settings > Plan: "Share the plan between machines" moves the plan to a repo of its own (the URL field: where; empty:
   the runner's choice) by `plan_share`, and shows what it said, the last line being what the other machine runs ------------ */
Object.assign(S,{planShare:null});  // null, {going:true}, or planShareView()
function planShareHTML(){
  const r=S.planShare, going=!!(r&&r.going);
  const said=r&&!going?`${r.lines.map(x=>`<div class="small${r.err?' v-bad':''}">${esc(x)}</div>`).join('')}${r.cmd?`<div class="small">On the other machine, run:</div><div class="row"><code class="grow">${esc(r.cmd)}</code></div>`:''}`:'';
  return `<div class="sec">Plan<span class="ln"></span></div>${card(`<div class="row"><input class="fld grow" data-f="planshare" placeholder="Plan repo URL (empty: made for you)" aria-label="Plan repo URL"><button class="btn" data-planshare${going?' disabled':''}>${going?'Sharing…':'Share the plan between machines'}</button></div>${said}`,'','data-k="sett:planshare"')}`;
}
async function planShare(){
  if(S.planShare&&S.planShare.going)return;
  S.planShare={going:true};render(true);
  let j;
  try{const r=await fetch(tq('act'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'plan_share',args:{target:String(S.f.planshare||'').trim()}})});j=await r.json()}
  catch(e){j={ok:false,out:`Not sent: ${e.message||e}`}}
  S.planShare=planShareView(j);render(true);
}
document.addEventListener('click',e=>{if(e.target.closest&&e.target.closest('[data-planshare]'))planShare()});
