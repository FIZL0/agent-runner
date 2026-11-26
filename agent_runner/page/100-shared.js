/* --- F124: the sheet: one panel of more choices over the view (docs/STYLE.md) -------------------------------- */
const SHEETS={
  text(){return `<h2>The session's text</h2><div class="btns"><button class="btn pri" data-feedcopy>Copy all</button></div><pre class="out" id="feedtext" style="-webkit-user-select:text;user-select:text">${esc(S.feedText||'')}</pre>`},
  run(){  // More…: Stop, Run, Fix up, each with its key in agent-runner ui
    const gs=controlGroups(S.snap);
    return `<h2>Run</h2>${obCards(obRun)}${gs.map(g=>`<div class="sec">${g.group}<span class="ln"></span></div>${g.items.map(({c,icon,label,choices})=>{
      const ico=`<span class="ico">${I[icon]||''}</span>`;
      const bad=c.key==='stop_now'||c.key==='wip_drop', busy=ctlBusy(c.key)?' busy':'';
      if(c.needs==='n')return `<div class="it setrow"><span class="lab">${ico}<span class="slotsn"><input type="number" min="1" max="99" inputmode="numeric" data-slots-n data-f="slotsn" aria-label="Slots" placeholder="N"><button class="btn${busy}" data-ctl="${esc(c.key)}">${esc(label)}</button></span></span><span class="k">${esc(c.tui)}</span></div>`;
      if(c.fix&&!c.each){const on=S.fixOpen===c.key;
        return `<button class="it${bad?' bad':''}" data-k="fix:${esc(c.key)}" data-fix="${esc(c.key)}" aria-expanded="${on}"><span class="lab">${ico}<span>${esc(label)}${on?'':'…'}</span></span><span class="k">${esc(c.tui)}</span></button>${on?foldIn('fix:'+c.key,choices.map(x=>S.sure===c.key+':'+x.id?ctlSure(c,x.id):`<div class="it setrow"><span class="grow"><span class="ell">${esc(x.label)}</span><span class="small">${esc(x.id)}</span></span><button class="btn${ctlBusy(c.key,x.id)?' busy':''}" data-ctl="${esc(c.key)}" data-tid="${esc(x.id)}">${esc({resume:'Resume',wip_show:'Show',wip_restore:'Restore',wip_drop:'Drop'}[c.key]||c.label)}</button></div>`).join('')):''}`}
      return S.sure===c.key?ctlSure(c):`<button class="it${bad?' bad':''}${busy}" data-ctl="${esc(c.key)}"><span class="lab">${ico}<span>${esc(label)}</span></span><span class="k">${esc(c.tui)}</span></button>`;
    }).join('')}`).join('')||'<div class="small">Nothing to do here right now.</div>'}`;
  },
  out(){return `<h2>${esc((S.out||{}).title||'')}</h2><pre class="out">${esc((S.out||{}).text||'')}</pre><div class="btns"><button class="btn" data-closesheet>Close</button></div>`},
  talk(){  // Talk's settings
    const vs=voices(), t=TS;
    return `<h2>Talk settings</h2>
      <label class="it setrow"><span class="grow">Read replies aloud</span><input type="checkbox" role="switch" class="sw" data-ts="read" ${t.read?'checked':''}></label>
      <label class="it setrow"><span class="grow">Voice</span><select class="fld" data-ts="voice">${voiceOpts()}${vs.map(v=>`<option value="${esc(v.name)}" ${t.voice===v.name?'selected':''}>${esc(v.name)}${v.lang?` (${esc(v.lang)})`:''}</option>`).join('')}${runVoices().length?'</optgroup>':''}</select></label>
      ${AU.got&&!runVoices().length?'<div class="small">The run\'s machine has no voice installed, so this browser reads. Ask a chat to install one.</div>':''}
      <label class="it setrow"><span class="grow">Mic</span><select class="fld" data-ts="mic"><option value="tap" ${t.mic==='tap'?'selected':''}>Tap to start and stop</option><option value="hold" ${t.mic==='hold'?'selected':''}>Hold to talk</option></select></label>
      ${recRow()}
      <label class="it setrow"><span class="grow">Auto listen<span class="small" style="display:block">Listens again once a reply was read; stops after one silent turn.</span></span><input type="checkbox" role="switch" class="sw" data-ts="auto" ${t.auto?'checked':''}></label>
      <div class="btns">${TK.trail?'<button class="btn" data-micreport>Copy mic report</button>':''}<button class="btn" data-sheet="mictest">Mic test…</button><button class="btn" data-closesheet>Done</button></div>`;
  },
};
let sheetBack=null;
/* F170: the sheets of a session's chips */
Object.assign(SHEETS,{
  sesswork(){const e=feedOf(FD.n).filter(x=>x.kind==='tool').pop();
    return `<h2>Working</h2>${e?`<div class="small">${esc(e.text)}</div>`:''}<div class="btns"><button class="btn" data-halt="${esc(FD.n)}">Stop</button></div>`},
  sessmodel(){return `<h2>Model</h2><div class="small">This chat runs on ${esc(modelOf(FD.n))}. The Chats setting under Models names it for new chats. It runs on this machine only, with no link in your apps and no slash commands.</div>`},
  sessmode(){const f=FD.foot||{}, now=f.mode||(FD.live||{}).mode;
    return `<h2>Mode</h2>${FEED_MODES.map(([k,l])=>`<button class="it" data-mode="${k}" aria-pressed="${k===now}"><span>${esc(l)}</span>${k===now?I.check:''}</button>`).join('')}${f.status&&f.status.length?`<div class="sec">Status line<span class="ln"></span></div><pre class="out">${esc(f.status.join('\n'))}</pre>`:''}`},
  sessshells(){const ts=sessTasks('shell');
    return `<h2>Shells</h2>${ts.map(t=>`<div class="it setrow"><span class="grow"><span class="ell">${esc(t.name)}</span><span class="small">${esc(taskWhen(t))}</span></span>${t.running?`<button class="btn" data-sesstask="${esc(t.id)}" data-do="stop">Stop</button>`:''}</div>${t.tail?`<pre class="out">${esc(t.tail)}</pre>`:''}`).join('')||'<div class="small">No shells are in its transcript. The agent CLI lists them with /tasks.</div>'}`},
  sessagents(){const ts=sessTasks('agent'), f=FD.foot||{};
    return `<h2>Agents</h2>${ts.map(t=>`<div class="it setrow"><span class="grow"><span class="ell">${esc(t.name)}</span><span class="small">${esc(taskWhen(t))}</span></span><button class="btn" data-sesstask="${esc(t.id)}" data-do="open">Open</button></div>`).join('')||'<div class="small">This session has started none lately.</div>'}${f.agents?`<div class="small">The agent CLI counts ${f.agents} in its own agent view, which is outside this session.</div>`:''}`},
  sessupdate(){const cmd=(FD.foot||{}).update||'', busyUp=S.ob.some(x=>x.upd&&x.state==='sending'), own=/^c\d+$/.test(FD.n);
    return `<h2>Update the agent CLI</h2>${cmd&&cmd!=='…'?`<div class="small">This runs on ${esc(S.snap.machine||'the machine of the run')}:</div><pre class="out">${esc(cmd)}</pre><div class="btns"><button class="btn pri${busyUp?' busy':''}" data-update="${esc(cmd)}">Update</button></div>`:'<div class="small">Its command does not fit the window: turn the phone, or use a wider one.</div>'}<div class="small">Open chats keep their version until they restart.</div>${own?`<div class="btns"><button class="btn" data-restart="${esc(FD.n)}"${sessIdle()?'':' disabled'}>Restart chat</button></div>${sessIdle()?'':'<div class="small">It can restart once it has nothing running.</div>'}`:''}`},
});
SHEETS.need=needSheet;  // F162
SHEETS.chats=chatsSheet;  // F206
/* F189b: a sheet took the place of another: its edges go on from where that one's were, and its words fade in */
function sheetOver(el,box){
  shotEnd();const r=el.getBoundingClientRect();shotEdges(el,r.top-box.top,box.bottom-r.bottom);
  for(const x of el.children)if(!x.matches('.grab'))moAnim(x,[{opacity:0},{opacity:1}],{ease:'--ease',dur:'--dur'});
}
function openSheet(name,arg){const over=S.sheet&&$('sheet').animate&&!calm()&&shotSeen($('sheet'));MO.folded=0;if(name==='talk')loadVoices();runStop($('sheet'));S.sheet=name;S.sheetArg=arg||'';S.sure=null;S.fixOpen='';S.drawer=false;sheetBack=document.activeElement;scrollStop($('sheet'));render(true);$('sheet').scrollTop=0;if(over)sheetOver($('sheet'),over);$('sheet').focus({preventScroll:true})}
/* F162a2: where focus goes back to: what opened the sheet, or a Needs you card drawn again since */
function sheetOpener(){const b=sheetBack, id=b&&b.dataset&&b.dataset.needopen;
  return !b||b.isConnected||!id?b:[...document.querySelectorAll('[data-needopen]')].find(x=>x.dataset.needopen===id)}
function closeSheet(){if(!S.sheet)return;MO.folded=0;runStop($('sheet'));S.sheet='';S.sure=null;render(true);const b=sheetOpener();if(b&&b.isConnected&&b.focus)b.focus({preventScroll:true});sheetBack=null}
/* B222a: the sheet's markup; a Needs you sheet with a field in use is patched around that field, which stays the same
   element: a new one under the keyboard loses its autocorrect and the letters on their way */
function sheetHTML(el,h){
  const a=document.activeElement, f=S.sheet==='need'&&a&&a!==el&&el.contains(a)&&a.dataset&&a.dataset.f;
  return f?fieldHTML(el,h,f):S.sheet==='need'&&el.querySelectorAll('[data-video]').length?videoHTML(el,h):setHTML(el,h);
}
/* F445a: el's markup, patched around its videos: one drawn again would stop and start over */
function videoHTML(el,h){
  if(el._h===h)return false;
  const t=document.createElement('template');t.innerHTML=h;
  patchKids(el,t.content,null,null);el._h=h;return true;
}
/* el's markup, patched around its field f when that is the one in use */
function fieldHTML(el,h,f){
  const a=document.activeElement;
  if(el._h===h||!a||a===el||!el.contains(a)||!a.dataset||a.dataset.f!==f)return setHTML(el,h);
  const t=document.createElement('template');t.innerHTML=h;
  const at=[...t.content.querySelectorAll('[data-f]')].find(x=>x.dataset.f===f), up=(x,top)=>{const l=[];for(;x&&x!==top;x=x.parentNode)l.unshift(x);return l};
  const was=up(a,el), now=up(at,t.content);
  if(!at||was.length!==now.length||was.some((x,i)=>x.nodeName!==now[i].nodeName))return setHTML(el,h);
  let box=el, want=t.content;
  was.forEach((x,i)=>{patchKids(box,want,x,now[i]);sameAttrs(x,now[i]);box=x;want=now[i]});
  el._h=h;return true;
}
/* box's children become want's, but `stay` (want's is `at`) is left; one that did not change is left too */
function patchKids(box,want,stay,at){
  const side=(olds,news,end)=>{
    for(let j=0;j<news.length;j++){const i=olds.findIndex(x=>sameVideo(x,news[j]));if(i<0)continue;  // F445a: first, whatever is round it
      side(olds.slice(0,i),news.slice(0,j),olds[i]);patchIn(olds[i],news[j])||sameAttrs(olds[i],news[j]);return side(olds.slice(i+1),news.slice(j+1),end)}
    for(let j=0;j<news.length;j++){const i=olds.findIndex(x=>x.isEqualNode(news[j]));if(i<0)continue;
      side(olds.slice(0,i),news.slice(0,j),olds[i]);return side(olds.slice(i+1),news.slice(j+1),end)}
    if(olds.length===1&&news.length===1&&patchIn(olds[0],news[0]))return;
    olds.forEach(x=>x.remove());news.forEach(x=>box.insertBefore(x,end));
  };
  const o=[...box.childNodes], n=[...want.childNodes], p=o.indexOf(stay), q=n.indexOf(at);
  if(!stay)return side(o,n,null);
  side(o.slice(0,p),n.slice(0,q),stay);side(o.slice(p+1),n.slice(q+1),null);
}
/* F445a: two drawings of one video, or of what holds it */
function sameVideo(x,y){
  if(x.nodeType!==1||x.nodeName!==y.nodeName||!x.querySelectorAll)return false;
  const of=n=>n.hasAttribute('data-video')?[n]:[...n.querySelectorAll('[data-video]')], src=of(x).map(v=>v.getAttribute('src'));
  return of(y).some(v=>src.includes(v.getAttribute('src')));
}
/* one thing that changed inside: patched in place, so what did not change in it (a picture) is not drawn again */
function patchIn(x,y){
  if(x.nodeType!==1||x.nodeName!==y.nodeName||!x.childNodes.length||x.dataset.f)return false;
  patchKids(x,y,null,null);sameAttrs(x,y);return true;
}
function sameAttrs(x,y){
  for(const k of x.getAttributeNames())if(!y.hasAttribute(k))x.removeAttribute(k);
  for(const k of y.getAttributeNames())if(x.getAttribute(k)!==y.getAttribute(k))x.setAttribute(k,y.getAttribute(k));
}
/* F189b: a press in the sheet made it longer or shorter: its edges and its parts go there */
function sheetMoves(el,box,spot,had){
  const r=el.getBoundingClientRect();shotEdges(el,r.top-box.top,box.bottom-r.bottom);
  enter(el,had);glide(el,el,spot);leaving(el);
}
function sheetDraw(){
  const el=$('sheet');
  if(S.sheet==='need'&&!needOf(S.sheetArg)){S.sheet='';S.sure=null;sheetBack=null}  // F162: answered, or it left Needs you
  if(el._sheet!==S.sheet){el._sheet=S.sheet;if(S.sheet!=='need')shotEnd()}  // F189: not by a refresh: F189b's edges go on
  if(S.sheet)el.classList.toggle('dlg',S.sheet==='need');
  if(S.sheet&&SHEETS[S.sheet]){
    const h='<div class="grab"></div>'+SHEETS[S.sheet](), drawn=el._h!==h;
    const spot=drawn&&el.animate&&folding()?glideSpot(el):null, box=spot&&shotSeen(el), had=spot&&keysIn(el);  // F189b
    if(spot)shotEnd();
    if(drawn&&el._gone)for(const g of el._gone)g.remove();
    const put=keepScroll(el), f=keepFields(el);
    if(sheetHTML(el,h)){f();put();if(spot)sheetMoves(el,box,spot,had)}
  }  // closing, it keeps its words while it slides
  if(!S.sheet)for(const v of el.querySelectorAll('[data-video]'))v.pause();  // F445a: and its video is not heard
  if(S.sheet==='need')for(const x of el.querySelectorAll('[data-f^="askre:"]')){const v=S.f[x.dataset.f]||'';if(x.value!==v)x.value=v}  // B222a: a sent reply's words go
  if(S.sheet!=='device'&&S.sheet!=='devsecrets')toolForget();  // F169: a typed secret goes with its sheet
  giveForget(S.sheet==='need'?S.sheetArg:'');  // F175a
  if(S.sheet!=='login'&&LG.frame)loginLeave();  // F126b
  el.classList.toggle('open',!!S.sheet);$('sheetscrim').classList.toggle('on',!!S.sheet);
}
