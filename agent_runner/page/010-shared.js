const T=new URLSearchParams(location.search).get('t')||'';
const tq=p=>p+(p.includes('?')?'&':'?')+'t='+encodeURIComponent(T);
/* F134: Runner Home around this page ('' when the page is the run's own, not reached through Home) */
const HB=homeBase(location.pathname,HOME_PAGE), HKEY=homeKey(location.pathname);
/* B179: on the Home Screen the page is an app of its own: no tabs, no browser Back */
const ON_HOME_SCREEN=navigator.standalone===true||!!(window.matchMedia&&matchMedia('(display-mode:standalone)').matches);
const ROOT=HB||location.pathname.replace(/[^/]*$/,'');
(function homeScreen(){
  const add=(rel,href)=>{const l=document.createElement('link');l.rel=rel;l.href=href;document.head.appendChild(l)};
  add('manifest',manifestLink(HB,HKEY,T));add('apple-touch-icon',(HB||'./')+'icon-180.png?t='+encodeURIComponent(T));
  const m=document.createElement('meta');m.name='apple-mobile-web-app-title';
  m.content=HOME_PAGE&&!HKEY?'Runner Home':HKEY||document.title.replace(/ · runner$/,'');document.head.appendChild(m);
})();
const H={projects:null,login:'',machine:'',devices:null,alerts:[],err:'',said:'',turn:0,begun:{},more:false,at:0};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ic=d=>`<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const I={
  keys:ic('<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>'),
 menu:ic('<path d="M4 7h16M4 12h16M4 17h10"/>'),
 edit:ic('<path d="M12 20h8"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
 talk:ic('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/>'),  // F93: a mic
 home:ic('<path d="M4 10.5 12 4l8 6.5V20H4z"/><path d="M10 20v-5h4v5"/>'),
 status:ic('<path d="M3 12h4l3-7 4 14 3-7h4"/>'),
 tools:ic('<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M10.5 18.5h3"/>'),  // F169: a device
 settings:ic('<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>'),  // F97
 speak:ic('<path d="M4 9.5v5h3.5L12 19V5L7.5 9.5z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a8 8 0 0 1 0 11"/>'),
 mute:ic('<path d="M4 9.5v5h3.5L12 19V5L7.5 9.5z"/><path d="M16 10l5 5M21 10l-5 5"/>'),
 keys:ic('<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8"/>'),
 down:ic('<path d="M12 5v14M6 13l6 6 6-6"/>'),
 dots:ic('<path d="M5 12h.01M12 12h.01M19 12h.01" stroke-width="2.6"/>'),
 plan:ic('<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r=".6"/><circle cx="4" cy="12" r=".6"/><circle cx="4" cy="18" r=".6"/>'),
 projects:ic('<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>'),  // F134
 concepts:ic('<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>'),  // F87: a bulb
 plus:ic('<path d="M12 5v14M5 12h14"/>'),
 pin:ic('<path d="M9 4h6l-1 6 3 3v1H7v-1l3-3z"/><path d="M12 14v6"/>'),  // F133
 trash:ic('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>'),  // F118
 clip:ic('<path d="M21 11.5 12.5 20a5 5 0 0 1-7-7L14 4.5a3.4 3.4 0 0 1 4.8 4.8L10.4 17.7a1.8 1.8 0 0 1-2.6-2.6L15.5 7.5"/>'),
 up:ic('<path d="M12 19V5M6 11l6-6 6 6"/>'),
 send:ic('<path d="M12 19V5M6 11l6-6 6 6"/><path class="forcemark" d="M6 18l6-6 6 6"/>'),  // B208: its second head shows for Force send alone
 stop:ic('<rect x="7" y="7" width="10" height="10" rx="1.5"/>'),
 back:ic('<path d="M15 5l-7 7 7 7"/>'),
 chev:ic('<path d="M9 6l6 6-6 6"/>'),
 clock:ic('<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>'),
 check:ic('<path d="M5 12.5l4.5 4.5L19 7"/>'),
 play:ic('<path d="M8 5v14l11-7z"/>'),
 alert:ic('<path d="M12 8v5M12 16.5v.5"/><circle cx="12" cy="12" r="9"/>'),
 dot:ic('<circle cx="12" cy="12" r="2"/>'),
 file:ic('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'),
 ask:ic('<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17v.5"/>'),
 term:ic('<rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M7 9.5l3 2.5-3 2.5M12.5 15H17"/>'),
 ext:ic('<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>')};
const LOGLINE_ICON={ok:'check',bad:'alert',go:'play','':'dot'};

const S={snap:{status:[],sessions:[],queue:[],needs:[],concepts:[],log:[],release:'',machine:'',slots:0},
  view:'home',thread:null,ctx:null,atts:{},drawer:false,feeds:{},sent:{},waitNew:null,online:true,
  sheet:'',askShot:-1,askFold:{},ren:null,f:{},taskOpen:{},tasks:{},set:null,setOpen:{},setChanged:false,
  sel:[],selLast:'',undo:null};  // F118: chats picked for delete, the last one clicked, a delete Undo can still take back
const $=id=>document.getElementById(id);
/* B153: the project's name (the top-left, the chat's lead label) and its first letter (the logo) */
const PN=()=>S.snap.project||HKEY||'agent-runner', LOGO=()=>`<span class="logo">${esc(PN().charAt(0).toLowerCase())}</span>`;
const store={get(k){try{return localStorage.getItem(k)||''}catch(e){return''}},
  set(k,v){try{v?localStorage.setItem(k,v):localStorage.removeItem(k)}catch(e){}}};
/* B177: this browser tab's own, kept over a reload */
const tabStore={get(k){try{return sessionStorage.getItem(k)||''}catch(e){return''}},
  set(k,v){try{v?sessionStorage.setItem(k,v):sessionStorage.removeItem(k)}catch(e){}}};
/* B200: what is kept by chat is kept by project too, as each has a c1 (Runner Home serves every project from one address) */
const CHATS_OF=HKEY?HKEY+':':'';
const DRAFT_KEY=k=>'ar-draft:'+CHATS_OF+k;  /* a box's draft, kept per thread (and Home) across refreshes */
const boxKey=()=>S.thread||(S.view==='talk'?'talk':'home');
/* B202: a starting chat's box gets another key: its attachments (attsMove), its draft (after one already there) and the dictation that fills it go along */
function boxMove(from,to){
  S.atts=attsMove(S.atts,from,to);if(from===to)return;
  const d=store.get(DRAFT_KEY(from)), was=store.get(DRAFT_KEY(to)), join=v=>was&&v?`${was}\n${v}`:was||v;
  if(d){store.set(DRAFT_KEY(to),join(d));store.set(DRAFT_KEY(from),'')}
  if(DK.rec&&DK.key===from){DK.key=to;DK.base=join(DK.base)}
}
/* B141: the session the page shows, which Ctrl+C and Stop interrupt: the open chat, else the Talk session in
   the Talk view ('' before it has one); F176: none on Home and the other views, whose message starts a new chat */
const shownSession=()=>isNew(S.thread)?'':S.thread||(S.view==='talk'?talkName():'');
/* B120: each chat's sent messages (localStorage, so a reload keeps them; store's try/catch when it is blocked), and
   HI where Up / Down stands in them: the chat, the place (null: not looking back) and the draft it left */
const HIST_KEY=k=>'ar-hist:'+CHATS_OF+k;
function histGet(k){try{const l=JSON.parse(store.get(HIST_KEY(k))||'[]');return Array.isArray(l)?l.filter(x=>typeof x==='string'):[]}catch(e){return[]}}
function histAdd(k,text){store.set(HIST_KEY(k),JSON.stringify(histPush(histGet(k),text)))}
let HI={key:'',i:null,draft:''};
function histKey(e,ta){
  if(e.shiftKey||e.altKey||e.ctrlKey||e.metaKey||e.isComposing||!histEdge(ta.value,ta.selectionStart,ta.selectionEnd,e.key))return false;
  const k=boxKey(), l=histGet(k);if(!l.length)return false;
  if(HI.key!==k||HI.i===null){if(e.key==='ArrowDown')return false;HI={key:k,i:l.length,draft:ta.value}}
  const i=histStep(l.length,HI.i,e.key);
  HI.i=i;ta.value=i===l.length?HI.draft:l[i];if(i===l.length)HI.i=null;
  if(HI.i===null)store.set(DRAFT_KEY(k),ta.value);  // a recalled message is not saved as the draft
  grow(ta);ta.setSelectionRange(ta.value.length,ta.value.length);
  return true;
}

/* F83: a refresh draws a part again only when its markup changed */
function setHTML(el,h){if(!el||el._h===h)return false;el._h=h;el.innerHTML=h;return true}
/* F83: the reading position over a redraw of box: call before, then call what it returns after. The first keyed thing
   on screen stays where it was (at the very top, new things show); a code block keeps its sideways scroll. */
function keepScroll(box){
  const was=box.scrollTop, edge=box.getBoundingClientRect().top;let key='',y=0;  // where things are laid out: not a glide under way
  if(was>2)for(const el of box.querySelectorAll('[data-k]')){const b=el.getBoundingClientRect(), fly=flying(el);if(b.bottom-fly>edge+1){key=el.dataset.k;y=b.top-fly;break}}
  const pre=[...box.querySelectorAll('pre')].map(p=>p.scrollLeft);
  return()=>{
    [...box.querySelectorAll('pre')].forEach((p,i)=>{if(pre[i])p.scrollLeft=pre[i]});
    box.scrollTop=was;
    const el=key&&[...box.querySelectorAll('[data-k]')].find(e=>e.dataset.k===key);
    if(el)box.scrollTop+=el.getBoundingClientRect().top-y;
  };
}
/* F147: motion (docs/STYLE.md, Motion). born: when a key came in, so a redraw half way goes on from there; fly: what
   glides now; said: how long a reply was; sent: the words on their way out of the message box; vt: a View Transition */
const MO={born:new Map(),said:new Map(),grown:new Map(),rolls:new Map(),fly:new Map(),sent:null,vt:null,scroll:new Map(),folded:0}, MO_MS=450;
const calm=()=>document.hidden||matchMedia('(prefers-reduced-motion:reduce)').matches;
function moAnim(el,frames,o){
  if(!el.animate||calm())return null;
  const css=getComputedStyle(document.documentElement), {ease='--spring',dur='--dur-spring',...more}=o||{};
  return el.animate(frames,{duration:parseFloat(css.getPropertyValue(dur)),easing:css.getPropertyValue(ease).trim(),...more});
}
/* F189b: a press on a fold or in a sheet: what opens, closes or moves for it does so on one curve, also over a redraw in this time */
const FOLD_MO={ease:'--spring-soft'}, folding=()=>Date.now()-MO.folded<MO_MS;
/* an element moved by (x, y) on its way to its place; flying: how far down a thing (or what holds it) is moved now */
function glideTo(el,x,y,o){
  const old=MO.fly.get(el);if(old)old.cancel();
  const a=moAnim(el,[{transform:`translate(${x}px,${y}px)`},{transform:'none'}],o);if(!a)return;
  MO.fly.set(el,a);a.onfinish=a.oncancel=()=>{if(MO.fly.get(el)===a)MO.fly.delete(el)};
}
/* F189a: box's scroll glides to its place (to: how far down, or a function of the box, asked again on every frame). The scroll
   itself moves, so a redraw under way goes on; calm() is at once, and the person's own hand on box takes it over */
function scrollGlide(box,to){
  let off=0;  // how far something else moved the scroll meanwhile: a refresh holding the place, a key
  const at=()=>Math.max(0,Math.min(typeof to==='function'?to(box):to+off,box.scrollHeight-box.clientHeight)), old=MO.scroll.get(box);
  if(old&&(old.to===to||Math.abs(old.at()-at())<1))return;
  scrollStop(box);
  const a=Math.abs(at()-box.scrollTop)<1?null:moAnim(box,[],{ease:'--spring-soft'});  // it draws nothing: its time and easing
  if(!a){box.scrollTop=at();return}
  const g={a,to,at,from:box.scrollTop,last:box.scrollTop};MO.scroll.set(box,g);
  const step=()=>{
    if(MO.scroll.get(box)!==g)return;
    const p=a.playState==='finished'||!box.isConnected?null:a.effect.getComputedTiming().progress;
    const by=box.scrollTop-g.last;if(Math.abs(by)>=1){off+=by;g.from+=by}
    box.scrollTop=p===null?at():g.from+(at()-g.from)*p;g.last=box.scrollTop;
    if(p===null)MO.scroll.delete(box);else requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
function scrollStop(box){const g=MO.scroll.get(box);if(g){MO.scroll.delete(box);g.a.cancel()}}
/* the end of a box that scrolls */
const endOf=b=>b.scrollHeight-b.clientHeight;
const shiftOf=el=>new DOMMatrix(getComputedStyle(el).transform);
function flying(el){let d=0;for(const x of MO.fly.keys()){if(!x.isConnected)MO.fly.delete(x);else if(x===el||x.contains(el))d+=shiftOf(x).m42}return d}
for(const t of ['pointerdown','touchstart','wheel'])document.addEventListener(t,e=>{for(const b of [...MO.scroll.keys()])if(b.contains(e.target)){scrollStop(b);if(b===$('body')&&chatShown())S.pin=atEnd(b)}},{capture:true,passive:true});
/* the lists: where each thing was on screen before a redraw, then each glides from there; what left collapses */
const GLIDES='[data-k],.col>.sec,#sheet>:not(.askbody,.gone0),.askbody>*', LEAVES='.card,.srow,.lrow,.ev,.crow,.qline,.foldin';
const glideKey=el=>el.dataset.k||'sec:'+el.textContent.replace(/\d+/g,'');
function glideSpot(box){
  if(!S.live||!box.animate||calm()||!folding()&&box.contains(document.activeElement)&&document.activeElement.matches('[data-f]'))return null;
  const e=box.getBoundingClientRect(), m=new Map();
  for(const el of box.querySelectorAll(GLIDES)){const k=glideKey(el), r=el.getBoundingClientRect();if(!m.has(k))m.set(k,{el,r,h:el._edge?shotSeen(el).bottom-r.top:r.height,on:r.bottom>e.top&&r.top<e.bottom})}
  return m;
}
function glide(scroller,root,was){
  if(!was||!was.size)return;
  const e=scroller.getBoundingClientRect(), now=new Map(), o=folding()?FOLD_MO:undefined;
  for(const el of root.querySelectorAll(GLIDES)){const k=glideKey(el);if(!now.has(k))now.set(k,{el,r:el.getBoundingClientRect()})}
  const by=new Map();
  for(const [k,n] of now){
    const w=was.get(k), p=n.el.parentElement.closest('[data-k]'), up=p&&by.get(p)||[0,0];
    const d=w&&(w.on||n.r.bottom>e.top&&n.r.top<e.bottom)?[w.r.left-n.r.left,w.r.top-n.r.top]:!w&&o&&n.el.matches('.foldin')&&by.get(n.el.previousElementSibling)||up;  // what opens goes with its button
    if(n.el.matches('.pill')){by.set(n.el,d);if(w&&Math.abs(w.r.width-n.r.width)>1){n.el.style.transformOrigin='0 50%';moAnim(n.el,[{transform:`translateX(${d[0]}px) scaleX(${w.r.width/n.r.width})`},{transform:'none'}])}continue}
    const x=d[0]-up[0], y=d[1]-up[1], far=Math.abs(y)>e.height||Math.abs(x)>e.width;
    by.set(n.el,far?up:d);
    if(!far&&(Math.abs(x)>=1||Math.abs(y)>=1))glideTo(n.el,x,y,o);
    if(o&&w&&n.el.matches('.card'))foldEdge(n.el,w.h,n.r.height);
  }
  const left=[...was].filter(([k,w])=>w.on&&!now.has(k)&&w.el.matches(LEAVES)&&!w.el.closest('.msgs')).map(x=>x[1]);
  const tops=left.filter(w=>!left.some(o=>o!==w&&o.el.contains(w.el)));
  if(tops.length>8&&!o)return;
  for(const w of tops){
    const q=w.el.matches('.foldin')&&[w.el.previousElementSibling,w.el.parentElement.closest(GLIDES)].map(x=>x&&now.get(glideKey(x))).find(Boolean);
    leave(scroller,w,e,q&&by.get(q.el));  // what closes goes with its button
  }
}
/* a card that a fold made taller or shorter: its lower edge moves there; a clip, with room kept for what it lost */
function foldEdge(el,was,now){
  const d=now-was, round=getComputedStyle(el).borderRadius||'0px', at=y=>({clipPath:`inset(0px 0px ${y}px 0px round ${round})`});if(Math.abs(d)<1)return;
  const a=moAnim(el,d>0?[at(d),at(0)]:[at(0),at(-d)],FOLD_MO);if(!a)return;
  el._edge=true;  // a redraw half way goes on from the edge as seen
  const end=()=>{el._edge=false;el.style.paddingBottom=el.style.marginBottom=''};
  a.onfinish=a.oncancel=end;if(d>0)return;
  el.style.paddingBottom=parseFloat(getComputedStyle(el).paddingBottom)-d+'px';el.style.marginBottom=d+'px';
}
/* a copy of what left, without its data, ids and typed words: it is gone, only its picture goes on */
function leave(box,w,e,by){
  const g=w.el.cloneNode(true);
  for(const x of [g,...g.querySelectorAll('*')])for(const a of [...x.attributes])if(/^(data-|id$|name$|for$)/.test(a.name))x.removeAttribute(a.name);
  g.classList.add('gone0');g.classList.remove('enter','changed');g.setAttribute('aria-hidden','true');g.inert=true;
  g.style.animation='none';
  Object.assign(g.style,{left:w.r.left-e.left-(box.clientLeft||0)+'px',top:w.r.top-e.top-(box.clientTop||0)+box.scrollTop+'px',width:w.r.width+'px',height:w.r.height+'px'});
  const fold=w.el.matches('.foldin'), cut=Math.max(0,w.r.bottom-e.bottom);
  const a=fold?moAnim(g,[{transform:'none',clipPath:`inset(0px 0px ${cut}px 0px)`,opacity:1},{transform:by?`translate(${-by[0]}px,${-by[1]}px)`:'none',clipPath:`inset(0px 0px ${w.r.height}px 0px)`,opacity:0}],{...FOLD_MO,fill:'forwards'})
    :moAnim(g,[{transform:'none',opacity:1},{transform:'scale(.96,.4)',opacity:0}],{ease:'--spring-soft',dur:'--dur-slow',fill:'forwards'});
  if(!a)return;
  (box._gone=box._gone||new Set()).add(g);a.onfinish=a.oncancel=()=>{g.remove();box._gone.delete(g)};
  box.appendChild(g);
}
/* a redraw took them out: they go on */
function leaving(box){if(box._gone)for(const g of box._gone)if(!g.isConnected)box.appendChild(g)}
/* F83: what came in since the last draw rises in, what changed state fades in. keysIn: the keys
   (and the words of your own messages, which move from sending to sent) on screen now */
function keysIn(box){const m=new Map();for(const el of box.querySelectorAll('[data-k]')){m.set(el.dataset.k,el.dataset.v||'');if(el.dataset.t)m.set('t:'+el.dataset.t,'')}return m}
function enter(box,had){
  if(!S.live||!had.size)return;  // the first load, and what it was waiting for, do not move
  const now=Date.now();
  for(const [k,t] of MO.born)if(now-t>=MO_MS)MO.born.delete(k);
  for(const el of box.querySelectorAll('[data-k]')){
    const k=el.dataset.k, fresh=!had.has(k)&&!(el.dataset.t&&had.has('t:'+el.dataset.t));
    if(fresh)MO.born.set(k,now);
    else if(had.has(k)&&el.dataset.v&&had.get(k)!==el.dataset.v){if(el.dataset.roll!==undefined&&had.get(k))roll(el,had.get(k));else el.classList.add('changed')}
    const rl=MO.rolls.get(k);if(rl&&rl.v===el.dataset.v&&now>rl.at&&now-rl.at<MO_MS&&had.get(k)===rl.v)roll(el,rl.was,rl.at);  // a redraw half way
    const age=MO.born.has(k)?now-MO.born.get(k):-1;
    if(age<0||!fresh&&!el.style)continue;
    const held=el.parentElement&&el.parentElement.closest&&el.parentElement.closest('.foldin');
    if(held&&folding()&&MO.born.has(held.dataset.k))continue;  // with its fold
    if(folding()&&el.matches&&el.matches('.foldin')){const a=moAnim(el,[{clipPath:'inset(0px 0px 100% 0px)',opacity:0},{clipPath:'inset(0px 0px 0% 0px)',opacity:1}],FOLD_MO);if(a)a.currentTime=age;continue}
    if(el.matches&&el.matches('.a')){[...el.querySelectorAll('.lead,.say>*,.speakb')].forEach((x,i)=>{x.classList.add('fresh');x.style.animationDelay=Math.min(i,10)*60-age+'ms'});continue}
    if(el.matches&&el.matches('.say'))continue;  // with its .a
    el.classList.add('enter');if(age)el.style.animationDelay=-age+'ms';
  }
}
/* a reply that grew: only its new words fade in */
function freshWords(box){
  const now=Date.now();
  for(const el of box.querySelectorAll('.say[data-k]')){
    const k=el.dataset.k, n=el.textContent.length, was=MO.said.get(k);MO.said.set(k,n);
    if(was&&n>was&&S.live&&!calm())MO.grown.set(k,{from:was,at:now});
    const g=MO.grown.get(k);if(!g)continue;
    if(now-g.at>=MO_MS){MO.grown.delete(k);continue}
    const walk=document.createTreeWalker(el,4), ts=[];let at=0;
    while(walk.nextNode())ts.push(walk.currentNode);
    for(const t of ts){const end=at+t.length;
      if(end>g.from&&t.data.trim()){const x=at<g.from?t.splitText(g.from-at):t, s=document.createElement('span');s.className='fresh';s.style.animationDelay=g.at-now+'ms';x.replaceWith(s);s.append(x)}
      at=end}
  }
}
/* a count or a state word rolls: up when it grew, down when it fell. Its data-v is its words */
function roll(el,was,at){
  if(!el.animate||calm())return;
  const d=parseFloat(el.dataset.v)<parseFloat(was)?-1:1, span=c=>{const s=document.createElement('span');s.className=c;return s};
  const now=span('rolls'), old=span('rolls out');old.setAttribute('aria-hidden','true');old.textContent=was;
  const t=at||Date.now();MO.rolls.set(el.dataset.k,{was,v:el.dataset.v,at:t});
  now.append(...el.childNodes);el.append(now,old);el.classList.add('roll');
  const b=moAnim(now,[{transform:`translateY(${d*100}%)`,opacity:0},{transform:'none',opacity:1}]);
  const a=moAnim(old,[{transform:'none',opacity:1},{transform:`translateY(${-d*100}%)`,opacity:0}],{fill:'forwards'});if(a){a.onfinish=()=>old.remove();if(at)a.currentTime=b.currentTime=Date.now()-at}
}
/* the loops (a dot, a wave) go on over a redraw, all in step */
function loopsInStep(box){if(box.getAnimations)for(const a of box.getAnimations({subtree:true}))if(a.effect.getComputedTiming().iterations===Infinity)a.startTime=0}
/* your words leave the message box: noted as they are sent, then their bubble springs from there to its place */
function sentMark(text){
  const b=document.querySelector('.box .inrow');if(!b||!b.getBoundingClientRect||calm())return;
  MO.sent={at:Date.now(),r:b.getBoundingClientRect(),text,t:'',began:0};
}
function sentFrom(box,had){
  const s=MO.sent, now=Date.now();if(!s)return;
  if(s.began?now-s.began>=MO_MS:now-s.at>4000){MO.sent=null;return}
  const u=[...box.querySelectorAll('.u[data-t]')].pop();if(!u)return;
  if(!s.began){if(had.has('t:'+u.dataset.t))return;s.began=now;s.t=u.dataset.t}
  else if(u.dataset.t!==s.t)return;
  u.classList.remove('enter');
  const r=u.getBoundingClientRect(), g=MO.scroll.get(box), up=g?box.scrollTop-g.from:0;  // F189a: the chat glides to its end under it: from where it was laid out at the start, on the same curve
  const a=moAnim(u,[{transform:`translate(${s.r.left-r.left}px,${s.r.top-r.top-up}px) scale(.94)`,opacity:.5},{transform:'none'}],g?{ease:'--spring-soft'}:{});
  if(a)a.currentTime=now-s.began;
}
/* to a real session: the bubble leaves the box and fades; the session draws the words itself */
function sendFly(){
  const s=MO.sent, main=document.querySelector('.main');MO.sent=null;if(!s||!s.text||!main||!main.animate)return;
  const m=main.getBoundingClientRect(), g=document.createElement('div');g.className='u flybub';g.setAttribute('aria-hidden','true');g.textContent=s.text.slice(0,400);
  Object.assign(g.style,{right:m.right-s.r.right+'px',bottom:m.bottom-s.r.bottom+'px'});
  main.appendChild(g);
  const a=moAnim(g,[{transform:'scale(.94)',opacity:0},{transform:'translateY(-40px)',opacity:1,offset:.35},{transform:'translateY(-110px) scale(.97)',opacity:0}],{ease:'--spring-soft'});
  if(a)a.onfinish=a.oncancel=()=>g.remove();else g.remove();
}
/* a chat opens or closes: a View Transition where the browser has them (it draws the new view a frame later), else
   go() at once and render() slides it in (viewSlide). n: the chat */
function viewGo(go,n){
  if(!document.startViewTransition||!S.live||kbH||S.sheet||calm()||!n||S.thread&&n!==S.thread){go();return}  // F206: from chat to chat at once
  const root=document.documentElement, into=n!==S.thread;
  root.classList.remove('vt-in','vt-out','vt-drawer');root.classList.add('vt',into?'vt-in':'vt-out');if(S.drawer)root.classList.add('vt-drawer');
  let done=false;const once=()=>{if(!done){done=true;go()}};
  const me={};MO.vt=me;
  const end=()=>{if(MO.vt!==me)return;MO.vt=null;root.classList.remove('vt','vt-in','vt-out','vt-drawer');render()};
  try{const t=document.startViewTransition(once);me.skip=()=>t.skipTransition();
    t.ready.catch(()=>{});t.updateCallbackDone.catch(()=>{});t.finished.then(end,end)}
  catch(e){once();end()}
}
/* the browser gives a press during a View Transition to the page's root: the press ends it, and its click goes to what is there */
document.addEventListener('pointerdown',()=>{if(MO.vt&&MO.vt.skip)MO.vt.skip()},true);
document.addEventListener('click',e=>{
  if(e.target!==document.documentElement||!e.isTrusted)return;
  const el=document.elementFromPoint(e.clientX,e.clientY);if(!el||el===document.documentElement)return;
  const f=el.closest('textarea,input,select');if(f)kbFocus(f);
  el.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,detail:e.detail,clientX:e.clientX,clientY:e.clientY}));
});
function viewSlide(to){
  if(MO.vt)return;
  const x=to==='in'?'40%':'-60px';
  for(const el of [$('feed').hidden?$('body'):$('feed'),$('dock')])moAnim(el,[{transform:`translateX(${x})`,opacity:0},{transform:'none',opacity:1}],{ease:'--spring-soft'});
}
function viewIn(el){el.classList.remove('viewin');void el.offsetWidth;el.classList.add('viewin')}
/* a field with data-f keeps its words (S.f), focus and caret over a redraw */
function keepFields(root){
  const a=document.activeElement, on=a&&root.contains(a)&&a.dataset&&a.dataset.f;let sel=null;
  if(on){try{sel=[a.selectionStart,a.selectionEnd]}catch(e){}}
  return()=>{for(const el of root.querySelectorAll('[data-f]'))if(el.dataset.f in S.f&&el.type!=='checkbox'&&el.value!==S.f[el.dataset.f])el.value=S.f[el.dataset.f];
    if(on){const el=[...root.querySelectorAll('[data-f]')].find(e=>e.dataset.f===on);if(el&&el!==document.activeElement){el.focus({preventScroll:true});try{if(sel&&sel[0]!=null)el.setSelectionRange(sel[0],sel[1])}catch(e){}}}};
}
/* a press under way, or a text selection in the view: a refresh waits for it (the next draw has it all) */
const PD={down:false,late:false,since:0,row:0}, HOLD_MS=15000;
const selecting=()=>{const g=window.getSelection&&window.getSelection();return !!(g&&!g.isCollapsed&&g.anchorNode&&$('body').contains(g.anchorNode))};
const emptyCard=t=>card(`<div class="small">${t}</div>`);

function toast(msg,bad){const t=$('toast');t.textContent=msg;t.className='toast'+(bad?' bad':'');t.hidden=false;
  clearTimeout(toast.h);toast.h=setTimeout(()=>t.hidden=true,bad?6000:3000)}
/* B164: an action outside the outbox failed; an older run also gets the restart control, in the Outbox popup */
function actFailed(j,other){toast(plainOut(j,other),true);if(oldRun(j)){S.oldRun=true;S.obOpen=true;obDraw()}}
async function act(name,args){
  try{const r=await fetch(tq('act'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,args:args||{}})});
    const j=await r.json();if(!j.ok)actFailed(j,`${name} did not work`);return j}
  catch(e){toast(`Could not reach the run page: ${plainErr(e)}`,true);return{ok:false}}
}

