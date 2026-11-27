/* --- F473: lazyrunner, the keyboard-first layout (concept K23), and the UI settings (theme, layout, key bar) ----------
   Hard rule: lazyrunner is only a CSS layout (189-lazy.css) and this key layer over the page's own sidebar and views.
   It draws no view or panel of its own: a key presses the button the page already has. tests/test_lazy.py checks it.
   On a phone (narrower than 760px) the page stays in the Standard layout and these keys do nothing. */
const UI_KEY='ui:look';
/* the panels: the key, what it opens (a sidebar view, 'sessions': the sidebar's chats and agents, or 'needs': Home's
   Needs you rows), its name. F484a (concept K24 option B): Needs you and Concepts are [6] and [7] */
const LAZY_PANELS=[['1','home','Home'],['2','sessions','Sessions'],['3','plan','Plans'],['4','tools','Tools'],['5','settings','Settings'],
  ['6','needs','Needs you'],['7','concepts','Concepts']];
/* F484a: the terminal UI's main run keys, from the run controls list (ui_model.RUN_CONTROLS' `tui`): each presses its
   control's button, as the Run card does; R the release row's "Release when the running tasks land" */
const LAZY_RUN_KEYS=['+','-','P','G','S'];
const LAZY_ROW_KEYS=[['J K','move the Plans row down or up'],['e','edit the row'],['n','add a task'],['g','the row\'s changes'],
  ['r','rename the chat'],['o','open the row'],['a','approve, or answer the Needs you row'],['R','release when the running tasks land']];
const LAZY_KEYS=[['1-7','go to a panel'],['j k','move, or scroll the main pane'],['Enter l','open in the main pane'],['h l','previous or next tab; h on the first goes back'],
  ['i','type in the box (insert mode)'],['Esc','back to normal mode'],['a d p','approve, drop or park the row'],['c','new chat'],['?','this list of keys']];
const UI_THEMES=[['','Standard (follows this device)'],['ryha','ryha'],['light','light'],['terminal','terminal'],['omarchy','omarchy']];
function uiLook(){
  const d={theme:'',layout:'standard',keybar:true};
  try{return Object.assign(d,JSON.parse(store.get(UI_KEY)||'{}'))}catch(e){return d}
}
function uiSet(k,v){const u=uiLook();u[k]=v;store.set(UI_KEY,JSON.stringify(u));uiApply();render(true)}
/* the look on the page's root: data-ui picks theme.py's colours (web.ui_themes_css), data-theme their light or dark */
function uiApply(){
  const r=document.documentElement, u=uiLook(), on=UI_THEMES.some(([n])=>n&&n===u.theme);
  if(on){r.dataset.ui=u.theme;r.dataset.theme=getComputedStyle(r).colorScheme==='light'?'light':'dark'}
  else{delete r.dataset.ui;delete r.dataset.theme}
  r.classList.toggle('lazy',u.layout==='lazy');r.classList.toggle('lazybar',u.layout==='lazy'&&!!u.keybar);
  keyBarDraw();
}
const lazyOn=()=>document.documentElement.classList.contains('lazy')&&$('app').clientWidth>=760;
const lazyInsert=()=>typingIn(document.activeElement);
function keyBarDraw(){
  const el=$('keybar'), shown=document.documentElement.classList.contains('lazybar');
  el.hidden=!shown;if(!shown)return;
  const h=lazyInsert()?'<b class="mode ins">INSERT</b> typing · <b>Esc</b> normal · <b>Enter</b> send'
    :'<b class="mode">NORMAL</b> <b>j/k</b> move · <b>J/K</b> reorder · <b>e</b> edit · <b>Enter/l</b> open · <b>i</b> type │ <b>1-7</b> panel · <b>+ -</b> slots · <b>c</b> new chat · <b>?</b> keys';
  if(el._h!==h){el._h=h;el.innerHTML=h}
}
SHEETS.ui=()=>{const u=uiLook();
  return `<h2>Look and layout</h2>
    <label class="it setrow"><span class="grow">Theme</span><select class="fld" data-uiset="theme">${UI_THEMES.map(([n,l])=>`<option value="${n}" ${u.theme===n?'selected':''}>${esc(l)}</option>`).join('')}</select></label>
    <label class="it setrow"><span class="grow">Layout<span class="small" style="display:block">Lazyrunner: the panels on the left, keys to move. A phone keeps Standard.</span></span><select class="fld" data-uiset="layout"><option value="standard" ${u.layout!=='lazy'?'selected':''}>Standard</option><option value="lazy" ${u.layout==='lazy'?'selected':''}>Lazyrunner</option></select></label>
    <label class="it setrow"><span class="grow">Show the key bar</span><input type="checkbox" role="switch" class="sw" data-uiset="keybar" ${u.keybar?'checked':''}></label>
    <div class="small">Kept in this browser.</div><div class="btns"><button class="btn" data-sheet="lazykeys">Keys…</button><button class="btn" data-closesheet>Done</button></div>`};
/* F484a: the keys sheet: the run keys come from the same run controls list as the terminal UI's */
const lazyRunKeys=()=>LAZY_RUN_KEYS.map(k=>controlsOf('run').find(c=>c.tui===k)).filter(Boolean).map(c=>[c.tui,c.label]);
SHEETS.lazykeys=()=>`<h2>Keys</h2>${LAZY_KEYS.concat(lazyRunKeys(),LAZY_ROW_KEYS).map(([k,w])=>`<div class="it setrow"><span class="grow">${esc(w)}</span><span class="k">${esc(k)}</span></div>`).join('')}<div class="btns"><button class="btn" data-closesheet>Done</button></div>`;
document.addEventListener('change',e=>{const t=e.target, k=t.dataset&&t.dataset.uiset;if(k)uiSet(k,t.type==='checkbox'?t.checked:t.value)});
/* what j and k move between: the panels' rows in the sidebar */
const lazyRows=()=>[...$('sidein').querySelectorAll('button[data-view],[data-thread],[data-new]')].filter(b=>b.offsetParent);
function lazyPanel(k){
  const p=LAZY_PANELS.find(x=>x[0]===k);if(!p)return;
  if(p[1]==='needs'){const h=$('sidein').querySelector('[data-view="home"]');if(h)h.click();  // Home holds the Needs you rows
    requestAnimationFrame(()=>{const n=$('body').querySelector('.card.need button,.card.need[tabindex]');if(n){n.focus();n.scrollIntoView({block:'nearest'})}});return}
  const b=p[1]==='sessions'?$('sidein').querySelector('[data-thread]')||$('sidein').querySelector('[data-new]'):$('sidein').querySelector(`[data-view="${p[1]}"]`);
  if(!b)return;b.focus();if(p[1]!=='sessions')b.click();
}
function lazyMove(d){
  const rs=lazyRows(), i=rs.indexOf(document.activeElement);
  if(i<0){$('body').scrollBy({top:d*80});return}
  const n=rs[Math.max(0,Math.min(rs.length-1,i+d))];if(n){n.focus();n.scrollIntoView({block:'nearest'})}
}
/* a tab: a pressed button among its group's in the main pane (Settings' tabs, a view's filters) */
function lazyTab(d){
  const g=document.querySelector('.main [role="group"]:has([aria-pressed="true"])'), bs=g?[...g.querySelectorAll('[aria-pressed]')]:[], i=bs.findIndex(b=>b.getAttribute('aria-pressed')==='true');
  const n=bs[i+d];if(n){n.click();return true}
  if(d<0){const back=$('top').querySelector('[data-home]');if(back){back.click();return true}}
  return false;
}
function lazyRowAct(word){
  const at=document.activeElement, row=at&&at.closest&&at.closest('.card,.crow,.it');if(!row)return;
  const b=[...row.querySelectorAll('button')].find(x=>x.textContent.trim().toLowerCase().startsWith(word));if(b)b.click();
  return !!b;
}
/* F484a: press the page's own button for `sel`, one in view; none drawn here: open panel `panel` (Home holds the Run
   card, Plans the Add a task button) and press it there */
function lazyPress(sel,panel){
  const on=()=>[...document.querySelectorAll(sel)].find(b=>b.offsetParent&&!b.disabled);
  let b=on();if(b){b.click();return}
  if(!panel)return;lazyPanel(panel);requestAnimationFrame(()=>{b=on();if(b)b.click()});
}
const lazyCtl=k=>lazyPress(`[data-ctl="${k}"]:not([data-tid]),[data-ctl="${k}"][data-tid=""]`,k.startsWith('release')?'3':'1');
function lazyRunKey(k){
  const c=controlsOf('run').find(x=>x.tui===k);
  if(!c||!((S.snap&&S.snap.shown)||[]).includes(c.key))return toast(`${k}: not now`,true);
  lazyCtl(c.key);
}
/* J/K: the focused Plans row's grip moves it, as its arrow keys do */
function lazyGrip(d){
  const at=document.activeElement, row=at&&at.closest&&at.closest('.card,.crow,.it'), g=at&&at.closest&&at.closest('[data-grip]')||row&&row.querySelector('[data-grip]');
  if(g)gripStep(g.dataset.grip,d);
}
/* r: rename the focused chat (the sidebar row) or the shown one */
function lazyRename(){
  const at=document.activeElement, t=at&&at.dataset&&at.dataset.thread||S.thread;
  if(t&&sessionOf(t))startRename(t);
}
function lazyAnswer(){
  if(lazyRowAct('approve'))return;
  const at=document.activeElement, row=at&&at.closest&&at.closest('.card.need');if(!row)return;
  const b=[...row.querySelectorAll('[data-ctl]')].find(x=>isAnswer(x.dataset.ctl))||row.querySelector('.tap,[tabindex]');if(b)b.click();
}
document.addEventListener('keydown',e=>{
  if(!lazyOn()||e.ctrlKey||e.metaKey||e.altKey||e.isComposing||lazyInsert())return;
  if(S.sheet&&e.key!=='?')return;  // a sheet has its own keys (Esc closes it)
  const k=e.key, inSide=$('side').contains(document.activeElement);
  const go={j:()=>lazyMove(1),k:()=>lazyMove(-1),i:()=>{const b=document.querySelector('[data-in]');if(b){b.focus();keyBarDraw()}},
    l:()=>{if(inSide)document.activeElement.click();else lazyTab(1)},h:()=>{if(!lazyTab(-1)){const r=lazyRows().find(b=>b.classList.contains('on'));if(r)r.focus()}},
    c:()=>{const b=document.querySelector('[data-new]');if(b)b.click()},'?':()=>S.sheet==='lazykeys'?closeSheet():openSheet('lazykeys'),
    a:lazyAnswer,d:()=>lazyRowAct('drop'),p:()=>lazyRowAct('park'),
    J:()=>lazyGrip(1),K:()=>lazyGrip(-1),e:()=>lazyRowAct('edit'),n:()=>lazyPress('[data-about="new"]','3'),
    g:()=>lazyRowAct('changes')||lazyRowAct('diff'),r:lazyRename,o:()=>{const a=document.activeElement;if(a&&a!==document.body)a.click()},
    R:()=>((S.snap&&S.snap.release_acts)||[]).includes('release_wait')?lazyCtl('release_wait'):toast('R: no release to start now',true)}[k]
    ||(/^[1-7]$/.test(k)?()=>lazyPanel(k):LAZY_RUN_KEYS.includes(k)?()=>lazyRunKey(k):null);
  if(!go)return;
  e.preventDefault();go();
});
for(const t of ['focusin','focusout'])document.addEventListener(t,()=>setTimeout(keyBarDraw));
uiApply();
