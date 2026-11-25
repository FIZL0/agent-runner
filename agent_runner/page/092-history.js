/* --- F191b: a chat's or slot's history, scrolled by the browser -------------------------------------------------
   #feedpast lies over the session's frame, with the history's lines and, at its end, the screen's own (cloned rows), so at
   its end it is the session to the pixel. It scrolls natively. At rest it is see-through and the live session shows; a
   touch arms it (drawn, over the session), and a scroll away from its end is 'up'; back at the end it is see-through again.
   The session itself is sent no wheel step. Where it cannot stand in (pastMay), the session scrolls as it did.
   HX: n its chat, st ('', 'armed', 'up'), none (it has no transcript), pages (entries, oldest page first), before and since
   (the marks), hist (their lines), L (the lines drawn), at (the screen's first line in L), pad, cell, y0 (where the
   screen's first line stands in the session), high (the content's height), y (the scroll last seen), touch, news (there are new words) */
const HX={n:'',st:'',none:false,pages:[],before:'',since:'',cols:0,hist:[],L:[],at:0,pad:0,cell:17,y0:0,high:0,y:0,touch:false,news:false,busy:false,asked:0,late:[],lateT:0,warmT:0,newT:0,above:0,gap:false,chunks:new Map(),look:''};
const PAST_CHUNK=40, PAST_OVER=2000, PAST_IDLE=160, PAST_WARM=700, PAST_NEW=2500, PAST_BAND=56, PAST_AGAIN=5000;
const pastUp=()=>HX.st==='up';
/* may the history stand in for the session? Not over a menu or a question, nor one scrolled by someone else */
const pastMay=()=>FD.shown&&FD.up&&FD.drawn&&!FD.whole&&!!FD.foot&&!FD.foot.text&&!FD.foot.bash&&!FD.jump&&!(FD.off>0)&&HX.n===FD.n&&!HX.none;
function pastReset(){
  for(const t of [HX.lateT,HX.warmT,HX.newT])clearTimeout(t);
  const el=$('feedpast');if(el){scrollStop(el);$('pastrows').textContent=''}
  HX.chunks.clear();Object.assign(HX,{n:'',st:'',none:false,pages:[],before:'',since:'',cols:0,hist:[],L:[],at:0,high:0,y:0,touch:false,news:false,busy:false,asked:HX.asked+1,late:[],lateT:0,warmT:0,newT:0,above:0,gap:false});
  pastClass();
}
function pastClass(){
  const el=$('feedpast');if(!el)return;
  el.hidden=!HX.st&&!pastMay();
  el.classList.toggle('armed',!!HX.st);el.classList.toggle('up',pastUp());
  if(pastUp()){el.removeAttribute('aria-hidden');el.tabIndex=0}else{el.setAttribute('aria-hidden','true');el.removeAttribute('tabindex')}
  pastJumpDraw();
}
/* --- what it is made of --- */
async function pastGet(q){
  const n=HX.n, asked=HX.asked;let j=null;
  try{const r=await fetch(tq(`history/${encodeURIComponent(n)}${q}`));j=r.ok||r.status===404?await r.json():null}catch(e){if(e instanceof SyntaxError)j={ok:false}}
  return HX.n===n&&HX.asked===asked?j:undefined;
}
async function pastLoad(){
  if(!FD.n||!/^[cs]\d+$/.test(FD.n)||HX.tried===FD.n&&Date.now()-HX.triedAt<PAST_AGAIN)return;
  const none=HX.none&&HX.n===FD.n;
  pastReset();HX.n=HX.tried=FD.n;HX.triedAt=Date.now();HX.none=none;HX.busy=true;
  const j=await pastGet('');if(j===undefined)return;
  HX.busy=false;
  if(!j){HX.n='';pastClass();return}  // the run cannot be asked now: a later draw asks again
  HX.none=!j.ok;
  if(j.ok){HX.pages=[j.entries];HX.before=j.before;HX.since=j.since;pastRows();if(HX.st==='armed')pastReady();else pastWarm()}
  pastClass();
}
function pastRows(){HX.cols=(feedTerm()||{}).cols||HX.cols||80;HX.hist=HX.pages.flatMap(p=>pastLines(p,HX.cols))}
/* what was written since; once the screen has changed, and at rest */
async function pastNew(){
  if(HX.busy||HX.none||!HX.n)return;
  HX.busy=true;
  try{for(let i=0;i<9;i++){
    const j=await pastGet(HX.since?'?since='+encodeURIComponent(HX.since):'');if(!j||!j.ok)return;
    if(j.reset||!HX.since){HX.pages=[j.entries];HX.before=j.before}
    else if(j.entries.length){
      const last=j.entries.filter(e=>e.kind!=='result'), res=j.entries.filter(e=>e.kind==='result');
      if(res.length)HX.pages=HX.pages.map(p=>pastMerge(p,res));
      if(last.length)HX.pages=[...HX.pages.slice(0,-1),pastMerge(HX.pages[HX.pages.length-1]||[],last)];
    }
    HX.since=j.since;if(!j.more)break;
  }}finally{HX.busy=false}
  pastRows();
}
/* an older page: its lines go in over the others while nothing scrolls, so a fling goes on */
async function pastOlder(){
  if(HX.busy||!HX.before||HX.late.length)return;
  HX.busy=true;const j=await pastGet(`?before=${encodeURIComponent(HX.before)}&n=200`);if(j===undefined)return;
  HX.busy=false;if(!j||!j.ok||j.reset){if(j)HX.before='';return}
  HX.before=j.before;HX.pages=[j.entries,...HX.pages];
  const ls=pastLines(j.entries,HX.cols);HX.hist=[...ls,...HX.hist];
  if(HX.st){HX.late=ls;pastIdle()}else pastWarm();
}
const pastPicked=()=>{const g=getSelection();return !!(g&&!g.isCollapsed&&$('pastrows').contains(g.anchorNode))};
function pastIdle(){clearTimeout(HX.lateT);HX.lateT=setTimeout(pastPut,PAST_IDLE)}
function pastPut(){
  if(!HX.late.length||HX.touch||MO.scroll.has($('feedpast'))||pastPicked()){if(HX.late.length)pastIdle();return}
  const k=HX.late.length, el=$('feedpast');HX.L=[...HX.late,...HX.L];HX.at+=k;HX.late=[];
  const was=pastEnd();pastClear();pastSize(true);el.scrollTop+=pastEnd()-was;HX.y=el.scrollTop;pastDraw();
  if(el.scrollTop<el.clientHeight*3)pastOlder();
}
/* the screen's own lines, over its prompt, as the terminal draws them */
function pastScreen(){
  const f=feedScreen(), rows=f&&f.t.element.querySelector('.xterm-rows');if(!rows||!FD.foot)return null;
  const n=Math.min(FD.foot.top,FD.short||FD.foot.top,rows.children.length), out=[];
  for(let y=0;y<n;y++){const r=rows.children[y];out.push({t:r.textContent.replace(/ /g,' ').trimEnd(),h:r.innerHTML})}
  return out;
}
/* the lines drawn are these, from `at` on the screen's; patch: what was drawn stays, and only what changed is drawn */
function pastSet(lines,at,patch){
  const was=HX.L;HX.L=lines;HX.at=at;
  if(!patch){pastClear();return}
  const from=lines.findIndex((l,i)=>!was[i]||was[i].h!==l.h), end=Math.max(was.length,lines.length);if(from<0&&was.length===lines.length)return;
  for(const [c,box] of HX.chunks){
    if((c+1)*PAST_CHUNK<=(from<0?lines.length:from))continue;
    for(let i=c*PAST_CHUNK;i<Math.min(end,(c+1)*PAST_CHUNK);i++){
      const row=box.children[i-c*PAST_CHUNK], l=lines[i];
      if(!l){while(box.children.length>i-c*PAST_CHUNK)box.lastChild.remove();break}
      if(!row)box.appendChild(pastRow1(l));else if(row._h!==l.h){row._h=l.h;row.innerHTML=l.h}
    }
    if(!box.children.length){box.remove();HX.chunks.delete(c)}
  }
}
function pastRow1(l){const d=document.createElement('div');d._h=l.h;d.innerHTML=l.h;return d}
function pastClear(){HX.chunks.clear();$('pastrows').textContent=''}
/* only the lines near the view are in the page */
function pastDraw(){
  const el=$('feedpast'), high=PAST_CHUNK*HX.cell, top=el.scrollTop-HX.pad, last=Math.ceil(HX.L.length/PAST_CHUNK)-1;
  const a=Math.max(0,Math.floor((top-PAST_OVER)/high)), b=Math.min(last,Math.floor((top+el.clientHeight+PAST_OVER)/high)), keep=pastPicked();
  for(const [c,box] of HX.chunks)if((c<a||c>b)&&!keep){box.remove();HX.chunks.delete(c)}
  for(let c=a;c<=b;c++){
    if(HX.chunks.has(c))continue;
    const box=document.createElement('div');box.className='hchunk';box.style.top=c*high+'px';
    for(const l of HX.L.slice(c*PAST_CHUNK,(c+1)*PAST_CHUNK))box.appendChild(pastRow1(l));
    const next=[...HX.chunks].filter(([k])=>k>c).sort((x,y)=>x[0]-y[0])[0];  // in the order they are read and copied
    $('pastrows').insertBefore(box,next?next[1]:null);HX.chunks.set(c,box);
  }
}
/* the content's size: scrolled to its end, the screen's first line stands where the session has it */
function pastSize(again){
  const el=$('feedpast'), n=HX.at, room=el.clientHeight, f=feedScreen();
  if(f&&!FD.whole){  // as its rows are laid out: a browser keeps 64ths of a pixel
    const r=f.t.element.querySelector('.xterm-rows').children, a=r[0]&&r[0].getBoundingClientRect();
    if(a&&r[1])HX.cell=r[1].getBoundingClientRect().top-a.top;
    HX.y0=Math.round(FD.t)+(a||f.el.getBoundingClientRect()).top;
  }
  const over=HX.y0-n*HX.cell, bar=FD.bar||0;
  if(!pastUp()||again)HX.pad=over>bar?over:bar+(((over-bar)%1)+1)%1;  // up, it holds what is read where it is
  HX.high=room+Math.max(0,Math.round(HX.pad-over));
  const st=$('pastrows').style, set=(k,v)=>{if(st[k]!==v)st[k]=v};
  set('paddingTop','');set('height',HX.high+'px');
  $('pastrows').style.setProperty('--hpad',HX.pad+'px');$('pastrows').style.setProperty('--hcell',HX.cell+'px');
}
const pastEnd=()=>Math.max(0,HX.high-$('feedpast').clientHeight);
function pastToEnd(){const el=$('feedpast');el.scrollTop=pastEnd();HX.y=el.scrollTop}
/* the look is the terminal's own: its style sheets, and the colours it has now */
function pastLook(){
  const f=feedScreen();if(!f)return;
  const el=$('pastrows'), rows=f.t.element.querySelector('.xterm-rows'), css=[...f.el.querySelectorAll('style')].map(s=>s.textContent).join('\n'), key=[css.length,FD.info&&FD.info.look,feedLook(),rows.style.cssText,f.t.element.className].join('|');
  const sheet=$('pastcss');if(sheet._css!==css){sheet._css=css;sheet.textContent=css}
  if(!$('pastfont'))for(const s of f.win.document.styleSheets){let r=[];try{r=[...s.cssRules]}catch(e){}
    const t=r.filter(x=>x.type===5).map(x=>x.cssText).join('\n');if(t){const st=document.createElement('style');st.id='pastfont';st.textContent=t;document.head.appendChild(st);break}}
  if(HX.look===key)return;HX.look=key;
  const owner=(f.t.element.className.match(/xterm-dom-renderer-owner-\d+/)||[''])[0], c=f.win.getComputedStyle(rows);
  $('pastterm').className='xterm '+owner;el.className='xterm-rows';
  Object.assign(el.style,{fontFamily:c.fontFamily,fontSize:c.fontSize,fontKerning:c.fontKerning,color:c.color,letterSpacing:c.letterSpacing});
  const w=rows.children[0]&&f.el.getBoundingClientRect().width/f.t.cols;if(w)el.style.setProperty('--hw',w+'px');
  el.style.setProperty('--hleft',f.el.getBoundingClientRect().left+'px');el.style.width='';
  for(const [k,v] of Object.entries(pastColors(f.t.options.theme||{},feedSkinOf(FD.info).replace('page-','')||'dark')))el.style.setProperty('--'+k,v);
}
function pastColors(theme,look){
  const hex=s=>[1,3,5].map(i=>parseInt(s.slice(i,i+2),16)), ext=theme.extendedAnsi, light=look==='light', base=S.snap.session_look==='light';
  const at=(slot,own)=>hex(ext?ext[slot-16]:own[light?1:0]), bg=hex(theme.background||'#1f1e1d'), fg=hex(theme.foreground||'#e8e6dc');
  const mine=at(237,['#373737','#f0f0f0']), add=at(22,['#225c2b','#69db7c']), gone=at(52,['#7a2936','#ffa8b4']), plain=ext?at(base?236:231):fg;
  const c={hmuted:[at(247,['#999999','#666666'])],hcode:[base&&ext?at(61):at(153,['#b1b9f9','#5769f7'])],hlink:[hex(theme.brightBlue||'#5c8cff')],hbad:[at(167,['#ff6b80','#ab2b3f'])],hok:[at(108,['#4eba65','#2c7a39'])],hwarn:[at(179,['#ffc107','#966c1e'])],
    hmmuted:[at(247,['#999999','#666666']),mine],hmine:[ext?at(255):fg,mine],hadd:[plain,add],hgone:[plain,gone],haddn:[at(108,['#4eba65','#2c7a39']),add],hgonen:[at(167,['#ff6b80','#ab2b3f']),gone]}, out={};
  const css=x=>`rgb(${x.join(',')})`;
  for(const [k,[a,b]] of Object.entries(c))out[k]=css(pastInk(a,b||bg,4.5));
  return{...out,hminebg:css(mine),haddbg:css(add),hgonebg:css(gone)};
}
/* --- the swap --- */
/* made ready, see-through: the lines up to the screen and the screen's own, at its end */
function pastReady(){
  const s=pastScreen();if(!s)return false;
  if(HX.cols!==(feedTerm()||{}).cols&&HX.pages.length)pastRows();
  pastLook();
  const j=pastJoin(HX.hist,s), at=j<0?HX.hist.length:Math.min(j,HX.hist.length);
  HX.late=[];HX.gap=false;
  pastSet([...HX.hist.slice(0,at),...s],at,HX.L.length>0&&HX.cols===HX.drawnCols);HX.drawnCols=HX.cols;
  pastSize();pastToEnd();pastDraw();HX.above=FD.above;return true;
}
/* a little after the screen changed, so a touch finds nothing to do */
function pastWarm(){if(!HX.warmT)HX.warmT=setTimeout(()=>{HX.warmT=0;if(!HX.st&&!$('feedpast').hidden&&pastMay())pastReady()},PAST_WARM)}
/* drawn over the session, in the state it is in */
function pastArm(touch){
  HX.touch=!!touch;
  if(HX.st)return true;
  if(!pastMay()||HX.n!==FD.n)return false;
  const el=$('feedpast'), off=HX.high?pastEnd()-el.scrollTop:0;  // a scroll that came first
  if(!pastReady())return false;
  if(off>1){el.scrollTop=Math.max(0,pastEnd()-off);pastDraw()}
  HX.st='armed';HX.news=false;FD.run=0;pastClass();
  if(HX.before&&HX.hist.length<400)pastOlder();
  return true;
}
/* the live session again, in this very frame */
function pastLive(){
  if(!HX.st)return;
  if(HX.touch&&pastMay())HX.st='armed';else HX.st='';
  HX.news=false;FD.run=0;feedSlim(false);pastClass();
  if(!HX.st){if(pastMay())pastWarm();pastNewSoon()}
}
function pastScrolled(){
  const el=$('feedpast'), y=el.scrollTop, px=y-HX.y;if(el.hidden)return;
  if(!HX.st){if(y>=pastEnd()-1){HX.y=y;return}if(!pastArm(HX.touch)){pastToEnd();return}}
  HX.y=y;pastDraw();if(HX.late.length)pastIdle();
  if(y>=pastEnd()-1){if(pastUp())pastLive();return}
  if(!pastUp()){HX.st='up';pastClass()}
  if(px){const b=feedBars(px,FD);FD.run=b.run;if(b.slim!==FD.slim)feedSlim(b.slim)}
  pastJumpDraw();
  if(y<el.clientHeight*3)pastOlder();
}
/* each draw of the session: while the history is drawn its end is the screen as it is now; what stands on screen stays */
function pastSee(){
  if(HX.n!==FD.n||HX.none){pastLoad();if(HX.n!==FD.n||HX.none)return}  // a new chat's transcript comes a little later
  if(!HX.st){pastClass();if(!$('feedpast').hidden){pastWarm();pastNewSoon()}return}
  if(FD.whole||!FD.foot){if(pastUp()&&!HX.news){HX.news=true;pastJumpDraw()}return}
  if(FD.foot.text||FD.foot.bash||FD.jump||HX.gap)return;
  if((feedTerm()||{}).cols!==HX.cols){pastWidth();return}
  const s=pastScreen();if(!s)return;
  const was=HX.L.slice(HX.at), j=s.length===was.length&&s.every((l,i)=>l.h===was[i].h)?HX.at:pastJoin(HX.L,s,s.length*2+200);
  if(j===HX.at&&s.length===was.length&&s.every((l,i)=>l.h===was[i].h))return;
  if(j<0){pastGap();return}
  pastTail(HX.L.slice(0,j),s);
}
function pastTail(before,s){
  const last=l=>{const i=l.findLastIndex(x=>x.t.trim());return i<0?'':pastKey(l[i].t)}, had=last(HX.L), end=!pastUp();
  pastSet([...before,...s],before.length,true);pastSize();
  if(end)pastToEnd();else{if(last(HX.L)!==had)HX.news=true}
  pastDraw();pastJumpDraw();
}
/* another width (a rotation): its lines are broken anew, what was at the top stays there as near as can be */
function pastWidth(){
  const el=$('feedpast'), up=pastUp(), i=Math.max(0,Math.floor((el.scrollTop+(FD.slim?0:FD.bar||0)-HX.pad)/HX.cell)), y=HX.pad+i*HX.cell-el.scrollTop, had=HX.L;
  const k=had.findIndex((l,n)=>n>=i&&l.t.trim().length>6), word=k<0?'':had[k].t.trim().slice(0,16), far=had.length?i/had.length:1;
  if(!pastReady()||!up)return;
  let best=-1;HX.L.forEach((l,n)=>{if(word&&l.t.trim().startsWith(word)&&(best<0||Math.abs(n-far*HX.L.length)<Math.abs(best-far*HX.L.length)))best=n});
  pastSize(true);el.scrollTop=HX.pad+(best<0?Math.round(far*HX.L.length):best-(k-i))*HX.cell-y;HX.y=el.scrollTop;pastDraw();pastJumpDraw();
}
/* more was written than one screen holds between two draws: the transcript has it */
async function pastGap(){
  HX.gap=true;const n=HX.n;
  for(let i=0;HX.busy&&i<50;i++)await new Promise(r=>setTimeout(r,100));  // an older page is on its way
  await pastNew();if(HX.n!==n||!HX.gap)return;
  HX.gap=false;const s=pastScreen();if(!HX.st||!s||FD.whole)return;
  const last=HX.L.slice(-60), k=pastJoin(HX.hist,last,600), add=k<0?[]:HX.hist.slice(k+last.length), all=[...HX.L,...add], j=pastJoin(all,s,s.length*2+200);
  pastTail(j<0||j<HX.at?all:all.slice(0,j),s);
}
function pastNewSoon(){if(!HX.newT)HX.newT=setTimeout(async()=>{HX.newT=0;if(HX.st||document.hidden||HX.n!==FD.n)return;await pastNew();if(!HX.st)pastWarm()},PAST_NEW)}
/* each time the frame is placed: the keyboard moves the text with the box, anything else moves nothing */
function pastPlace(){
  const el=$('feedpast');if(!el||!FD.shown)return;
  pastClass();if(el.hidden||!HX.L.length&&!HX.st)return;
  const d=FD.above-HX.above;HX.above=FD.above;
  if(!HX.st){pastSize();pastToEnd()}
  else if(!FD.whole){pastSize();if(!pastUp())pastToEnd();else if(d){el.scrollTop-=d;HX.y=el.scrollTop}}
  pastJumpDraw();
}
/* and its lines glide with the frame (feedGlide) */
function pastGlide(d){if(HX.st)moAnim($('pastterm'),[{translate:`0 ${d}px`},{translate:'0 0'}],{ease:'--ease',dur:'--dur-slow'})}
/* the button back to the live session: it floats over the lines just above the box */
function pastJumpDraw(){
  const j=$('pastjump');if(!j)return;
  const on=pastUp()&&pastEnd()-$('feedpast').scrollTop>PAST_BAND, dock=document.querySelector('.dockwrap'), say=HX.news?'Jump to bottom: there is something new':'Jump to bottom';
  if(on&&dock){const row=slimRow();j.style.bottom=row+'px';j.style.setProperty('--up',Math.max(0,dock.offsetHeight-row)+'px')}
  j.classList.toggle('on',on);j.classList.toggle('fresh',HX.news);j.inert=!on;
  const b=j.firstElementChild;if(b.getAttribute('aria-label')!==say){b.setAttribute('aria-label',say);b.title=say}
}
/* a fling under way ends */
function pastStop(){const el=$('feedpast');if(!el||!HX.st)return;scrollStop(el);el.style.overflowY='hidden';void el.offsetHeight;el.style.overflowY=''}
/* to the live session: it glides when a press asked for it */
function pastDown(press){
  if(!HX.st)return;
  const el=$('feedpast');pastStop();
  if(press&&!calm())scrollGlide(el,pastEnd);else{pastToEnd();HX.touch=false;pastLive()}
}
/* a wheel step over the session (a mouse): the first one up opens the history, then the browser scrolls it */
function pastWheel(px){
  const el=$('feedpast');
  if(HX.st){el.scrollTop+=px;pastScrolled();return true}
  if(!pastMay()||HX.n!==FD.n)return false;
  if(px<0&&pastArm()){el.scrollTop+=px;if(el.scrollTop>=pastEnd()-1){HX.st='';pastClass()}else pastScrolled()}
  return true;
}
/* the keys that scroll, pressed in the session: the history's, so the session itself never scrolls */
function pastPress(e){
  const page=$('feedpast').clientHeight*.85, by={PageUp:-page,PageDown:page,Home:-1e9,End:1e9}[e.key];
  if(!by||e.shiftKey||e.altKey||e.metaKey||/Home|End/.test(e.key)&&!e.ctrlKey||!HX.st&&!pastMay())return false;
  return pastWheel(by);
}
/* a touch: at rest a tap clicks in the session and a long press gives its text, as on #feedtouch */
{const el=$('feedpast');let T1=null;
const at=t=>{const r=el.getBoundingClientRect();return[t.clientX-r.left,t.clientY-r.top]};
const drop=()=>{if(T1)clearTimeout(T1.hold);T1=null};
el.addEventListener('touchstart',e=>{
  drop();HX.touch=true;
  if(e.target!==el)for(const n of ['touchend','touchcancel'])e.target.addEventListener(n,end,{passive:false,once:true});  // a row drawn again under the finger
  if(pastUp()||e.touches.length!==1){pastArm(true);return}
  if(!pastArm(true))return;
  const t=e.touches[0], [x,y]=at(t), g=T1={x,y,x0:t.clientX,y0:t.clientY};
  g.hold=setTimeout(()=>{if(T1===g&&!pastUp()&&!(SW&&SW.on)){T1=null;feedText()}},550)},{passive:true});
el.addEventListener('touchmove',e=>{const t=e.touches[0];if(T1&&(pastUp()||SW&&SW.on||e.touches.length!==1||Math.abs(t.clientX-T1.x0)>8||Math.abs(t.clientY-T1.y0)>8))drop()},{passive:true});
const end=e=>{
  const g=T1;drop();if(e.touches.length)return;
  HX.touch=false;
  if(HX.st==='armed'){if($('feedpast').scrollTop>=pastEnd()-1){HX.st='';pastClass();pastWarm()}}
  if(g&&!pastUp()&&e.type==='touchend'){if(e.cancelable)e.preventDefault();feedClick(g.x,g.y)}
  if(HX.late.length)pastIdle();
};
el.addEventListener('touchend',end,{passive:false});el.addEventListener('touchcancel',end,{passive:true});
el.addEventListener('click',e=>{if(!HX.st&&e.detail&&e.pointerType==='mouse')feedClick(...at(e))});
el.addEventListener('wheel',e=>{if(!HX.st&&e.deltaY<0)pastArm()},{passive:true});
el.addEventListener('scroll',()=>{pastScrolled();if(pastUp())drop()},{passive:true});
/* a browser gives no click for a tap that ends a fling: the touch's end makes it, as on the slim message box (B218b1) */
const jump=$('pastjump').firstElementChild;let J=null;
jump.addEventListener('click',()=>pastDown(true));
jump.addEventListener('touchstart',e=>{const t=e.touches[0];pastStop();J=e.touches.length===1?{x:t.clientX,y:t.clientY}:null},{passive:true});
jump.addEventListener('touchend',e=>{const j=J, t=e.changedTouches[0];J=null;if(!j||!e.cancelable||Math.abs(t.clientX-j.x)>9||Math.abs(t.clientY-j.y)>9)return;e.preventDefault();pastDown(true)},{passive:false});
jump.addEventListener('touchcancel',()=>{J=null},{passive:true})}
