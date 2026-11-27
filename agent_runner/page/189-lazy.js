/* --- F473: lazyrunner, the keyboard-first layout (concept K23), and the UI settings (theme, layout, key bar) ----------
   Hard rule: lazyrunner is only a CSS layout (189-lazy.css) and this key layer over the page's own sidebar and views.
   It draws no view or panel of its own: a key presses the button the page already has. tests/test_lazy.py checks it.
   On a phone (narrower than 760px) the page stays in the Standard layout and these keys do nothing. */
const UI_KEY='ui:look';
/* the five panels: the key, what it opens (a sidebar view, or 'sessions': the sidebar's chats and agents), its name */
const LAZY_PANELS=[['1','status','Status'],['2','sessions','Sessions'],['3','plan','Plans'],['4','tools','Tools'],['5','settings','Settings']];
const LAZY_KEYS=[['1-5','go to a panel'],['j k','move, or scroll the main pane'],['Enter l','open in the main pane'],['h l','previous or next tab; h on the first goes back'],
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
    :'<b class="mode">NORMAL</b> <b>j/k</b> move · <b>Enter/l</b> open · <b>h/l</b> tabs · <b>i</b> type │ <b>1-5</b> panel · <b>c</b> new chat · <b>?</b> keys';
  if(el._h!==h){el._h=h;el.innerHTML=h}
}
SHEETS.ui=()=>{const u=uiLook();
  return `<h2>Look and layout</h2>
    <label class="it setrow"><span class="grow">Theme</span><select class="fld" data-uiset="theme">${UI_THEMES.map(([n,l])=>`<option value="${n}" ${u.theme===n?'selected':''}>${esc(l)}</option>`).join('')}</select></label>
    <label class="it setrow"><span class="grow">Layout<span class="small" style="display:block">Lazyrunner: the panels on the left, keys to move. A phone keeps Standard.</span></span><select class="fld" data-uiset="layout"><option value="standard" ${u.layout!=='lazy'?'selected':''}>Standard</option><option value="lazy" ${u.layout==='lazy'?'selected':''}>Lazyrunner</option></select></label>
    <label class="it setrow"><span class="grow">Show the key bar</span><input type="checkbox" role="switch" class="sw" data-uiset="keybar" ${u.keybar?'checked':''}></label>
    <div class="small">Kept in this browser.</div><div class="btns"><button class="btn" data-sheet="lazykeys">Keys…</button><button class="btn" data-closesheet>Done</button></div>`};
SHEETS.lazykeys=()=>`<h2>Keys</h2>${LAZY_KEYS.map(([k,w])=>`<div class="it setrow"><span class="grow">${esc(w)}</span><span class="k">${esc(k)}</span></div>`).join('')}<div class="btns"><button class="btn" data-closesheet>Done</button></div>`;
document.addEventListener('change',e=>{const t=e.target, k=t.dataset&&t.dataset.uiset;if(k)uiSet(k,t.type==='checkbox'?t.checked:t.value)});
/* what j and k move between: the panels' rows in the sidebar */
const lazyRows=()=>[...$('sidein').querySelectorAll('button[data-view],[data-thread],[data-new]')].filter(b=>b.offsetParent);
function lazyPanel(k){
  const p=LAZY_PANELS.find(x=>x[0]===k);if(!p)return;
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
}
document.addEventListener('keydown',e=>{
  if(!lazyOn()||e.ctrlKey||e.metaKey||e.altKey||e.isComposing||lazyInsert())return;
  if(S.sheet&&e.key!=='?')return;  // a sheet has its own keys (Esc closes it)
  const k=e.key, inSide=$('side').contains(document.activeElement);
  const go={j:()=>lazyMove(1),k:()=>lazyMove(-1),i:()=>{const b=document.querySelector('[data-in]');if(b){b.focus();keyBarDraw()}},
    l:()=>{if(inSide)document.activeElement.click();else lazyTab(1)},h:()=>{if(!lazyTab(-1)){const r=lazyRows().find(b=>b.classList.contains('on'));if(r)r.focus()}},
    c:()=>{const b=document.querySelector('[data-new]');if(b)b.click()},'?':()=>S.sheet==='lazykeys'?closeSheet():openSheet('lazykeys'),
    a:()=>lazyRowAct('approve'),d:()=>lazyRowAct('drop'),p:()=>lazyRowAct('park')}[k]||(/^[1-5]$/.test(k)?()=>lazyPanel(k):null);
  if(!go)return;
  e.preventDefault();go();
});
for(const t of ['focusin','focusout'])document.addEventListener(t,()=>setTimeout(keyBarDraw));
uiApply();
