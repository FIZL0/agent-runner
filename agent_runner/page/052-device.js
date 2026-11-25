/* B818a: Device Vitals in the app: a device opens as a page under Devices, from its Home's /vitals/device.
   Which one is open is H.dev, and stands in the history entry (level, tab, dev), so Back and a reload keep the place.
   B818b: DV.pick is Clean's open tick list, the list as it was when it opened and what is ticked, so a refresh changes
   neither; DV.act is the press being answered (busy) and what the last one's answer said, by section */
const devActs=()=>({busy:'',said:{}});
const DV={d:null,err:'',busy:false,turn:0,more:{},pick:null,act:devActs()};
H.dev='';
const devOn=()=>atAll()&&H.tab==='devices'&&H.dev||'';
const devHere=h=>({level:'all',tab:H.tab,...(h?{dev:h}:{})});
function devSet(id){if(id!==H.dev){DV.d=null;DV.err='';DV.more={};DV.pick=null;DV.act=devActs()}H.dev=id;if(devOn())devLoad()}
function devOpen(id){
  H.tab='devices';tabStore.set('ar-alltab',H.tab);S.drawer=false;
  try{history.replaceState(devHere(),'');history.pushState(devHere(id),'')}catch(e){}
  devSet(id);render(true);
}
/* a tab of All projects was pressed: Devices is the way back, for another the history entry is that tab's now */
function devLeave(){if(H.dev&&H.tab==='devices')return devBack();devSet('');try{if(history.state&&'tab' in history.state)history.replaceState(devHere(),'')}catch(e){}}
function devBack(){
  if(history.state&&history.state.dev&&history.state.dev===H.dev){history.back();return}
  devSet('');render(true);
}
/* the tab and device a history entry names, on Back, Forward or a load */
function devPlace(st){
  if(!atAll()||!st||st.level!=='all')return;
  if('tab' in st){H.tab=st.tab||'';tabStore.set('ar-alltab',H.tab)}
  devSet(st.dev||'');render(true);
}
/* Home's own page at #device-ID, where an old /device?id= link leads: that device; the # goes, so a reload keeps the place */
function devLink(){
  const m=HOME_PAGE&&!HKEY&&/^#device-(.+)$/.exec(location.hash);if(!m)return false;
  let id=m[1];try{id=decodeURIComponent(id)}catch(e){}
  try{history.replaceState(history.state,'',location.pathname+location.search)}catch(e){}
  devOpen(id);return true;
}
/* a press on the open device, sent once: a resend could run it twice. Its answer stands in section `sec`; one that comes
   after the page has left that device is a toast */
async function devPost(sec,key,path,body){
  const a=DV.act;if(a.busy)return null;
  a.busy=key;a.said={};render(true);let j;
  try{j=await (await fetch(tq(HB+'dev/'+encodeURIComponent(H.dev)+path),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json()}
  catch(e){j={ok:false,out:`Could not reach Runner Home: ${plainErr(e)}`}}
  a.busy='';const said=j.out||(j.ok?'Done':'That did not work');
  if(a!==DV.act){toast(said.split('\n')[0],!j.ok);return null}
  a.said={[sec]:{text:said,bad:!j.ok}};return j;
}
async function devSlot(key){const j=await devPost('room','slot:'+key,'/act',{project:key,name:'slots',arg:'+1'});if(j){render(true);devLoad()}}
async function devClean(how){
  if(DV.act.busy)return;
  if(how==='list'){const l=DV.d&&DV.d.clean||[];DV.act.said={};DV.pick={list:l,on:new Set(l.filter(i=>!i.ask).map(i=>i.id))}}
  const p=DV.pick, ids=p?p.list.map(i=>i.id).filter(id=>p.on.has(id)):[];
  if(how==='cancel'||how==='go'&&!ids.length)DV.pick=null;
  else if(how==='go'){
    const j=await devPost('foot','clean','/vitals/clean',{items:ids});if(!j)return;
    if(j.removed)DV.pick=null;  // answered; else the ticks stay to press again
    devLoad();
  }
  render(true);
}
/* the box is ticked already: a redraw now would take it from under the finger */
function devTick(id,on){if(DV.pick)DV.pick.on[on?'add':'delete'](id)}
const devSaid=sec=>{const s=DV.act.said[sec];return s?`<div class="small devsaid"><span${s.bad?' class="v-bad"':''}>${esc(s.text)}</span></div>`:''};
const devBtn=(attr,key,label,c='')=>{const b=DV.act.busy;return `<button class="btn${c}${b&&b===key?' busy':''}" ${attr}${b?' disabled':''}>${label}</button>`};
function devSlots(d){
  const l=d.running||[];
  return (l.length?`<div class="btns">${l.map(r=>devBtn(`data-devslot="${esc(r.key)}"`,'slot:'+r.key,'+ slot'+(l.length>1?' · '+esc(r.key):''))).join('')}</div>`:'<div class="small">No run up on this device to add a slot to.</div>')+devSaid('room');
}
function devCleanHTML(d){
  const l=d.clean||[], p=DV.pick;
  if(!p)return (l.length?`<div class="btns">${devBtn('data-devclean="list"','',`Clean ${sizeWords(l.filter(i=>!i.ask).reduce((n,i)=>n+i.size,0))} safely…`)}</div>`:'<div class="small">Nothing to clean.</div>')+devSaid('foot');
  return `<div class="small">Clean removes only what you tick:</div>${p.list.map(i=>`<label class="devtick"><input type="checkbox" data-devtick="${esc(i.id)}" data-f="devtick:${esc(i.id)}"${p.on.has(i.id)?' checked':''}${DV.act.busy?' disabled':''}><span>${esc(i.path)} <span class="small">· ${esc(i.why)}${i.size?' · '+sizeWords(i.size):''}</span></span></label>`).join('')}<div class="btns">${devBtn('data-devclean="go"','clean','Remove ticked',' bad')}${devBtn('data-devclean="cancel"','','Cancel')}</div>${devSaid('foot')}`;
}
async function devLoad(){
  const id=H.dev, turn=++DV.turn;if(!HB||!id)return;
  DV.busy=true;let d=null,err='';
  try{d=await (await fetch(tq(HB+'dev/'+encodeURIComponent(id)+'/vitals/device'))).json()}
  catch(e){err=`Could not reach Runner Home: ${plainErr(e)}`}
  if(turn!==DV.turn)return;  // another device, or a newer ask
  if(d&&!d.ok&&!d.id){err=d.out||'The device could not be read.';d=null}  // Home's own refusal: a device's answer has its id
  DV.busy=false;DV.err=err;if(d)DV.d=d;
  render();
}
const devListed=()=>(H.devices||[]).find(x=>x.id===H.dev)||{};
const devName=()=>DV.d&&DV.d.host||devListed().host||'Device';
const devBackBtn=()=>devOn()?`<button class="icon" data-devback aria-label="Back to Devices" title="Back to Devices">${I.back}</button>`:'';
const allTitle=()=>devOn()?`<span class="tt">${esc(devName())}</span>`:H.tab==='devices'?'Devices':'Overview';
const GIB=1073741824;
const sizeWords=n=>n==null?'':n>=GIB*1024?(n/GIB/1024).toFixed(1)+' TB':n>=GIB?(n/GIB).toFixed(1)+' GB':n>=1048576?(n/1048576).toFixed(0)+' MB':(n/1024).toFixed(0)+' KB';
/* a meter, with no bar where the machine reads no share */
const devMeter=(name,pct,said)=>pct==null?`<div class="meter"><span>${esc(name)}</span><span></span><span class="r">${esc(said)}</span></div>`:meterHTML({name,pct,said});
function sparkHTML(v){
  const pts=(v||[]).map((x,i)=>x==null?null:[i,x]).filter(Boolean);if(pts.length<2)return '';
  const lo=Math.min(...pts.map(p=>p[1])), span=Math.max(...pts.map(p=>p[1]))-lo||1;
  return `<svg class="spark" viewBox="0 0 ${v.length-1} 28" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts.map(p=>p[0]+','+(26-24*(p[1]-lo)/span).toFixed(1)).join(' ')}"/></svg>`;
}
const devRows=l=>l.map(([a,b])=>`<div class="lrow"><span>${esc(a)}</span><span class="small">${esc(b)}</span></div>`).join('');
function devSec(id,title,inner,more){
  const on=!!DV.more[id];
  return `<div class="sec">${title}<span class="ln"></span></div>${card(`${inner}${more?`<div class="btns"><button class="btn" data-devmore="${id}" aria-expanded="${on}">${on?'Less':'More'}</button></div>${on?`<div class="foldin">${more}</div>`:''}`:''}`,'devcard',`data-k="dev:${id}"`)}`;
}
function devMachine(d){
  const m=d.machine||{}, sp=d.spark||{}, c=m.cpu, out=[], say=(...l)=>l.filter(Boolean).join(' · ');
  if(c){
    out.push(devMeter('CPU',c.pct,say(c.pct!=null&&c.pct.toFixed(0)+'%',c.threads&&c.threads+' threads',c.load!=null&&'load '+c.load))+sparkHTML(sp.cpu));
    if(c.temp!=null)out.push(devMeter('Temp',c.temp,c.temp.toFixed(0)+'°C')+sparkHTML(sp.temp));
  }
  (m.gpus||[]).forEach((g,i)=>{
    out.push(devMeter('GPU',g.pct,say(g.pct!=null&&g.pct.toFixed(0)+'%',i&&g.temp!=null&&g.temp.toFixed(0)+'°C',g.vram_total&&sizeWords(g.vram_used)+' / '+sizeWords(g.vram_total)))+`<div class="small">${esc(g.name)}</div>`+(i?'':sparkHTML(sp.gpu)));
    if(!i&&g.temp!=null)out.push(devMeter('GPU temp',g.temp,g.temp.toFixed(0)+'°C')+sparkHTML(sp.gtemp));
  });
  if(m.mem)out.push(devMeter('Memory',100*(m.mem.total-m.mem.avail)/m.mem.total,sizeWords(m.mem.total-m.mem.avail)+' / '+sizeWords(m.mem.total))+sparkHTML(sp.mem));
  if(m.disk)out.push(devMeter('Disk',100*(1-m.disk.free/m.disk.total),sizeWords(m.disk.free)+' free')+`<div class="small">${esc(m.disk.path)} · free GB, last 24 h</div>`+sparkHTML(sp.disk));
  const part=(t,h)=>`<div class="small">${t}</div>${h}`;
  const more=(c&&c.cores?part('Per core',c.cores.map((p,i)=>devMeter(i,p,p.toFixed(0)+'%')).join('')):'')
    +(m.sensors?part('All sensors',devRows(m.sensors.map(s=>[s.chip+' · '+s.label,s.c.toFixed(0)+'°C']))):'')
    +(m.top?part('Top processes',devRows(m.top.map(p=>[`${p.name} (${p.pid})`,p.cpu.toFixed(1)+'% · '+sizeWords(p.rss)]))):'');
  return devSec('machine','Machine',out.join('')||'<div class="small">Nothing here could be read.</div>',more);
}
function devFoot(d){
  const f=d.footprint||{}, rows=[['Worktrees (run homes)',f.worktrees],['Session temp folders',f.tmp],['Logs',f.logs]].filter(r=>r[1]!=null).map(([a,n])=>[a,sizeWords(n)]);
  if(f.wip)rows.push(['wip/ branches',String(f.wip.length)]);
  return devSec('foot',`Runner footprint${f.total!=null?' · '+sizeWords(f.total):''}`,(rows.length?devRows(rows):'<div class="small">Not measured yet.</div>')+devCleanHTML(d),
    (f.largest||[]).length?`<div class="small">Largest folders</div>${devRows(f.largest.map(x=>[x.path,sizeWords(x.size)]))}`:'');
}
function devHTML(){
  const d=DV.d, retry=`<div class="btns"><button class="btn${DV.busy?' busy':''}" data-devload>Retry</button></div>`;
  const err=DV.err?card(`<div class="small"><span class="v-bad">${esc(DV.err)}</span></div>${retry}`):'';
  if(!d)return `<div class="col">${err||emptyCard('Loading…')}</div>`;
  if(!d.ok){const l=devListed(), said=d.verdict&&d.verdict.said||l.ok===false&&l.verdict&&l.verdict.said||'Not answering';
    return `<div class="col">${err}${card(`<b>${esc(devName())}</b><div class="v-bad">${esc(said)}</div>${d.out?`<div class="small">${esc(d.out)}</div>`:''}${err?'':retry}`,'','data-k="dev:not"')}</div>`}
  const v=d.verdict||{}, h=d.headroom||{}, ss=d.sessions||[];
  return `<div class="col">${err}${card(`<div><b>${esc(d.host)}</b>${d.here&&H.dev==='local'?' <span class="small">· this one</span>':''}</div><div class="v-${esc(v.level)}">${esc(v.said)}</div>`,'','data-k="dev:said"')}${
    devSec('room','Headroom',`<b>${esc(h.said||'')}</b><div class="small">Smallest of: ${esc(Object.entries(h.limits||{}).map(([k,n])=>`${k} ${n}`).join(' · '))} (at most 6)</div>${devSlots(d)}`)}${
    devMachine(d)}${devFoot(d)}${
    devSec('sess','Sessions',ss.length?devRows(ss.map(s=>[s.project+' '+s.name+(s.what?' · '+s.what:''),s.cpu.toFixed(1)+'% · '+sizeWords(s.rss)])):'<div class="small">No slot or control session running here.</div>')}</div>`;
}
