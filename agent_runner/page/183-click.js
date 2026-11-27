let tapped={n:'',at:0};
document.addEventListener('click',async e=>{
  const q=s=>e.target.closest(s);let x;
  if(q('[aria-expanded],#sheet button'))MO.folded=Date.now();  // F189b
  if(S.undo&&!q('[data-undo]'))finalDelete();  // F118: any other click makes the delete final
  if(x=q('[data-feedkey]')){feedKey(x.dataset.feedkey);return}  // F114
  if(q('[data-newsrefresh]')){newsRefresh();return}  // F149
  if(x=q('[data-newslater]')){newsLater(x.dataset.newslater);return}
  if(q('[data-feedkeys]')){keysToggle();return}
  if(q('[data-login]')){loginOpen();return}  // F126b
  if(q('[data-feedtext]')){feedText();return}
  if(x=q('[data-feedcopy]')){const pre=$('feedtext'), pick=()=>{const r=document.createRange();r.selectNodeContents(pre);const g=getSelection();g.removeAllRanges();g.addRange(r)};
    try{await navigator.clipboard.writeText(S.feedText||'');toast('Copied')}catch(err){pick();toast('Selected: copy it with your own Copy')}return}
  if(x=q('[data-resume]')){const n=x.dataset.resume;outbox('resume_chat',{chat:n},{res:n,say:`Resume ${threadTitle(n)}`});return}
  if(q('#sheetscrim')||q('[data-closesheet]')){closeSheet();return}
  if(S.planMenu&&!q('.qacts,[data-planmenu]'))setTimeout(rowMenuShut);  // F429b: what was pressed goes on
  if(x=q('[data-planmenu]')){rowMenuOpen(x.dataset.planmenu);return}
  if(x=q('[data-menuact]')){menuAct(x.dataset.menuact,x.dataset.tid);return}
  if(x=q('[data-menuundo]')){menuUndo(x.dataset.menuundo);return}
  if(q('.rowacts'))S.rowOpen='';  // F187: its own handler goes on
  if(q('[data-slimbox]')){feedSlim(false);const t=document.querySelector('[data-in]');if(t)kbFocus(t);return}  // B218b: in this very tap, as iOS opens a keyboard for no other focus
  if(x=q('[data-halt]')){const n=x.dataset.halt;act('stop_session',{session:n}).then(()=>liveLoad());return}
  if(q('[data-slashopen]')){const t=document.querySelector('[data-in]');if(t){if(!t.value.trim()){t.value='/';store.set(DRAFT_KEY(boxKey()),'/');grow(t)}kbFocus(t);t.setSelectionRange(t.value.length,t.value.length);slashShow(t)}return}
  if(x=q('[data-mode]')){closeSheet();setMode(x.dataset.mode);return}
  if(x=q('[data-sesstask]')){const t=((FD.live||{}).tasks||[]).find(y=>y.id===x.dataset.sesstask);closeSheet();if(t)sessTask(t,x.dataset.do);return}
  if(x=q('[data-update]')){outbox('claude_update',{cmd:x.dataset.update},{upd:1,say:'Update the agent CLI',done:'The agent CLI is updated'});return}
  if(x=q('[data-restart]')){const n=x.dataset.restart;closeSheet();outbox('restart_chat',{chat:n},{res:n,say:`Restart ${threadTitle(n)}`});return}
  if(x=q('[data-sheet]')){openSheet(x.dataset.sheet);return}
  if(x=q('[data-rowmenu]')){rowExpand(x.dataset.rowmenu);return}
  if(q('[data-chats]')){openSheet('chats');chatsLoad();return}  // F206
  if(q('[data-rencancel]')){cancelRename();return}  // F446
  if(x=q('[data-ren]')){if(S.sheet)closeSheet();startRename(x.dataset.ren);return}
  if(x=q('[data-fix]')){S.fixOpen=S.fixOpen===x.dataset.fix?'':x.dataset.fix;S.sure=null;render(true);return}
  if(x=q('[data-slashpick]')){slashTake(+x.dataset.slashpick);return}  // B119
  if(q('[data-obopen]')){S.obOpen=true;obDraw();return}  // F137: the outbox's pill opens its popup
  if(q('[data-obclose]')||e.target.id==='obpop'){S.obOpen=false;obDraw();return}
  if(x=q('[data-obretry]')){const id=x.dataset.obretry;homeHas(id)?homeRetry(id):obRetryClick(id);return}
  if(x=q('[data-sentdrop]')){sentDrop(x.dataset.n,x.dataset.sentdrop);render(true);return}  // B154
  if(x=q('[data-sentretry]')){const n=x.dataset.n, p=sentDrop(n,x.dataset.sentretry);
    if(p&&p.talk&&!talkOld().includes(n))talkSend(p.text);else if(p)outbox('chat_to',{text:p.text,to:n},{text:p.text,key:n,say:`To ${threadTitle(n)}: ${p.text}`});return}
  if(x=q('[data-obdrop]')){if(homeHas(x.dataset.obdrop)){homeChange(b=>obDrop(b,x.dataset.obdrop));render(true);return}obChange(b=>obDrop(b,x.dataset.obdrop));
    if(String(S.thread||'')[0]==='@'&&!S.ob.some(y=>'@'+y.cid===S.thread))S.thread=null;  // its stand-in chat went
    if(S.waitNew&&S.waitNew.ph&&!S.ob.some(y=>'@'+y.cid===S.waitNew.ph))S.waitNew=null;
    render(true);return}
  if(x=q('[data-obedit]')){obEditBack(x.dataset.obedit);return}
  // F150: the levels of the sidebar, and All projects' buttons (Runner Home's /act and /remove)
  if(q('[data-up]')){goUp(false,!e.detail);return}
  if(x=q('[data-alltab]')){H.tab=x.dataset.alltab;tabStore.set('ar-alltab',H.tab);devLeave();S.drawer=false;render(true);loadDevices();return}
  if(q('[data-pmore]')){H.more=!H.more;render(true);return}
  if(x=q('[data-devopen]')){devOpen(x.dataset.devopen);return}  // B818a: a device's page, and what is on it
  if(q('[data-devback]')){devBack();return}
  if(q('[data-devload]')){devLoad();render(true);return}
  if(x=q('[data-devmore]')){DV.more[x.dataset.devmore]=!DV.more[x.dataset.devmore];render(true);return}
  if(x=q('[data-devslot]')){devSlot(x.dataset.devslot);return}  // B818b
  if(x=q('[data-devclean]')){devClean(x.dataset.devclean);return}
  if(x=q('[data-devtick]')){devTick(x.dataset.devtick,x.checked);return}
  if(q('[data-pload]')){loadProjects();loadDevices();return}
  if(q('[data-addproject]')){H.said='';openSheet('addproject');const i=$('sheet').querySelector('input');if(i)kbFocus(i);return}
  if(x=q('[data-projmore]')){openSheet('project',x.dataset.projmore);return}
  if(x=q('[data-pact]')){const k=x.dataset.pkey, p=projectOf(k), a=x.dataset.pact, arg=x.dataset.parg||'', m=p&&projectMore(p).find(b=>b.a===a);if(!p)return;
    if(m&&m.sure&&!x.hasAttribute('data-sure')){S.sure=`proj:${m.label}:${k}`;render(true);return}
    S.sure=null;homeAct(k,a,arg,`${{start:'Start run',pause:'Pause',resume:'Go on',stop:'Stop',slots:`${arg} slot${arg==='1'?'':'s'}`}[a]} · ${p.name||k}`);return}
  if(x=q('[data-punlist]')){const k=x.dataset.pkey;if(!x.hasAttribute('data-sure')){S.sure='proj:Unlist:'+k;render(true);return}
    closeSheet();homePost('remove',{project:k}).then(d=>toast(d.out||(d.ok?'Unlisted':'That did not work'),!d.ok));return}
  if(x=q('[data-askhere]')){e.preventDefault();S.needGo=x.dataset.askhere;goDown();goView('home');needGo();return}
  if((x=q('a[data-pkey]'))&&x.dataset.pkey===HKEY&&atAll()&&!(e.ctrlKey||e.metaKey||e.shiftKey)){e.preventDefault();goDown(false,!e.detail);return}
  if((x=q('[data-pgo]'))&&x.dataset.pkey===HKEY&&HKEY&&atAll()&&!q('a,button,input,form')){goDown();return}
  if((x=q('a[data-pkey]'))&&!(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)){e.preventDefault();openProject(x.dataset.pkey,x.href);return}  // B769b
  if((x=q('[data-pgo]'))&&!q('a,button,input,form')){if(x.dataset.pkey)openProject(x.dataset.pkey,x.dataset.pgo);else location.href=x.dataset.pgo;return}
  if(slashOpen()&&!q('[data-in]'))slashClose();
  if(q('[data-undo]')){S.undo=null;render(true);return}
  if(x=q('[data-pin]')){const n=x.dataset.pin,names=chatNames(),p=chatPins().filter(m=>names.includes(m));  // F133
    const pins=p.includes(n)?p.filter(m=>m!==n):p.concat([n]);savePins(pins);return}
  if(x=q('[data-del]')){S.undo={names:[x.dataset.del],bar:false};S.sel=[];render(true);return}
  if(q('[data-delsel]')){if(S.sel.length){S.undo={names:S.sel,bar:true};S.sel=[]}render(true);return}
  if((x=q('[data-thread]'))&&!x.dataset.way&&/^c\d+$/.test(x.dataset.thread)){  // F118: Ctrl/Cmd+click picks, Shift+click a range
    const how=e.shiftKey?'range':e.ctrlKey||e.metaKey?'toggle':'';
    const p=chatPick(chatNames(),S.sel,S.selLast,x.dataset.thread,how);S.sel=p.sel;S.selLast=p.last;
    if(how){e.preventDefault();render(true);return}
    const now=Date.now(), twice=tapped.n===x.dataset.thread&&now-tapped.at<400;tapped={n:x.dataset.thread,at:now};  // F129: a double-click renames
    if(twice&&!S.drawer){startRename(x.dataset.thread);return}
  }
  if(q('[data-micreport]'))return micCopy();
  if(q('[data-keptsend]'))return keptSend();  // B216a1
  if(x=q('[data-mictest]'))return micTest(x.dataset.mictest);  // B162b1
  if(q('[data-mictestcopy]'))return micCopyText('Mic test',micTestText());
  if(q('[data-mic]')){micLog(`click, detail ${e.detail}`);if(TS.mic==='hold'&&(e.detail>0||Date.now()-TK.upAt<1000))return;return listen()}  // F93; F124: held (pointerdown), a key still toggles
  if(q('[data-spk]')){if(talkReads())return hush();if(TK.held&&!TK.ear&&TK.state!=='thinking')return speak(TK.held);unlockAudio();talkSet('read',!TS.read);return}
  if(x=q('[data-talkmode]'))return talkMode(x.dataset.talkmode);
  if(x=q('[data-speak]'))return playReply(x.dataset.speak);
  if(q('[data-menu]')){if(!S.drawer)drawerBlur();S.drawer=true;render();return}
  if(q('#scrim')){S.drawer=false;render();return}
  if(x=q('[data-view]')){const v=x.dataset.view;return viewGo(()=>goView(v),S.thread)}
  if(q('[data-home]')){viewGo(()=>{S.thread=null;S.ctx=null;render(true)},S.thread);return}
  if(x=q('[data-tool]'))return toolClick(x);  // F169
  if(q('[data-slots-n]')||q('.fld')||q('.sw'))return;
  if(q('[data-unsure]')){S.sure=null;render(true);return}
  if(x=q('[data-ctl]')){const c=controlOf(x.dataset.ctl);if(!c)return;
    const n=c.needs==='n'?String(S.f.slotsn||'').trim():'', tid=x.dataset.tid||'';
    const need=c.answer?needOf(tid):null;if(c.answer&&!need)return;
    const text=need?(need.labels||{})[c.key]||c.label:'', note=need&&x.closest('#sheet')?S.f[askField(tid)]:'';  // F180
    const rq=controlClick(c,{n,tid,sure:x.hasAttribute('data-sure'),text,note});
    if(rq.ask){S.sure=c.key+(tid?':'+tid:'');render(true);return}  // F82: asked in the page, no browser dialog
    if(c.needs==='n'&&!/^\d+$/.test(n))return toast('Type how many slots first',true);
    S.sure=null;S.f.slotsn='';
    if(c.chat&&/^(need|concept)$/.test(c.where)&&chatOpenOf(chatRowOf(tid)))return;  // F209c1: its open chat, nothing sent
    if(c.chat&&c.where==='need'){const k=needConcept(tid,S.snap.concepts);if(k>=0){if(S.sheet)closeSheet();about('concept:'+k);return}}  // B219b: nothing sent until the first message
    if(c.chat){const n=c.where==='need'&&(S.snap.needs||[]).find(x=>x.id===tid);  // B139, C35: it asks a new chat
      newChat(rq.name,rq.args,`${c.label} ${tid}`,n?needChatAsk(n):`do ${tid} here`);return}
    if(S.sheet)closeSheet();
    if(!tid&&ctlTwice(c.key,S.held))return;  // B851b: the same press, still pending, is not sent again
    outbox(rq.name,rq.args,{ctl:c.key+':'+tid,say:need?`${tid} · answered “${text}”`:c.label+(tid?` ${tid}`:''),...(c.where==='need'?{need:tid}:c.where==='concept'?{concept:tid}:c.where==='shelved'?{shelved:tid}:{})});return}  // F124: through the outbox
  if(x=q('[data-framefull]')){const k=x.dataset.framefull;S.frameFull={...(S.frameFull||{}),[k]:!(S.frameFull||{})[k]};render(true);return}  // F463
  if(x=q('[data-pitchopen]')){const n=S.snap.needs[+x.dataset.pitchopen];if(!n)return;  // F98
    S.pitchOpen={...(S.pitchOpen||{}),[n.id]:!(S.pitchOpen||{})[n.id]};S.sure=null;render(true);return}
  if(x=q('[data-pitchno]')){const n=S.snap.needs[+x.dataset.pitchno];if(!n)return;
    const how=x.dataset.how, tid=x.dataset.tid||'';
    if(!x.hasAttribute('data-sure')){S.sure=`pitch:${n.id}:${how}:${tid}`;render(true);return}
    const why=x.closest('#sheet')?String(S.f[askField(n.id)]||'').trim():'';
    S.sure=null;outbox('pitch_no',{pid:n.id,how,tid,confirm:true,...(why?{why}:{})},{need:n.id,say:`${n.id} · Not this${tid?': '+tid:''}`});return}
  if(x=q('[data-reviewopen]')){const n=S.snap.needs[+x.dataset.reviewopen];if(!n)return;  // F444c
    S.reviewOpen={...(S.reviewOpen||{}),[n.id]:!(S.reviewOpen||{})[n.id]};S.sure=null;render(true);return}
  if(x=q('[data-review]')){const n=S.snap.needs[+x.dataset.review];if(!n)return;
    const tid=x.dataset.tid, k=`${n.id}:${tid}`, f=reviewField(n.id,tid), said=String(S.f[f]||'').trim();
    if(!said)return toast(x.dataset.how==='ask'?'Type your question first':'Say what you want instead first',true);
    if(x.dataset.how==='ask'){S.reviewAns={...(S.reviewAns||{}),[k]:{wait:said}};delete S.f[f];
      outbox('pitch_ask',{pid:n.id,tid,q:said},{review:k,say:`${tid} · Ask about it`});return}
    if(!x.hasAttribute('data-sure')){S.sure=`better:${k}`;render(true);return}
    S.sure=null;delete S.f[f];outbox('pitch_better',{pid:n.id,tid,why:said,confirm:true},{need:n.id,say:`${tid} · Ask for a better way`});return}
  if(x=q('[data-taskgo]')){e.preventDefault();taskGo(x.dataset.taskgo);return}  // F482: a task named in a chat
  if(x=q('[data-task]')){openTask(x.dataset.task,x.dataset.list);return}  // F85
  if(x=q('[data-setopen]')){const id=x.dataset.setopen;S.setOpen[id]=!S.setOpen[id];render(true);return}  // F97
  if(q('[data-setload]')){loadSettings();return}
  if(x=q('[data-setask]')){answerAsk(x.dataset.id,x.dataset.setask);return}  // C55b
  if(x=q('[data-setsave]')){saveSetting(x.dataset.id,x.dataset.setsave);return}
  if(x=q('[data-setreset]')){resetSetting(x.dataset.id,x.dataset.setreset);return}
  if(x=q('[data-setstep]')){stepSetting(x.dataset.id,+x.dataset.setstep);return}
  if(q('[data-setmodels]')){setModels();return}  // F405
  if(x=q('[data-setmore]')){openSheet('setting',x.dataset.setmore);return}
  if(q('[data-planqclear]')){setqClear('planq');return}  // F212
  if(q('[data-planqload]')){PQ.err='';planLoad();render(true);return}
  if(q('[data-setqclear]')){setqClear();return}
  if(x=q('[data-settab]')){settingsTab(x.dataset.settab,x.dataset.id);return}  // F462
  if(q('[data-setchanged]')){S.setChanged=!S.setChanged;render(true);return}
  if(x=q('[data-thread]')){const n=x.dataset.thread;return viewGo(()=>{S.ctx=null;open(n)},n===S.thread?null:n)}
  if(q('[data-newtalk]')){newTalk();if(S.live)viewIn($('body'));return}  // F157
  if(x=q('[data-new]')){if(plusHeld(x))return;S.drawer=false;newChat('new_control',{},'New chat');return}
  if(x=q('[data-needopen]')){needOpen(x.dataset.needopen);return}  // F162
  if(x=q('[data-askfold]')){S.askFold={...S.askFold,[x.dataset.askfold]:!S.askFold[x.dataset.askfold]};render(true);return}
  if(q('[data-askload]')){S.askWhy={};S.askText={};render(true);askLoad(S.sheetArg);return}
  if(x=q('[data-shot]')){shotGo(+x.dataset.shot);return}
  if(q('[data-shotclose]')){shotGo(-1);return}
  if(x=q('[data-give]')){giveSend(x.dataset.give,x.hasAttribute('data-sure'));return}  // F175a
  if(x=q('[data-stepcopy]')){const pre=$('sheet').querySelector(`[data-stepcmd="${x.dataset.stepcopy}"]`);if(!pre)return;
    try{await navigator.clipboard.writeText(pre.textContent);toast('Copied')}catch(err){const r=document.createRange();r.selectNodeContents(pre);const g=getSelection();g.removeAllRanges();g.addRange(r);toast('Selected: copy it with your own Copy')}return}
  if(x=q('[data-reply]')){needReply(x.dataset.reply);return}
  if(x=q('[data-about]'))return plusHeld(x)?undefined:about(x.dataset.about);
  if(x=q('[data-quick]')){S.ctx=null;const t=x.textContent.trim();  // B139: a new chat
    newChat('quick_ask',{key:x.dataset.quick},t,t);return}
  if(x=q('[data-pick]')){const c=S.snap.concepts[+x.dataset.pick],o=c&&(c.options||[])[+x.dataset.o];if(!o)return;
    outbox('answer',{tid:c.id,text:`go with ${o.name}`},{concept:c.id,say:`${c.concept||c.id} · go with ${o.name}`,done:`Going with ${o.name}`});return}
  if(x=q('[data-unatt]')){(S.atts[boxKey()]||[]).splice(+x.dataset.unatt,1);render(true);return}
  if(q('[data-clip]')){$('file').click();return}
  if(q('[data-dict]'))return dictate();  // F115
  if(x=q('[data-stop]')){const n=x.dataset.stop||shownSession();if(n)act('interrupt',{session:n});return}
});
document.addEventListener('submit',e=>{e.preventDefault();
  if(e.target.matches('[data-padd]'))return addProject();  // F150
  if(e.target.matches('[data-logincode]'))return loginCode();  // F126b
  if(e.target.matches('[data-loginghe]')){const d=String(S.f.logindomain||'').trim();if(d)loginAt(d);return}  // F406c
  if(e.target.matches('[data-renform]'))return saveRename();  // F129
  send(e.submitter)});
