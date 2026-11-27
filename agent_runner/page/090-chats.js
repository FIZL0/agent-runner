/* --- F114: a chat or slot: the real session in #feed ------------------------------------------------------------
   F206: one frame, made once and kept; only the open chat is connected (arLine, session_frame.HEAD): leaving it, or a page
   out of sight for FEED_AWAY, hangs up, so the session gets its other viewers' size back. Each chat's last screen is kept
   (KEPT, in memory) and shown until the new connection's first whole draw.
   FD: n its chat, info the run's answer, frame, want (it is to be connected), up (its socket is open), dialing (since when
   it is being opened), drawn (the terminal shows this chat), old (the kept screen over it), since (when it stopped being
   drawn), was (it was drawn, or kept, before) */
const FD={n:'',turn:0,info:null,frame:null,want:false,up:false,dialing:0,drawn:false,old:null,since:0,was:false,timer:0,sayT:0,upT:0,away:0,downs:0,keptAt:0,ask:null,deaf:0,hid:0,muted:false}, FEED_AWAY=15000, FEED_AGAIN=3000;
const KEPT=new Map(), FEED_SAY=5000, FEED_DIAL=10000, FEED_KEEP=2000, LIVE_GIVE=8000;
const FEED_LINES=1;  // lines of a drag to one wheel step
const TOUCH=()=>!!(window.matchMedia&&matchMedia('(pointer:coarse)').matches);
const enterHint=()=>TOUCH()?' enterkeyhint="enter"':'';  // B181
const feedNow=n=>feedState({stand:String(n||'')[0]==='@',starting:starting(n),born:bornNow(n),info:FD.n===n?FD.info:null,chat:!isAgent(n)});
const feedSize=()=>TOUCH()?12:13;  // the terminal's text size, px: the stand-in's too (standHTML)
const feedSrc=n=>`t/${encodeURIComponent(T)}/${encodeURIComponent(n)}/?fontSize=${feedSize()}`;
/* the chat the frame is to be connected to, '' for none (session_frame.HEAD asks once its page is up) */
function feedWant(){return FD.want?FD.n:''}
function feedWantLook(){return feedSkinOf(FD.info)}
const feedLine=()=>{try{return FD.frame.contentWindow.arLine||null}catch(e){return null}};
const feedSkinOf=i=>!i||!i.look?'':i.look==='page'?'page-'+feedLook():i.look;
/* the screen that is there now, kept for its chat (its lines, and what feedPlace needs to put it where it was) */
function feedKeep(){
  if(!FD.foot&&KEPT.has(FD.n))return;  // no prompt: it may have drawn its end, or an error, over its last screen
  const l=FD.drawn&&feedLine(), node=l&&l.keep();if(!node)return;
  FD.keptAt=Date.now();keptPut(KEPT,FD.n,{node,info:FD.info,foot:FD.foot,whole:FD.whole,short:FD.short,last:FD.last});
}
/* its kept screen, as it was placed */
function feedBack(n){
  const k=KEPT.get(n);FD.old=k?k.node:null;FD.was=!!k;FD.since=Date.now();
  if(k){Object.assign(FD,{foot:k.foot,whole:k.whole,short:k.short,last:k.last});if(!FD.info)FD.info=k.info}
}
function feedHang(){FD.turn++;for(const t of [FD.timer,FD.upT])clearTimeout(t);FD.timer=0;FD.want=FD.up=FD.drawn=false;FD.dialing=0;liveStop();const l=feedLine();if(l)l.hang()}
function feedLeave(){feedKeep();feedHang();FD.old=null;feedGone()}
/* connected to the open chat, after its place and size are known */
function feedDial(){
  const turn=FD.turn, busyDial=()=>FD.up||Date.now()-FD.dialing<FEED_DIAL;if(busyDial())return;
  FD.want=true;
  if(!FD.frame)return feedFrame();
  requestAnimationFrame(()=>{if(turn!==FD.turn||!FD.want||busyDial())return;feedPlace();feedDialing();const l=feedLine();if(l)l.dial(FD.n,feedSkinOf(FD.info))});
}
/* one that neither opens nor closes is dialed again */
function feedDialing(){FD.dialing=Date.now();clearTimeout(FD.upT);FD.upT=setTimeout(()=>{if(!FD.up)feedLoad()},FEED_DIAL+500)}
function feedFrame(){
  const f=document.createElement('iframe');f.title='The session';f.allow='clipboard-read; clipboard-write';f.src=feedSrc(FD.n);
  f.onload=()=>{if(FD.frame!==f||feedLine())return;f.remove();FD.frame=null;FD.want=false;FD.dialing=0;if(FD.n)FD.timer=setTimeout(feedLoad,FEED_AGAIN)};  // its page did not come
  FD.frame=f;feedDialing();$('feedframe').appendChild(f);
}
async function feedLoad(){
  const n=FD.n, turn=++FD.turn;clearTimeout(FD.timer);FD.timer=0;
  if(!n||n[0]==='@'||isNew(n)||document.hidden)return;
  if(FD.info&&FD.info.ok)feedDial();
  let i;try{i=await (await fetch(tq('terminal/'+encodeURIComponent(n)))).json()}catch(e){i=null}
  if(turn!==FD.turn)return;
  if(i)FD.info=i;
  if(i&&i.ok)feedDial();
  else{if(i){feedKeep();feedHang();feedBack(n)}if(!FD.up)FD.timer=setTimeout(feedLoad,FEED_AGAIN)}  // it may come up, or be installed
  render();
}
/* the frame's word: its socket opened or closed (the session ended, the connection broke: look again), its first whole
   draw is there, files dropped */
addEventListener('message',e=>{
  const d=e.data;if(e.origin!==location.origin||!d||!FD.frame||e.source!==FD.frame.contentWindow||d.session!==FD.n)return;
  if(d.files){[...d.files].forEach(upload);return}
  if(d.state==='drawn')return feedDrawn();
  clearTimeout(FD.timer);clearTimeout(FD.upT);FD.timer=0;FD.dialing=0;FD.up=d.state==='up';
  if(FD.up)feedUp();
  else{
    if(FD.drawn){feedKeep();FD.drawn=false;feedBack(FD.n)}
    FD.want=false;FD.timer=setTimeout(feedLoad,Math.min(250*2**FD.downs++,15000));
  }
  feedSkin();
});
function feedDrawn(){if(FD.drawn||!FD.up)return;clearTimeout(FD.upT);FD.drawn=FD.was=true;FD.downs=0;FD.fresh=true;feedSee();FD.fresh=false;FD.old=null;feedSkin();feedPlace()}
/* what stands over the terminal until it is drawn: the kept screen, else the chat's latest messages; and the line */
function feedSkin(){
  const l=feedLine(), st=FD.n?feedNow(FD.n):'', wait=FD.shown&&(!FD.drawn||feedMute())&&st!=='ended';FD.muted=feedMute();
  if(l)l.show(FD.drawn?null:FD.old);
  if(FD.frame)FD.frame.className=FD.drawn||FD.old&&l?'':'blank';
  const stand=$('feedstand');stand.hidden=!FD.shown||FD.drawn||!!(FD.old&&l);if(!stand.hidden)setHTML(stand,standHTML(FD.n));
  $('feedline').hidden=!wait;feedSay(wait);
}
function feedSay(wait){
  const el=$('feedsay'), left=FD.muted?0:FD.since+FEED_SAY-Date.now(), on=wait&&left<=0;clearTimeout(FD.sayT);
  if(wait&&!on)FD.sayT=setTimeout(feedSkin,left);
  el.hidden=!on;setHTML(el,on?`<span class="livedot"></span>${FD.was?'Reconnecting…':'Connecting to the session…'}`:'');
}
/* B819: the terminal's cells before it is there: its size and font, measured and rounded as xterm.js does it (a canvas, else
   a span), in a frame as wide as `room`. STAND: the padding and line height of session_frame's PAD and LINE_HEIGHT, and the
   scrollbar's room xterm's fit keeps. ls: what brings a letter to its cell */
const STAND={pad:14,bar:15,line:1.3,seen:{}};
function standLetter(size,family){
  const key=size+family;if(STAND.seen[key])return STAND.seen[key];
  let w=0,h=0;
  try{const c=new OffscreenCanvas(100,100).getContext('2d');c.font=`${size}px ${family}`;const m=c.measureText('W');w=m.width;h=m.fontBoundingBoxAscent+m.fontBoundingBoxDescent}catch(e){}
  if(!(w&&h)){
    const s=document.createElement('span');s.textContent='W'.repeat(32);s.style.cssText=`position:absolute;visibility:hidden;white-space:pre;line-height:normal;font-size:${size}px;font-family:${family}`;
    document.body.appendChild(s);w=s.offsetWidth/32;h=s.offsetHeight;s.remove();
  }
  return w&&h?STAND.seen[key]={w,h}:{w:size*.6,h:size*1.2};
}
function standCells(size,family,room){
  const l=standLetter(size,family), dpr=window.devicePixelRatio||1, wide=n=>Math.round(l.w*dpr*n/dpr)/n;
  const cols=Math.max(2,Math.floor((room-2*STAND.pad-STAND.bar)/wide(80))), cw=wide(cols);  // it fits from 80 columns
  return{cols,cw,ls:cw-l.w,cell:Math.floor(Math.ceil(l.h*dpr)*STAND.line)/dpr};
}
/* a chat not seen here yet: its latest messages, from its transcript, as the terminal draws them */
function standHTML(n){
  const said=standMsgs(feedOf(n)).map(m=>({kind:m.w==='u'?'you':'say',text:m.text}));
  if(!said.length)return '<div class="col"><div class="msgs"><div class="small">Loading…</div></div></div>';
  const el=$('feedstand'), size=feedSize(), c=standCells(size,getComputedStyle(el).fontFamily,$('feed').clientWidth);
  return `<div class="standrows" style="font-size:${size}px;--hw:${c.cw}px;--hcell:${c.cell}px;letter-spacing:${c.ls.toFixed(4)}px">${pastLines(said,c.cols).map(l=>`<div>${l.h}</div>`).join('')}</div>`;
}
addEventListener('resize',()=>{if(!$('feedstand').hidden)feedSkin()});
/* each draw: the frame for the chat that is open, or its state in the body */
function feedDraw(n){
  const moved=(n||'')!==FD.n;
  if(moved){feedLeave();FD.n=n||'';FD.info=null;FD.downs=0;if(n)feedBack(n)}
  const st=n?feedNow(n):'', show=st==='session'||st==='loading'&&!!sessionOf(n)||st==='ended'&&!!FD.old;
  if(FD.info&&!FD.info.ok&&FD.info.mode==='install')FD.old=null;
  $('feed').hidden=!show;$('body').hidden=show;
  document.documentElement.classList.toggle('lightfeed',S.snap.session_look==='light');document.documentElement.classList.toggle('pagefeed',show&&!!FD.info&&FD.info.look==='page');
  feedShown(show);
  const l=moved&&show&&feedLine();if(l&&FD.info&&FD.frame.contentWindow.arLook)FD.frame.contentWindow.arLook(feedSkinOf(FD.info));
  feedSkin();
  if(moved&&n)feedLoad();
}
document.addEventListener('visibilitychange',()=>{
  clearTimeout(FD.away);
  if(document.hidden){FD.hid=Date.now();FD.away=setTimeout(()=>{if(document.hidden&&FD.n){feedLeave();feedBack(FD.n);feedSkin()}},FEED_AWAY)}
  else{liveStop();if(FD.n&&!FD.up){FD.since=Date.now();feedLoad()}else if(FD.n&&Date.now()-FD.hid>=FEED_AWAY)feedAgain()}  // frozen before its timer: the socket may be dead
});
/* F206a: the network can go silent with the socket still open: for FEED_SAY the run has not answered and the session has
   sent nothing. The line and Reconnecting… show then, and the first answer dials again.
   FD: ask the question that is out, deaf since when none is answered, muted what feedSkin last showed */
function feedMute(){const l=FD.up&&FD.deaf&&feedLine();return!!l&&Date.now()-Math.max(FD.deaf,l.heard())>=FEED_SAY}
function liveStop(){const a=FD.ask;FD.ask=null;FD.deaf=0;if(a)a.abort()}
/* /live, one at a time: on a dead network they pile up and hold the browser's few connections */
async function liveGet(n){
  if(FD.ask)return null;
  FD.deaf=FD.deaf||Date.now();
  const ask=FD.ask=new AbortController(), give=setTimeout(()=>ask.abort(),LIVE_GIVE);
  let r=null,j=null;try{r=await fetch(tq('live/'+encodeURIComponent(n)),{signal:ask.signal});j=await r.json()}catch(e){if(!(e instanceof SyntaxError))r=null}  // a body that stalls is no answer
  clearTimeout(give);
  if(FD.ask!==ask)return null;
  FD.ask=null;if(!r)return null;
  if(FD.muted=feedMute()){feedAgain();return null}
  FD.deaf=0;return j;
}
function feedAgain(){const deaf=FD.muted&&FD.deaf;feedKeep();feedHang();feedBack(FD.n);if(deaf)FD.since=deaf;feedSkin();feedLoad()}
addEventListener('online',()=>{if(FD.n&&FD.want)feedAgain()});  // the socket may be dead and not know it
/* an ended chat whose last screen is kept: what to do now, over its message box */
function feedEnd(n){return feedNow(n)==='ended'&&FD.old?`<div class="feedend">${feedHTML(n,true)}</div>`:''}
/* F425b: an opened sent response: what was asked and answered; words sent here start its chat */
function responseHTML(n){
  const r=responseOf(n), part=(head,words)=>`<div><div class="small">${head}</div><div class="said">${esc(words)}</div></div>`;
  if(!r)return `<div class="col feeds">${card(S.snap.at?`<div class="q">${esc(threadTitle(n))}</div><div class="small">This response is no longer kept, or a chat about it was started.</div>`:'<div class="small">Loading…</div>','',`data-k="feed:${esc(n)}"`)}</div>`;
  const ago=agoWords(r.at*1000,' ago'), when=ago&&` · ${ago}`;
  return `<div class="col feeds">${card(`<div class="q said">${esc(r.question||r.label)}</div>${part('Your answer'+when,r.answer)}${r.note?part('Your note',r.note):''}<div class="small">It is sent. A chat about it starts with your first message${modelOf(n)?`, on ${esc(modelOf(n))}`:''}.</div>`,'',`data-k="feed:${esc(n)}"`)}</div>`;
}
/* what a chat or slot with no session to show says */
function feedHTML(n,bare){
  if(S.ctx&&S.ctx.kind==='response'&&isNew(n))return responseHTML(n);
  if(isNew(n))return `<div class="col feeds">${card(`<div class="q">${esc(threadTitle(n))}</div><div class="small">The chat starts with your first message${modelOf(n)?`, on ${esc(modelOf(n))}`:''}.</div>`,'',`data-k="feed:${esc(n)}"`)}</div>`;  // F172
  const st=feedNow(n), i=(FD.n===n&&FD.info)||{}, last=S.last[n]||{}, link=i.link||(sessionOf(n)||{}).link||last.link||'';
  const open=link?`<a class="btn" href="${esc(link)}" target="_blank" rel="noopener">Open its session ${I.ext}</a>`:'';
  if(st==='starting')return `<div class="col feeds"><div class="msgs">${sentBubbles(n,t=>t)}${obBubbles(n)}${n[0]==='@'?'':`<div class="think">${LOGO()}${WAVE}Starting the chat…</div>`}</div></div>`;
  if(st==='loading')return `<div class="col feeds"><div class="think">${LOGO()}Loading…</div></div>`;
  let title='', words=i.out||'', btns=open;
  if(st==='install')title='The session cannot be shown here';
  else if(st==='ended'){
    title='This chat has ended';
    words=i.resume?'Resume brings it back with everything said in it.':i.why||'';
    if(i.resume)btns=`<button class="btn pri${S.ob.some(x=>x.res===n&&x.state==='sending')?' busy':''}" data-resume="${esc(n)}">Resume</button>`+open;
  }else if(st==='idle'){
    const tid=(sessionOf(n)||{}).task||last.task||'', cut=tid&&((S.snap.fixups||{}).resume||[]).some(x=>x.id===tid)&&controlOf('resume');
    title=sessionOf(n)?`${n} has no session now`:'This slot is gone';
    words=cut?`Its session on ${tid} was cut off. Its work is kept.`:last.task&&last.title?`It last worked on “${last.title}”.`:'It shows here when a task starts.';
    if(cut)btns=`<button class="btn pri${ctlBusy('resume',tid)?' busy':''}" data-ctl="resume" data-tid="${esc(tid)}">Resume</button>`+open;
  }else title='There is no terminal to show';
  const said=st==='install'&&i.cmd?esc(words).replace(esc(i.cmd),m=>`<code>${m}</code>`):esc(words);  // B761: the install command, as code
  const c=card(`<div class="q">${esc(title)}</div>${words?`<div class="small">${said}</div>`:''}${btns?`<div class="btns">${btns}</div>`:''}`,'',`data-k="feed:${esc(n)}" data-v="${st}"`);
  return bare?c:`<div class="col feeds">${c}</div>`;
}
/* ttyd's terminal (xterm.js), once its page has made it; null before */
/* B863: the page's own Jump to bottom pressed: the terminal goes to its newest output */
function feedOwnEnd(){const t=feedTerm();if(t)t.scrollToBottom();FD.own=false;if(typeof pastJumpDraw==='function')pastJumpDraw()}
function feedTerm(){try{return FD.up&&FD.frame&&FD.frame.contentWindow.term||null}catch(e){return null}}
function feedKey(k){const t=feedTerm();if(!t)return toast('The session is not connected yet',true);
  t.input(feedBytes(k,!!(t.modes&&t.modes.applicationCursorKeysMode)),true)}
const keyButtons=()=>`<div class="keys" role="toolbar" aria-label="Keys for the session">${FEED_KEYS.map(([k,l])=>`${k==='left'?'<button type="button" class="tool" data-feedtext title="The screen as text, to copy">Text</button>':''}<button type="button" class="tool" data-feedkey="${k}"${/\w/.test(l)?'':` aria-label="${k.charAt(0).toUpperCase()+k.slice(1)} arrow"`}>${l}</button>`).join('')}</div>`;
/* F437b: no key row with an open question card, unless the keyboard button opened it there; S.keys stays, for after it */
const keysCard=()=>sessUp(S.thread)&&!questionAway(S.thread)?questionUp(S.thread):'';
const keysShown=()=>{const k=keysCard();return k?QN.keys===k:!!S.keys||keysLeft()};
const keysLeft=()=>!!QN.keys&&questionAway(S.thread)&&QN.keys===questionUp(S.thread);  // F437c: opened under the card, which hides
function keysFlip(){const k=keysCard();if(k)QN.keys=QN.keys===k?'':k;else{const on=keysShown();if(keysLeft())QN.keys='';S.keys=!on}}
const keysRow=()=>keysShown()?keyButtons():'';
/* the screen's text in a sheet, to select and copy with a finger */
function feedText(){const t=feedTerm();if(!t)return toast('The session is not connected yet',true);
  const b=t.buffer.active, l=[];for(let y=b.viewportY;y<b.viewportY+t.rows;y++){const x=b.getLine(y);l.push(x?x.translateToString(true):'')}
  S.feedText=feedWords(l);openSheet('text')}
function feedScreen(any){  // any: also while the terminal does not show this chat yet
  let t=null;try{t=(any||FD.up&&FD.drawn)&&FD.frame.contentWindow.term}catch(e){}
  const el=t&&t.element&&t.element.querySelector('.xterm-screen');return el?{t,el,win:FD.frame.contentWindow,cell:el.getBoundingClientRect().height/t.rows||16}:null}
/* wheel steps on the session, as a mouse's: its own scrolling (a fullscreen session's history) or the terminal's */
function feedWheel(n,x,y){
  const f=feedScreen();if(!f||!n)return;
  if(f.t.modes.mouseTrackingMode==='none'&&f.t.buffer.active.type==='normal'){f.t.scrollLines(n);return}
  [x,y]=feedAt(x,y);
  for(let i=Math.min(Math.abs(n),20);i>0;i--)f.el.dispatchEvent(new f.win.WheelEvent('wheel',{deltaY:Math.sign(n)*f.cell,deltaMode:0,clientX:x,clientY:y,bubbles:true,cancelable:true}));
}
function feedClick(x,y){const f=feedScreen();if(!f)return;[x,y]=feedAt(x,y);
  for(const type of ['mousemove','mousedown','mouseup','click'])f.el.dispatchEvent(new f.win.MouseEvent(type,{clientX:x,clientY:y,button:0,buttons:type==='mousedown'?1:0,detail:1,bubbles:true,cancelable:true,view:f.win}))}
/* the touch layer over the frame: a drag scrolls (and glides on), a tap clicks, a long press does nothing. The
   drawer's swipe has the touch first: once it is on, this leaves it alone */
{let G=null, glide=0;
const layer=$('feedtouch'), at=t=>{const r=layer.getBoundingClientRect();return[t.clientX-r.left,t.clientY-r.top]};
const step=by=>{const f=feedScreen(), px=feedScroll(by);if(!f||!px)return;const [n,left]=feedSteps(G.rest+px,f.cell*FEED_LINES);G.rest=left;feedWheel(n,G.x,G.y)};
layer.addEventListener('touchstart',e=>{cancelAnimationFrame(glide);if(G)clearTimeout(G.hold);
  if(e.touches.length!==1){G=null;return}
  const t=e.touches[0], [x,y]=at(t);G={x,y,y0:t.clientY,x0:t.clientX,ly:t.clientY,lt:e.timeStamp,v:0,rest:0,on:false};
  const g=G;g.hold=setTimeout(()=>{if(G===g&&!g.on)G=null},450)},{passive:true});
layer.addEventListener('touchmove',e=>{
  if(!G)return;
  if(SW&&SW.on||e.touches.length!==1){clearTimeout(G.hold);G=null;return}
  const t=e.touches[0], dy=t.clientY-G.y0, dx=t.clientX-G.x0;
  if(!G.on){if(Math.abs(dy)<8&&Math.abs(dx)<8)return;clearTimeout(G.hold);if(Math.abs(dx)>Math.abs(dy)){G=null;return}G.on=true;SW=null}
  step(G.ly-t.clientY);
  if(e.timeStamp>G.lt)G.v=.7*(G.ly-t.clientY)/(e.timeStamp-G.lt)+.3*G.v;
  G.ly=t.clientY;G.lt=e.timeStamp},{passive:true});
layer.addEventListener('touchend',e=>{const g=G;if(!g)return;clearTimeout(g.hold);
  if(!g.on){G=null;if(e.cancelable)e.preventDefault();feedClick(g.x,g.y);return}
  let last=performance.now(), v=e.timeStamp-g.lt>60||matchMedia('(prefers-reduced-motion:reduce)').matches?0:g.v;
  const go=now=>{if(G!==g)return;if(Math.abs(v)<.05){G=null;return}step(v*(now-last));v*=Math.pow(.996,now-last);last=now;glide=requestAnimationFrame(go)};
  glide=requestAnimationFrame(go)},{passive:false});
layer.addEventListener('touchcancel',()=>{if(G)clearTimeout(G.hold);G=null},{passive:true});
/* B218b1: a press on the slim message box ends the drag and its glide, at the touch, so the box it opens stays. A browser
   may give no click for a tap after a fling, so the touch's end makes it, as kbTapEnd does (a click alone: Enter, a mouse) */
let tap=null;
const slim=$('slimbox'), slimPress=e=>{const el=e.target.closest('[data-slimbox]');if(el){cancelAnimationFrame(glide);if(G)clearTimeout(G.hold);G=null;pastStop()}return el};
slim.addEventListener('click',slimPress);
const slimEnd=e=>{const k=tap, t=e.changedTouches[0], el=slim.querySelector('[data-slimbox]');tap=null;
  if(!k||!el||e.type!=='touchend'||!e.cancelable||Date.now()-k.at>450||Math.abs(t.clientX-k.x)>9||Math.abs(t.clientY-k.y)>9)return;  // a swipe or a long press
  e.preventDefault();el.click()};
slim.addEventListener('touchstart',e=>{const el=slimPress(e), t=e.touches[0];tap=el&&e.touches.length===1?{x:t.clientX,y:t.clientY,at:Date.now()}:null;
  if(tap)for(const n of ['touchend','touchcancel'])e.target.addEventListener(n,slimEnd,{passive:false})},{passive:true});  // on what was touched: a redraw of the row under the finger may take it out
layer.addEventListener('wheel',e=>{const f=feedScreen();if(!f||feedTake(e.deltaY))return;const r=layer.getBoundingClientRect();feedWheel(Math.sign(e.deltaY),e.clientX-r.left,e.clientY-r.top)},{passive:true});
layer.addEventListener('click',e=>{if(e.detail&&e.pointerType==='mouse'){const r=layer.getBoundingClientRect();feedClick(e.clientX-r.left,e.clientY-r.top)}})}
/* --- F170: the lines at the bottom of the agent's window as the page's own controls (approved on K10's page, option A) --
   The frame is taller than its room by FOOT_ROWS, so those lines lie past the edge; feedSpot says where it goes, by a
   transform, never by a resize: the bars come and go, the box grows, and the session's size stays. B192: the bars going or
   coming never moves it; only a scroll does (feedScroll), and the session's own going to its end. Whole (a menu, a
   question, unsent words, a look feedFoot does not know): it fits its room exactly, all of it shown. */
Object.assign(FD,{shown:false,foot:undefined,whole:false,wait:0,off:0,far:0,t:0,held:'',above:0,last:0,run:0,rest:0,slim:false,jump:false,top:false,gap:0,still:'',rows:'',stillT:0,typed:0,full:0,wide:0,doc:0,live:null,liveAt:0,task:''});
const KB_PAD=6;  // .dock's bottom padding: 14px, and 8px in .app.kb
const SLIM_H=56, FOOT_WAIT=400, TEXT_WAIT=1200, LIVE_EVERY=2000;
const pageDark=()=>{const t=document.documentElement.dataset.theme;return t?t==='dark':matchMedia('(prefers-color-scheme:dark)').matches};
function feedLook(){return pageDark()?'dark':'light'}
function lookAgain(){try{if(FD.frame&&FD.info&&FD.info.look==='page')FD.frame.contentWindow.arLook(feedSkinOf(FD.info))}catch(e){}}
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',lookAgain);
if(window.MutationObserver)new MutationObserver(lookAgain).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
/* does the session of a chat or slot work? The agent CLI's own status; until it is read, or with none, the feed's */
const sessWorks=n=>{const l=FD.n===n&&FD.live;return l&&l.status?l.status==='busy':FD.n===n&&FD.foot?FD.foot.work:busy(n)};
function feedGone(){FD.own=false;pastReset();clearTimeout(FD.wait);feedStill();Object.assign(FD,{foot:undefined,whole:false,wait:0,off:0,far:0,t:0,held:'',last:0,run:0,rest:0,slim:false,jump:false,top:false,still:'',live:null,liveAt:0});feedClass()}
function feedClass(){const m=document.querySelector('.main'), row=$('slimbox');if(!m||!row)return;
  m.classList.toggle('still',calm());m.classList.toggle('sess',FD.shown);m.classList.toggle('slim',FD.shown&&FD.slim);m.classList.toggle('pulled',FD.shown&&FD.off>0);row.hidden=!FD.shown;
  const d=$('dock');if(d)d.inert=FD.shown&&FD.slim;row.inert=!FD.slim;
  if(!FD.shown){const a=feedFly;feedFly=null;if(a)a.cancel();$('feed').style.bottom=''}}
function feedShown(on){if(FD.shown!==on){FD.shown=on;if(!on){FD.slim=false;FD.off=0}}feedClass();if(on)requestAnimationFrame(feedPlace)}
/* its socket is open: its screen is read at each draw, in the very frame it shows: one frame later, a row more or less is a jump (F206a) */
function feedUp(){
  let t;try{t=FD.frame.contentWindow.term}catch(e){}
  if(t&&!t.arSeen){t.arSeen=true;t.onRender(feedSee);feedRedrawPin(t)}
  lookAgain();liveLoad();
}
/* B867: a harness chat draws its screen again for each viewer that comes (and at each resize) with a clear of the
   scrollback (CSI 3J) and its last output; xterm's view then stays at the top of it. A view that was at its end stays
   there: for a moment after the clear, each write parsed takes it to its end again, unless the reader scrolled up.
   B884: a view scrolled up keeps its distance from the end across the clear, so it shows the same lines, never the top */
const REDRAW_PIN_MS=800;
function feedRedrawPin(t){
  if(!t.parser||!t.parser.registerCsiHandler)return;
  let until=0,back=0,want=-1;
  t.parser.registerCsiHandler({final:'J'},p=>{
    const b=t.buffer.active;
    if(p[0]===3){back=Math.max(0,b.baseY-b.viewportY);want=-1;until=Date.now()+REDRAW_PIN_MS}
    return false});
  const pin=()=>{
    if(Date.now()>=until){until=0;return}
    const b=t.buffer.active;
    if(!back){t.scrollToBottom();return}
    want=Math.max(0,b.baseY-back);if(b.viewportY!==want)t.scrollToLine(want)};
  if(t.onWriteParsed)t.onWriteParsed(pin);else t.onLineFeed(pin);
  t.onScroll(()=>{const b=t.buffer.active;if(!until||b.viewportY<=0)return;
    if(back?(want>=0&&b.viewportY!==want):b.viewportY<b.baseY)until=0});
}
function feedLines(t){const b=t.buffer.active,l=[];for(let y=b.baseY;y<b.baseY+t.rows;y++){const x=b.getLine(y);l.push(x?x.translateToString(true):'')}return l}
function feedSee(){
  const t=feedTerm();if(!t||!FD.shown||!FD.drawn)return;
  const b=t.buffer.active, lines=feedLines(t);
  const dim=(y,x)=>{const l=b.getLine(b.baseY+y), c=l&&l.getCell(x);return!!(c&&c.isDim())};
  const lit=(y,x)=>{const l=b.getLine(b.baseY+y), c=l&&l.getCell(x);return!!(c&&!c.isBgDefault())};
  if(!lines.some(l=>l)){if(FD.fresh&&FD.foot===undefined){FD.foot=null;feedWhole(true)}return}  // not drawn yet
  FD.last=b.viewportY<b.baseY?t.rows:lines.findLastIndex(l=>l.trim())+1;
  const foot=feedFoot(lines,dim,lit), was=FD.foot, wasShort=FD.short, still=!FD.fresh&&!!was&&!FD.whole&&!FD.jump&&!FD.off;
  FD.foot=foot;
  let blank=0;if(foot)while(blank<foot.top&&!lines[foot.top-1-blank].trim())blank++;
  FD.short=foot&&(!b.baseY||t.modes.mouseTrackingMode!=='none')&&(blank>3||foot.end<t.rows-FOOT_ROWS-2)?Math.max(1,foot.top-blank):0;
  // B786: the working lines stand right above the prompt, with the gap over them: its words end over the gap
  FD.gap=!FD.short&&foot&&!foot.jump&&!foot.rate&&feedOldest(t)?feedGap(lines,foot.top,true):0;
  if(FD.gap)FD.short=FD.gap;
  const all=!foot||!!foot.text||foot.bash;
  if(all!==FD.whole&&FD.fresh)feedWhole(all);
  else if(all!==FD.whole){if(!FD.wait)FD.wait=setTimeout(()=>{FD.wait=0;const f=FD.foot;if(f===undefined)return;const now=!f||!!f.text||f.bash;if(now!==FD.whole)feedWhole(now)},foot&&foot.text?TEXT_WAIT:FOOT_WAIT)}
  else{clearTimeout(FD.wait);FD.wait=0}
  const jump=b.viewportY<b.baseY||!!(foot&&foot.jump);
  const ended=FD.jump&&!jump, left=!FD.jump&&jump;
  FD.jump=jump;
  const own=feedOwnJump(b.viewportY<b.baseY,foot);if(own!==!!FD.own){FD.own=own;if(typeof pastJumpDraw==='function')pastJumpDraw()}
  if(ended)FD.off=0;  // at its end the last lines stand on the box
  FD.top=FD.off>0&&FD.top||feedOldest(t)&&(!jump&&!!foot&&(!!FD.short||feedGap(lines,foot.top))||!FD.slim&&!!FD.still&&feedRows(lines)===FD.still);  // once pulled, it stays till it is back
  if(ended&&FD.slim)feedSlim(false);
  if(still&&foot&&!FD.whole&&!jump&&FD.short!==wasShort&&!pastUp())feedGlide(feedTop());else feedPlace();
  if(left&&FD.run<=-8)feedSlim(true);
  pastSee();
  const key=f=>f?[f.mode,f.shells,f.tasks,f.agents,f.update,f.status.join('|'),f.work].join():String(f);
  if(foot&&Date.now()-FD.keptAt>FEED_KEEP)feedKeep();
  if(key(was)!==key(foot)){if(!was||!foot||was.work!==foot.work||was.shells!==foot.shells)liveLoad();render()}
}
/* B766: the session has nothing older to scroll to when its first rows stay as they are after an upward scroll it got.
   feedStill ends a look */
const STILL_ROWS=8, STILL_MS=800, feedRows=l=>l.slice(0,STILL_ROWS).join('\n');
// the terminal itself has no line above the view (the agent CLI may have, when it takes the wheel)
const feedOldest=t=>t.modes.mouseTrackingMode!=='none'||!t.buffer.active.viewportY;
function feedStill(){clearTimeout(FD.stillT);FD.stillT=0;FD.rows=''}
function feedStillLook(left,cell){
  if(left>=0)return feedStill();
  const t=feedTerm();if(!t||!FD.drawn||FD.whole||FD.top||FD.stillT)return;
  if(!FD.rows)FD.rows=feedRows(feedLines(t));
  if(FD.run>-3*cell)return;
  const n=FD.n;
  FD.stillT=setTimeout(()=>{
    const was=FD.rows, u=feedTerm();feedStill();
    if(FD.n!==n||!u||!FD.drawn||FD.whole||FD.slim||!feedOldest(u))return;
    if(was===feedRows(feedLines(u))){FD.still=was;feedSee()}
  },STILL_MS);
}
/* a sent message: the session is at its end, the frame with it */
function feedRest(){pastDown(true);if(FD.off&&!FD.jump){FD.off=0;feedPlace()}}
function feedWhole(on){FD.whole=on;if(on){FD.slim=false;FD.off=0}feedClass();feedPlace();render()}
/* B214: the view's height with the keyboard closed: the session's size comes from it, so a keyboard never resizes it.
   A width that changed (rotation) counts again, with the keyboard open too; the bottom inset is off .app then */
function feedRoom(main){
  const w=main.clientWidth, h=main.clientHeight, doc=document.documentElement.clientHeight;
  const kept=kbH?Math.abs(doc-FD.doc)<100:Date.now()<kbStill||TOUCH()&&typingIn(document.activeElement)&&h<FD.full-100;  // the last: a browser that shrinks the page itself
  if(FD.full&&FD.wide===w&&kept)return FD.full;
  FD.wide=w;FD.doc=doc;
  return FD.full=kbH?h+doc-kbH-(parseFloat(getComputedStyle($('app')).getPropertyValue('--sab'))||0):h;
}
/* the dock's height with the keyboard closed and one line in the box */
function dockRest(dock){
  const ta=document.querySelector('#dock [data-in]');let more=0;
  if(ta){const c=getComputedStyle(ta), px=k=>parseFloat(c[k])||0;more=Math.max(0,Math.round(ta.offsetHeight-Math.max(px('minHeight'),px('lineHeight')+px('paddingTop')+px('paddingBottom'))))}
  return dock-more+(kbH?KB_PAD:0);
}
/* B214: the frame goes to its new place with the box, from `was`, its top on screen until now (feedTop). translate, so
   a draw half way may still set its transform */
let feedFly=null;
const feedTop=()=>FD.shown&&FD.frame?$('feedframe').getBoundingClientRect().top:null;
function feedGlide(was){
  if(was==null)return;
  const el=$('feedframe');if(feedFly){const a=feedFly;feedFly=null;a.cancel();el.style.translate='';$('feed').style.bottom=''}
  feedPlace();
  const d=was-el.getBoundingClientRect().top;if(Math.abs(d)<1||!el.animate||calm())return;
  const css=getComputedStyle(document.documentElement), at=`0 ${d}px`, room=$('feed').style;
  const a=feedFly=el.animate([{translate:at},{translate:'0 0'}],{duration:parseFloat(css.getPropertyValue('--dur-slow')),easing:css.getPropertyValue('--ease').trim()});
  pastGlide(d);
  el.style.translate=at;room.bottom=d>0?-d+'px':'';  // it starts below its new room, so that is not cut off yet
  const still=()=>{if(feedFly===a)el.style.translate=''};
  requestAnimationFrame(()=>requestAnimationFrame(still));  // iOS draws one frame before the animation
  a.onfinish=a.oncancel=()=>{if(feedFly===a){still();feedFly=null;room.bottom=''}};
}
/* the box grew or shrank: as .dock does it, over the glide for a keyboard that may still go on */
let feedGrew=null;
function feedGrow(d){
  if(feedGrew)feedGrew.cancel();
  feedGrew=moAnim($('feedframe'),[{translate:`0 ${d}px`},{translate:'0 0'}],{ease:'--ease',dur:'--dur-slow',composite:'add'});
}
/* B218: the slim message box's row: the box's own bottom edge, 44px and 4px. Its height is the same with the keyboard open */
function slimGap(){const d=$('dock'), b=d&&d.querySelector('.box');return b?Math.round(d.getBoundingClientRect().bottom-b.getBoundingClientRect().bottom):0}
function slimRow(){const g=slimGap();return g?48+g+(kbH?KB_PAD:0):SLIM_H}
/* B218: how far the bars' motion goes: the dock's and the box's height over the slim box's, and how far its words ride */
function slimSize(){
  const m=document.querySelector('.main'), d=$('dock'), b=d&&d.querySelector('.box'), ta=b&&b.querySelector('[data-in]');if(!ta||!FD.shown)return;
  const by=Math.max(0,b.offsetHeight-44), c=getComputedStyle(ta);
  const mid=ta.getBoundingClientRect().top-b.getBoundingClientRect().top+parseFloat(c.paddingTop)+parseFloat(c.lineHeight)/2-22;  // the first line's middle over a slim row's
  const set=(k,v)=>m.style.setProperty(k,v), o=+getComputedStyle(d).opacity, rest=o===0||o===1;
  if(rest)m.classList.add('still');  // nothing moves now: the new sizes are not a motion
  set('--slimd',by);set('--slimride',by-Math.min(8,Math.max(0,mid))+'px');set('--slimgap',slimGap()+'px');
  const f=d.querySelector('.foot');setHTML($('slimfoot'),f?f.innerHTML:'');
  set('--slimtop',$('top').offsetHeight+document.querySelector('.notices').offsetHeight+'px');
  if(rest){for(const e of [d,b,$('top'),document.querySelector('.notices'),$('slimbox'),...document.querySelectorAll('.slimground,.slimskin i')])getComputedStyle(e).translate;m.classList.remove('still')}
}
/* what the frame's place is made of; null while there is none */
function feedPlace(){
  const main=document.querySelector('.main'), box=$('feedframe');if(!FD.shown||!main||!main.clientHeight)return;
  if(!FD.drawn||FD.muted){main.style.setProperty('--feeddock',document.querySelector('.dockwrap').offsetHeight+'px');main.style.setProperty('--feedbar',$('top').offsetHeight+document.querySelector('.notices').offsetHeight+'px')}
  const gap=slimGap();if(gap)main.style.setProperty('--slimgap',gap+'px');
  if(!FD.frame){main.style.setProperty('--seebar',$('top').offsetHeight+'px');return}
  const top=$('top').offsetHeight, say=document.querySelector('.notices').offsetHeight;
  main.style.setProperty('--seebar',top+'px');
  if(!FD.slim||!FD.bar)FD.bar=top+say;
  const dock=document.querySelector('.dockwrap').offsetHeight, f=feedScreen(true);
  const cell=f?f.cell:17, pad=f?f.el.getBoundingClientRect().top:12;
  const card=document.querySelector('#dock .qcard');
  const row=slimRow(), full=feedRoom(main), high=FD.whole?feedWholeHigh(full-FD.bar-dockRest(dock),pad,cell,card?card.offsetHeight:0):Math.round(full-row+FOOT_ROWS*cell);
  const size=[full,cell].join(), above=main.clientHeight-dock+dockRest(dock), hold=(FD.jump||FD.off>0)&&FD.held===size?FD.t+above-FD.above:null;  // scrolled up: where it was over the box; a chip or a file that comes moves nothing
  const o={main:main.clientHeight,bar:FD.bar,dock,row,high,pad,cell,foot:FD.foot,short:FD.short,whole:FD.whole,last:FD.last,off:FD.off,top:FD.top,hold};
  let at=feedSpot(o);if(!FD.jump&&hold!=null&&!at.off)at=feedSpot({...o,off:0,hold:null});
  if(!FD.whole&&FD.foot===undefined)at.t=Math.min(FD.bar,main.clientHeight-dock-high+FOOT_ROWS*cell);  // not read yet
  main.classList.toggle('pulled',at.off>0);
  FD.far=at.far;FD.off=at.off;FD.t=at.t;FD.above=above;FD.held=FD.whole||!FD.foot?'':size;
  const st=box.style, set=(k,v)=>{if(st[k]!==v)st[k]=v};
  set('inset','0 0 auto 0');set('height',high+'px');set('transform',`translateY(${Math.round(at.t)}px)`);
  const b=FD.drawn&&f&&f.t.buffer.active, away=b&&b.type==='normal'?(b.baseY-b.viewportY)*cell:0;
  set('clipPath',at.cut>away?`inset(0 0 ${Math.round(at.cut-away)}px 0)`:'none');
  pastPlace();
}
/* the bars and the box away, or back. Never while the person types, or while a menu, a question or a sheet is open */
const slimMay=()=>!QN.held.has(FD.n)&&!FD.whole&&!!FD.foot&&(pastUp()||FD.jump&&FD.far>8)&&!S.sheet&&!slashOpen()&&!kbH&&Date.now()-FD.typed>2500&&!(document.activeElement&&document.activeElement.matches('[data-in]')&&document.activeElement.value.trim());
function feedSlim(on){if(on&&!slimMay())return;FD.run=0;if(FD.slim!==on){slimSize();FD.slim=on;feedClass();slimDraw()}}
/* a drag or a wheel of px (down is more): the bars go or come, and what is left of it for the session to scroll */
function feedScroll(px){
  if(!px||!FD.shown)return px;
  const b=feedBars(px,FD);FD.run=b.run;
  if(b.slim!==FD.slim)feedSlim(b.slim);
  const take=feedShare(px,FD), f=feedScreen();
  if(f)feedStillLook(px-take,f.cell);
  if(!take)return px;
  FD.t-=take;FD.off-=take;feedPlace();
  return px-take;
}
/* a wheel step in the frame (session_frame.HEAD asks): was it the page's? What the frame leaves goes on to the session */
function feedTake(px){
  if(pastWheel(px))return true;
  const left=feedScroll(px), f=feedScreen();if(left===px||!f)return false;
  const [n,rest]=feedSteps(FD.rest+left,f.cell*FEED_LINES), r=$('feedtouch').getBoundingClientRect();
  FD.rest=rest;feedWheel(n,r.width/2||FD.frame.clientWidth/2,r.height/2||FD.frame.clientHeight/2);
  return true;
}
/* B190: a key or a paste in the frame (session_frame.HEAD asks): was it the page's? Its words go in the message box */
function feedTyped(e,paste){
  if(!paste&&!S.sheet&&pastPress(e))return true;
  const ta=document.querySelector('[data-in]'), how=S.sheet?'':feedHand(paste?{paste}:e,FD.foot,FD.whole);
  if(how==='line')return sessType('\n');
  if(how!=='box'||!ta)return false;
  if(FD.slim)feedSlim(false);  // the box was away and inert
  ta.focus({preventScroll:true});
  ta.setRangeText(paste||(e.key==='Enter'?'\n':e.key),ta.selectionStart,ta.selectionEnd,'end');
  ta.dispatchEvent(new Event('input',{bubbles:true}));
  return true;
}
/* a point on the touch layer, in the frame */
function feedAt(x,y){const l=$('feedtouch').getBoundingClientRect(), r=FD.frame.getBoundingClientRect();return[x+l.left-r.left,y+l.top-r.top]}
/* the run's word on the session: its status, its background work */
async function liveLoad(){
  const n=FD.n, turn=FD.turn;if(!n||!FD.frame||document.hidden||!/^[cs]\d+$/.test(n))return;
  FD.liveAt=Date.now();
  const j=await liveGet(n);
  if(turn!==FD.turn||FD.n!==n||!j)return;
  const first=!FD.live, same=JSON.stringify(FD.live)===JSON.stringify(j);FD.live=j;
  const moved=same?()=>{}:questionMove(n,first);  // F192a1
  if(!same){render();sendRedraw()}
  moved();
}
const workFor=()=>FD.live&&FD.live.status==='busy'&&FD.live.since?'Working '+forWords(Date.now()/1000-FD.live.since):'Working';
/* B192: the message box's one row while the reader is scrolled up: its words, Working (its sheet) and Stop */
function slimDraw(){
  const ta=document.querySelector('[data-in]'), words=ta&&ta.value.trim(), on=FD.n&&sessWorks(FD.n);
  setHTML($('slimbox'),`<div><button type="button" data-slimbox aria-label="Show the message box"><span class="pr" aria-hidden="true">&gt;</span><span${words?' class="draft"':''}>${esc(words||(ta?ta.placeholder:''))}</span></button>${on?`<button type="button" data-sheet="sesswork"><span class="livedot"></span><span data-workfor>Working</span></button><button type="button" data-halt="${esc(FD.n)}">${I.stop}Stop</button>`:''}</div>`);workDraw()}
function workDraw(){for(const e of document.querySelectorAll('[data-workfor]')){const w=workFor();if(e.textContent!==w)e.textContent=w}}
setInterval(()=>{if(!FD.shown||document.hidden)return;workDraw();if(feedMute()!==FD.muted){feedSkin();feedPlace()}if(Date.now()-FD.liveAt>=LIVE_EVERY)liveLoad()},1000);
addEventListener('input',e=>{if(e.target.matches&&e.target.matches('[data-in]')){FD.typed=Date.now();if(FD.slim)feedSlim(false)}});
addEventListener('keydown',e=>{if(FD.slim&&e.target.matches&&e.target.matches('[data-in]')&&e.key!=='Escape')feedSlim(false)});
/* F406g: the provider's name and model of a chat on the harness loop ('' for another), or of a new one */
const modelOf=n=>/^c\d+$/.test(n||'')?(sessionOf(n)||{}).model||(FD.n===n&&FD.live&&FD.live.harness?S.snap.chat_model||'Model':''):isAgent(n)&&n?'':S.snap.chat_model||'';
/* the row above the box: what there is to say, each a sheet; a menu or a question on the screen has the key row in its place, not with an open question card */
const sessUp=n=>{const st=feedNow(n);return st==='session'||st==='loading'&&sessionOf(n)};
function sessRow(n){
  if(!sessUp(n))return QN.mark.has(n)?questionCard(n):'';  // F192a2: what is sent is still about it; F206a: there from the first frame, so what stands over it does not move
  const model=modelOf(n), ask=questionCard(n);
  if(!model&&FD.foot===null&&FD.whole)return ask+(TOUCH()&&!keysShown()&&!keysCard()?keyButtons():'');
  const w=sessWorks(n), icon={work:'<span class="livedot"></span>',update:'<span class="bdot"></span>'};
  setTimeout(slimDraw,0);
  return ask+`<div class="schips" role="group" aria-label="The session">${sessionChips({foot:FD.foot,live:FD.live,working:w,model}).map(c=>`<button type="button" class="chip${c.key==='update'?' up':''}" data-sheet="${c.key==='mode'?'sessmode':'sess'+c.key}">${icon[c.key]||''}${c.key==='work'?'<span data-workfor>Working</span>':esc(c.label)}</button>`).join('')}</div>`;
}
const sessTasks=kind=>((FD.live||{}).tasks||[]).filter(t=>t.kind===kind);
const taskWhen=t=>t.running?`running${t.at?' '+forWords(Date.now()/1000-t.at).replace(/ \d+s$/,''):''}`:'done';
const sessIdle=()=>!!(FD.live&&FD.live.status==='idle');
/* typing into the session, one step at a time: each waits for what the screen then says */
const sessType=x=>{const t=feedTerm();if(t)t.input(x,true);return!!t};
async function sessWait(ok,ms){for(const end=Date.now()+ms;Date.now()<end;){const t=feedTerm(), l=t?feedLines(t):[];const got=ok(l);if(got)return got;await new Promise(r=>setTimeout(r,60))}return null}
const promptOf=l=>{const f=feedFoot(l,()=>true);return f&&!f.bash?f:null};
async function setMode(key){
  if(FD.task)return;
  const label=FEED_MODES.find(m=>m[0]===key)[1], n=FD.n, now=l=>{const f=promptOf(l);return f&&f.mode};
  if(!FD.foot||!FD.foot.mode)return toast('Its mode cannot be read off the window now',true);
  FD.task='mode';
  try{
    for(let i=0,at=FD.foot.mode;at!==key;i++){
      if(i>6||FD.n!==n||!sessType('\x1b[Z'))return toast(`The session did not go to ${label}`,true);
      const was=at;at=await sessWait(l=>{const m=now(l);return m&&m!==was&&m},2000);
      if(!at)return toast(`The session did not go to ${label}`,true);
    }
    toast(`Mode: ${label}`);
  }finally{FD.task=''}
}
/* Stop on a shell, Open on an agent: through the agent CLI's own list (/tasks). The message box is never used */
async function sessTask(t,what){
  const n=FD.n, no=why=>toast(`${what==='stop'?'Not stopped':'Not opened'}: ${why}`,true);
  if(FD.task)return;
  if(!FD.foot||FD.foot.text||FD.foot.bash)return no('its prompt is not free');
  const same=x=>t.name.startsWith(x.name)||x.name.startsWith(t.name), open=l=>l.some(x=>/x to stop|to select|Esc to close/i.test(x));
  const away=async()=>{for(let i=0;i<3;i++){const t2=feedTerm();if(!t2||promptOf(feedLines(t2)))return;sessType('\x1b');await sessWait(promptOf,900)}};
  FD.task=what;
  try{
    sessType('/tasks');await sessWait(l=>{const f=feedFoot(l,()=>false);return f&&/\/tasks/.test(f.text)},2000);sessType('\r');
    if(!await sessWait(open,4000)){await away();return no('its list did not open')}
    let lines=feedLines(feedTerm()), rows=taskLines(lines);
    if(!rows.length&&!lines.some(l=>l.includes(t.name.slice(0,24)))){await away();return no('it is not in its list')}
    if(rows.length){
      const like=rows.filter(same), mine=like.find(x=>x.running)||like[0];
      if(!mine||like.filter(x=>x.running).length>1){await away();return no(mine?'more than one has that name':'it is not in its list')}
      for(let i=0;i<30;i++){
        rows=taskLines(feedLines(feedTerm()));const on=rows.findIndex(x=>x.on), to=rows.findIndex(x=>same(x)&&x.running===mine.running);
        if(to<0||on<0){await away();return no('it is not in its list')}
        if(on===to)break;
        sessType(on<to?'\x1b[B':'\x1b[A');await sessWait(l=>taskLines(l).findIndex(x=>x.on)!==on,900);
        if(i===29||FD.n!==n){await away();return no('its list did not move')}
      }
      if(what==='open'){sessType('\r');return}
    }else if(what==='open')return;
    sessType('x');
    const done=await sessWait(l=>promptOf(l)||!taskLines(l).some(x=>same(x)&&x.running)&&l.some(x=>/Background|No tasks/.test(x)),4000);
    await away();liveLoad();
    if(done)toast('Stopped');else no('it still runs');
  }finally{FD.task=''}
}
const greeting=()=>{const h=new Date().getHours();return h<12?'Good morning':h<18?'Good afternoon':'Good evening'};
/* F426a: Home is about the person: talk, answer, jump; the run and the plan are one line each, which opens its view */
function homeHTML(){
  const off=homeStart();
  return `<div class="col">${off}<div class="greet">${LOGO()}${greeting()}</div><button class="btn${off?'':' acc'} talkbig" data-view="talk">${I.talk}Talk</button>${box('How can I help with the run?',keysLine(!!S.snap.chat_model))}${ttydLine()}
    ${homeChips()}${needsSec()}${homeSums()}</div>`;
}
/* the chat that last had something said in it, pinned or not, and the one run control that fits now */
function homeChips(){
  const last=chatSort(chats(),[]).find(s=>s.at>0), c=controlOf(cardControls(S.snap).find(k=>k==='pause'||k==='go_on'));
  return `<div class="chips homechips">${last?`<button class="chip" data-thread="${esc(last.name)}" title="${esc(chatTitle(last))}">${I.back}Last chat</button>`:''}<button class="chip" data-about="new">${I.plus}Add a task</button>${c?`<button class="chip${ctlBusy(c.key)?' busy':''}" data-ctl="${esc(c.key)}">${I[CTL_ICON[c.key]]}${esc(c.label)}</button>`:''}<button class="chip" data-quick="since">${I.clock}Since my last look</button></div>${obCards(x=>/^(pause|go_on):/.test(x.ctl||''))}`;
}
const homeSums=()=>card([['status','Now',homeStatus(S.snap,working_())],['plan','Queue',homePlan(S.snap)]].map(([v,l,w])=>`<button class="fold sumrow" data-view="${v}" data-k="sum:${v}" data-v="${esc(w)}"><span class="grow ell">${esc(w)}</span><span class="small">${l}</span><span class="chev">${I.chev}</span></button>`).join(''),'sums','data-k="sums"');
function homeStatus(snap,ws){
  if(snap.up===false)return 'No run is up';
  const m=mergeRows(snap).length, n=ws.filter(s=>s.state!=='merging').length, st=runPill(snap).text;
  return(st&&st!=='Running'?st+' · ':'')+([n?`${n} working`:'',m?`${m} merging`:''].filter(Boolean).join(', ')||'No agent is working');
}
function homePlan(snap){
  const n=planQueue(snap).length, q=releasesOn(snap)&&planReleases(snap).find(x=>!x.placeholder), r=q&&q.release;
  const w=r&&({releasing:'releasing now',blocked:'next release blocked',next:'release next',waits:`next release waits for ${(r.waits||[]).length}`})[r.state];
  return(n?`${n} left`:'The queue is empty')+(w?', '+w:'');
}
/* B120: without ttyd, one line says a chat needs it to show its session, with this machine's install command */
const ttydLine=()=>S.snap.terminal_mode==='install'?`<div class="small ttyd" data-ttyd>A chat shows the real session with ttyd, which this machine lacks: ${S.snap.ttyd_install?`install it with <code>${esc(S.snap.ttyd_install)}</code>`:'install your platform\'s ttyd package'}.</div>`:'';
const needsSec=()=>{const cs=chatNeedsShown();  // B832: a chat's question first
  return `<div class="sec">Needs you<span class="ln"></span></div>${obCards(x=>x.need)}${cs.map(chatNeedCard).join('')}${S.snap.needs.length?S.snap.needs.map(needCard).join(''):cs.length?'':emptyCard('Nothing needs you.')}`};
/* F193: with releases off, only a New release sent before that, until it is settled */
/* F186: New release: says which release is open already, and then asks before it queues another */
function newReleaseCard(){
  if(!releasesOn(S.snap))return obCards(x=>obActs(x,'release'));
  const ws=working_(), said=S.snap.release_said||'';
  const acts=(S.snap.release_acts||[]).filter(k=>ws.length||k!=='release_wait').map(controlOf).filter(Boolean);
  const sure=acts.filter(c=>c.confirm&&S.sure===c.key).map(c=>ctlSure(c)).join('');
  return obCards(x=>obActs(x,'release'))+card(`<div class="srow"><div class="row"><div class="grow"><b>New release</b>${sure?'':`<div class="small" data-k="relsaid" data-v="${esc(said)}">${esc(said?said+'.':ws.length?`Waits for the ${ws.length} task${ws.length>1?'s':''} still working.`:'Releases what has landed.')}</div>`}</div></div>${sure||`<div class="btns">${acts.map((c,i)=>`<button class="btn ${i===0?'acc':''}${ctlBusy(c.key)?' busy':''}" data-ctl="${esc(c.key)}">${esc(c.label)}</button>`).join('')}</div>`}</div>`,'','data-k="release"')}
/* F426f: the page's one age helper; `tail` (' ago', in a sentence) follows every age but now */
const agoWords=(at,tail='')=>{const m=Math.max(0,Math.round((Date.now()-new Date(at).getTime())/60000));return isNaN(m)?'':m<1?'now':(m<60?`${m} min`:m<48*60?`${Math.floor(m/60)} h`:`${Math.floor(m/1440)} d`)+tail};

/* F206: the title's switcher: the chats in the sidebar's order, each with its last line */
function chatsSheet(){
  const g=shownChats(), row=s=>{
    if(s.response)return `<button class="it swc response" data-thread="${esc(s.name)}" data-k="swc:${esc(s.name)}"><span class="grow"><span class="ell">${esc(s.label)}</span><span class="small ell">${esc('You: '+plain(s.answer))}</span></span>${responseNew(s)}</button>`;  // F425b
    const n=s.name, f=S.feeds[n], said=plain(chatLast(feedOf(n),busy(n))), on=S.thread===n;
    return `<button class="it swc" data-thread="${esc(n)}" data-k="swc:${esc(n)}"${on?' aria-current="true"':''}><span class="grow"><span class="ell">${esc(chatTitle(s))}</span><span class="small ell">${esc(said||(f?' ':'Loading…'))}</span></span>${replyDue(s)?'<span class="bdot" role="img" aria-label="needs your reply"></span>':on?I.check:''}</button>`};
  const n=S.thread, own=n&&sessionOf(n)&&!isAgent(n);
  return `<h2>Chats</h2>${g.top.map(row).join('')}${g.quiet.length?`<div class="sec">Quiet<span class="ln"></span></div>${g.quiet.map(row).join('')}`:''}${own?`<div class="btns"><button class="btn" data-ren="${esc(n)}">Rename this chat</button></div>`:''}`;
}
function chatsLoad(){for(const s of chats().slice(0,40))if(!S.feeds[s.name]||Date.now()-(S.feeds[s.name].at||0)>4000)loadFeed(s.name)}
setInterval(()=>{if(S.sheet==='chats'&&!document.hidden)chatsLoad()},5000);
