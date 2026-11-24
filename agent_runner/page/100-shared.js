/* --- F124: the sheet: one panel of more choices over the view (docs/STYLE.md) -------------------------------- */
const SHEETS={
  text(){return `<h2>The session's text</h2><div class="btns"><button class="btn pri" data-feedcopy>Copy all</button></div><pre class="out" id="feedtext" style="-webkit-user-select:text;user-select:text">${esc(S.feedText||'')}</pre>`},
  run(){  // More…: Stop, Run, Fix up, each with its key in agent-runner ui
    const gs=controlGroups(S.snap);
    return `<h2>Run</h2>${obCards(obRun)}${gs.map(g=>`<div class="sec">${g.group}<span class="ln"></span></div>${g.items.map(({c,label,choices})=>{
      const bad=c.key==='stop_now'||c.key==='wip_drop', busy=ctlBusy(c.key)?' busy':'';
      if(c.needs==='n')return `<div class="it setrow"><span class="slotsn"><input type="number" min="1" max="99" inputmode="numeric" data-slots-n data-f="slotsn" aria-label="Slots" placeholder="N"><button class="btn${busy}" data-ctl="${esc(c.key)}">${esc(label)}</button></span><span class="k">${esc(c.tui)}</span></div>`;
      if(c.fix&&!c.each){const on=S.fixOpen===c.key;
        return `<button class="it${bad?' bad':''}" data-fix="${esc(c.key)}" aria-expanded="${on}"><span>${esc(label)}${on?'':'…'}</span><span class="k">${esc(c.tui)}</span></button>${on?choices.map(x=>S.sure===c.key+':'+x.id?ctlSure(c,x.id):`<div class="it setrow"><span class="grow"><span class="ell">${esc(x.label)}</span><span class="small">${esc(x.id)}</span></span><button class="btn${ctlBusy(c.key,x.id)?' busy':''}" data-ctl="${esc(c.key)}" data-tid="${esc(x.id)}">${esc({resume:'Resume',wip_show:'Show',wip_restore:'Restore',wip_drop:'Drop'}[c.key]||c.label)}</button></div>`).join(''):''}`}
      return S.sure===c.key?ctlSure(c):`<button class="it${bad?' bad':''}${busy}" data-ctl="${esc(c.key)}"><span>${esc(label)}</span><span class="k">${esc(c.tui)}</span></button>`;
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
      <label class="it setrow"><span class="grow">Auto listen<span class="small" style="display:block">Listens again once a reply was read; stops after one silent turn.</span></span><input type="checkbox" role="switch" class="sw" data-ts="auto" ${t.auto?'checked':''}></label>
      <div class="btns">${TK.trail?'<button class="btn" data-micreport>Copy mic report</button>':''}<button class="btn" data-closesheet>Done</button></div>`;
  },
};
let sheetBack=null;
/* F170: the sheets of a session's chips */
Object.assign(SHEETS,{
  sesswork(){const e=feedOf(FD.n).filter(x=>x.kind==='tool').pop();
    return `<h2>Working</h2>${e?`<div class="small">${esc(e.text)}</div>`:''}<div class="btns"><button class="btn" data-halt="${esc(FD.n)}">Stop</button></div>`},
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
function openSheet(name,arg){if(name==='talk')loadVoices();runStop($('sheet'));S.sheet=name;S.sheetArg=arg||'';S.sure=null;S.fixOpen='';S.drawer=false;sheetBack=document.activeElement;render(true);$('sheet').scrollTop=0;$('sheet').focus({preventScroll:true})}
/* F162a2: where focus goes back to: what opened the sheet, or a Needs you card drawn again since */
function sheetOpener(){const b=sheetBack, id=b&&b.dataset&&b.dataset.needopen;
  return !b||b.isConnected||!id?b:[...document.querySelectorAll('[data-needopen]')].find(x=>x.dataset.needopen===id)}
function closeSheet(){if(!S.sheet)return;runStop($('sheet'));S.sheet='';S.sure=null;render(true);const b=sheetOpener();if(b&&b.isConnected&&b.focus)b.focus({preventScroll:true});sheetBack=null}
function sheetDraw(){
  const el=$('sheet');
  if(S.sheet==='need'&&!needOf(S.sheetArg)){S.sheet='';S.sure=null;sheetBack=null}  // F162: answered, or it left Needs you
  if(S.sheet!=='need')shotEnd();  // F189
  if(S.sheet)el.classList.toggle('dlg',S.sheet==='need');
  if(S.sheet&&SHEETS[S.sheet]){const put=keepScroll(el), f=keepFields(el);if(setHTML(el,'<div class="grab"></div>'+SHEETS[S.sheet]())){f();put()}}  // closing, it keeps its words while it slides
  if(S.sheet!=='device'&&S.sheet!=='devsecrets')toolForget();  // F169: a typed secret goes with its sheet
  giveForget(S.sheet==='need'?S.sheetArg:'');  // F175a
  if(S.sheet!=='login'&&LG.frame)loginLeave();  // F126b
  el.classList.toggle('open',!!S.sheet);$('sheetscrim').classList.toggle('on',!!S.sheet);
}
