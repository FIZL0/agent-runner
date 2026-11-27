/* --- doing things ------------------------------------------------------------------------------------------ */
/* B212: on touch a script's focus brings no keyboard, so open() gives none (about() does, in the tap) and drops one left from
   the box before; not when a starting chat gets its name (named): its box may be in use */
function open(n,named){if(S.ren&&!named)renameLeave(n);const resp=/^\+response:/.test(n);if(resp)responseOpen(n);if(TOUCH()&&(!isNew(n)||resp)&&!named&&typingIn(document.activeElement))document.activeElement.blur();const quiet=!!S.quiet&&S.quiet===S.thread;S.quiet='';S.thread=n;if(!isNew(n))S.ctx=null;S.drawer=false;S.sheet='';S.sure=null;loadFeed(n);render(true);if(!quiet&&!TOUCH())setTimeout(()=>document.querySelector('[data-in]')?.focus({preventScroll:true}),50)}  // B177: not for a stand-in a reload opened
function goView(v){if(S.view==='home'&&!S.thread&&viewOf(v)==='talk'&&S.atts&&S.atts.home)S.atts=attsMove(S.atts,'home','talk');S.view=viewOf(v);S.thread=null;S.ctx=null;S.drawer=false;S.sheet='';S.sure=null;render(true);if(S.view==='settings')loadSettings();if(S.view==='tools')loadTools()}  // B856: Home's attachments go along to Talk
/* by: the button that was pressed; none for a key, so an empty Enter never forces (F190c) */
async function send(by){
  const ta=document.querySelector('[data-in]');const text=(ta?.value||'').trim();
  const key=boxKey(), atts=S.atts[key]||[];  // B182: this box's own
  if(sendWaits(atts))return toast('Wait for the attachments to finish uploading');
  const paths=atts.filter(a=>a.path).map(a=>a.path);
  if(by&&ta&&by.classList.contains('force')&&sendNow(ta)==='force')return forceQueued(key,S.thread);
  if(!text&&!paths.length)return;
  sentMark(text);
  if(!S.thread&&S.view==='talk'){  // F93; F83: out of the box at once, back in it if it did not go
    histAdd(key,text);HI.i=null;store.set(DRAFT_KEY(key),'');if(ta)ta.value='';delete S.atts[key];
    if(!await talkSend(compose(null,text,paths))){if(!store.get(DRAFT_KEY(key)))store.set(DRAFT_KEY(key),text);if(atts.length)S.atts[key]=[...atts,...(S.atts[key]||[])];render(true)}return}
  const ctx=S.ctx, to=S.thread||'';
  if(ctx&&ctx.kind==='concept'){const c=(S.snap.concepts||[]).find(x=>(x.concept||x.id)===ctx.id);if(c&&c.lead)ctx.lead=c.lead}  // B219a: its page as it is now, not as a kept view has it
  if(ctx&&ctx.kind==='response'&&!responseOf(to))return toast(S.snap.at?'This response is no longer kept, or a chat about it was started':'Still loading: try again in a moment',true);  // F425b: the words stay
  const msg=compose(ctx,text,paths);
  histAdd(key,text);HI.i=null;  // B120: Up brings it back
  store.set(DRAFT_KEY(key),'');if(ta)ta.value='';
  delete S.atts[key];
  const rq=sendReq(ctx,to,msg);
  if(rq.name!=='chat_to'){newChat(rq.name,rq.args,ctx?ctx.label:text||`${paths.length} attachment(s)`,msg);return}  // B139, F176
  // F137: out of the box at once, a pending message until chat_to answers (obDone), red with Retry if it fails
  // F190a: never with force: while it works, the session queues the message; F190c: a second press forces, after a delay
  sendHold(key,SEND_HOLD);
  if(FD.shown){feedRest();sendFly()}  // the session draws it itself
  questionOn.send(to,msg,(msg,more)=>outbox('chat_to',{text:msg,to,...(FD.n===to&&FD.foot&&FD.foot.text?{unsent:true}:{})},{text,key,say:`To ${threadTitle(to)}: ${text||paths.length+' attachment(s)'}`,...more}));  // F192a2
}
/* F137: a new chat opens at once as a stand-in ('@cid') that takes messages; new_control starts it without
   waiting, and its messages go once it has a name. B139: ask, its first message, shows in the stand-in. */
function newChat(name,args,say,ask){const known=chats().map(c=>c.name), it=outbox(name,{...args,wait:false},{newchat:true,say,...(ask?{ask}:{})});
  S.waitNew={known,at:Date.now(),ph:'@'+it.cid};open('@'+it.cid)}
/* F209c1: a Needs you or Concepts row's Chat opens the open chat about it (its 'chat'), when the chat list still has it */
function chatOpenOf(r){const v=r&&r.chat!=null?String(r.chat):'', n=v&&(/^c/.test(v)?v:'c'+v);if(!n||!chats().some(c=>c.name===n))return false;if(S.sheet)closeSheet();open(n);return true}
function chatRowOf(id){return (S.snap.needs||[]).find(x=>x.id===id)||(S.snap.concepts||[]).find(x=>(x.concept||x.id)===id)}
/* F172: a card's Chat opens its new chat view; the session starts with the first message (send) */
function about(a){
  const [k,v]=[a.split(':')[0],a.slice(a.indexOf(':')+1)];
  if(a==='new')S.ctx={kind:'new',label:'Add a task'};
  else if(a==='newconcept')S.ctx={kind:'newconcept',label:'New concept'};
  else if(k==='concept'){const c=S.snap.concepts[+v];if(!c||chatOpenOf(c))return;S.ctx={kind:'concept',id:c.concept||c.id,title:c.title,label:c.title||c.concept,lead:c.lead}}
  else if(k==='setting'){const x=settingOf(v);if(!x)return;S.ctx={kind:'setting',id:`[${x.table}] ${x.key}`,title:x.name,label:x.name}}
  else if(k==='plan'){const q=S.snap.queue.concat(S.snap.shelved||[]).concat(mergeRows(S.snap),working_().map(s=>({id:s.task,title:s.title}))).find(x=>x.id===v);if(!q)return;S.ctx={kind:'plan',id:q.id,title:q.title,label:`${q.id} ${q.title}`}}
  else if(a==='settings')S.ctx={kind:'settings',label:'Ask about my settings'};  // F449: a first message ready to edit, sent only on Send
  else return;
  open(ctxKey(S.ctx));const ta=document.querySelector('[data-in]');
  if(a==='settings'&&ta&&!ta.value.trim()){ta.value=SETTINGS_ASK;store.set(DRAFT_KEY(boxKey()),ta.value);if(typeof grow==='function')grow(ta)}
  if(ta)kbFocus(ta);  // in the tap itself, so a phone's keyboard comes
}
async function upload(file){
  const it={name:file.name||'file'};(S.atts[boxKey()]=S.atts[boxKey()]||[]).push(it);
  if((file.type||'').startsWith('image/')){const r=new FileReader();r.onload=()=>{it.thumb=r.result;render(true)};r.readAsDataURL(file)}
  render(true);
  try{const r=await fetch(tq('upload?name='+encodeURIComponent(it.name)),{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream'},body:file});
    const j=await r.json();if(j.ok)it.path=j.path;else{it.err=j.out||'upload failed';toast(it.err,true)}}
  catch(e){it.err=plainErr(e);toast(`Upload failed: ${it.err}`,true)}
  render(true);
}

/* F189b: the key row opens or closes over the message box: what stands above it goes to its new place, the session's frame with it */
function keysToggle(){
  const d=$('dock'), h=d.offsetHeight, was=feedTop(), old=d.querySelector('.keys'), r=old&&old.getBoundingClientRect();keysFlip();render(true);
  const by=d.offsetHeight-h, row=d.querySelector('.schips'), keys=d.querySelector('.keys');if(!by||calm())return;
  if(row)glideTo(row,0,by,FOLD_MO);
  if(keys)moAnim(keys,[{transform:`translateY(${by}px)`,opacity:0},{transform:'none',opacity:1}],FOLD_MO);
  if(!keys&&old){  // a copy goes down behind the box and fades
    const g=old.cloneNode(true), e=d.getBoundingClientRect();g.classList.add('gone0');g.setAttribute('aria-hidden','true');g.inert=true;
    for(const x of g.querySelectorAll('*'))for(const k of Object.keys(x.dataset))delete x.dataset[k];
    Object.assign(g.style,{left:r.left-e.left+'px',top:r.top-e.top+'px',width:r.width+'px'});d.prepend(g);
    const a=moAnim(g,[{transform:'none',opacity:1},{transform:`translateY(${-by}px)`,opacity:0}],{...FOLD_MO,fill:'forwards'});a.onfinish=a.oncancel=()=>g.remove();
  }
  if(was!=null){feedPlace();feedGrow(was-feedTop())}
}
