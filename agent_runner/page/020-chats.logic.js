function feedState(o){
  if(o.stand)return'starting';
  const i=o.info;
  if(i&&i.ok)return'session';
  if(i&&i.mode==='install')return'install';
  if(o.starting||o.born)return'starting';  // F196: born, a chat this page started, no reply yet: never Loading or ended
  if(!i)return'loading';
  return i.live?'none':o.chat?'ended':'idle';
}
/* the key row: a key's bytes, as the terminal sends them (app: application cursor keys) */
const FEED_KEYS=[['esc','Esc'],['tab','Tab'],['up','↑'],['enter','Enter'],['ctrlc','Ctrl-C'],['left','←'],['down','↓'],['right','→']];
function feedBytes(k,app){const c=app?'\x1bO':'\x1b[';
  return{esc:'\x1b',tab:'\t',enter:'\r',ctrlc:'\x03',up:c+'A',down:c+'B',right:c+'C',left:c+'D'}[k]||''}
/* what a terminal shows, as plain text: no trailing spaces, no empty lines at its end */
function feedWords(lines){return lines.map(l=>l.replace(/\s+$/,'')).join('\n').replace(/\n+$/,'')}
/* F170: the lines at the bottom of the agent's window, from the screen's lines (top to bottom, no trailing spaces); dim(y,x):
   is that cell dim (a hint, not typed)? lit(y,x): has it a ground of its own? null when the prompt is not there as the agent CLI draws it (a menu, a question, a new
   look): then nothing is hidden. {top, end: rows, the first hidden and the last of the box; text: unsent words in the
   prompt; bash; mode: FEED_MODES' key; shells, agents: how many; update: its command, '…' when cut off; status: the status
   line; rate: a 1: 2: 3: survey stands above it, answered by a digit; work: does it work; jump: is it scrolled up} */
const FEED_MODES=[['default','Ask first','manual mode|default mode'],['acceptEdits','Accept edits','accept edits'],['plan','Plan','plan mode'],['auto','Auto','auto mode'],['bypassPermissions','Bypass permissions','bypass permissions']];
const feedRule=l=>/^[─━]{6}/.test(l)&&(l.match(/[─━]/g)||[]).length>=l.length/2;
// cells of a line's words as the agent CLI counts them: 2 for a wide letter or an emoji, marks and joined parts with it
const feedSeg=new Intl.Segmenter(undefined,{granularity:'grapheme'});
const feedCells=l=>[...feedSeg.segment(l)].reduce((n,{segment:c})=>n+(/[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe6f\uff00-\uff60\uffe0-\uffe6]|\p{Emoji_Presentation}|\p{RI}|\ufe0f/u.test(c)?2:1),0);
// B194: the rule over the prompt with a session name on it: on a narrow window mostly the name, cut with no dashes before
// it when it is long (' agent-runner · F149 · pa… ─'); as wide as the rule under the prompt (cols), its > on the next line
const feedNamed=(l,next,cols)=>/^[─━]* \S.* [─━]+$/.test(l)&&Math.abs(feedCells(l)-cols)<=1&&/^[❯!>](\s|$)/.test(next||'');
// B192: the pill the agent CLI puts at the end of its last line while scrolled up, in each wording it has
const FEED_PILL=/ (?:Jump to bottom|\d+ new messages?|Waiting for your answer)(?: \([^)]*\))?(?: ↓| · \S+ to scroll)(?: |$)/g;
const FEED_JUMP=/(Jump to bottom|\d+ new messages?|Waiting for your answer)( \(.*\))?( ↓| · .* to scroll)\s*$/;
// B194: it is drawn over the middle of that line, whose words may go on after it: known by its place, the middle of cols,
// and its own ground (lit(x): has that cell one?), which words in an answer do not have
const feedJump=(l,cols,lit)=>FEED_JUMP.test(l)||[...l.matchAll(FEED_PILL)].some(m=>Math.abs(feedCells(l.slice(0,m.index))-(cols-feedCells(m[0].trim())-2)/2)<1&&(!lit||lit(feedCells(l.slice(0,m.index))+2)));
/* B863: the page's own Jump to bottom: the terminal is scrolled up from its newest output (scrolled) and its screen draws
   no jump pill of its own (Copilot's never does; an agent CLI's own pill stays its own) */
const feedOwnJump=(scrolled,foot)=>!!scrolled&&!(foot&&foot.jump);
function feedFoot(lines,dim,lit){
  let end=-1,at=-1;
  for(let y=lines.length-1;y>1&&end<0;y--){
    if(!feedRule(lines[y]))continue;
    const cols=feedCells(lines[y]), rule=t=>feedRule(lines[t])||t<y-1&&feedNamed(lines[t],lines[t+1],cols);
    let t=y-1;while(t>=0&&t>y-14&&!rule(t))t--;
    if(t>=0&&y-t>1&&rule(t)&&/^[❯!>](\s|$)/.test(lines[t+1])){end=y;at=t}else return null;
  }
  if(end<0)return null;
  const below=lines.slice(end+1);
  if(below.some(l=>/(Esc|Enter) to (cancel|close|confirm|exit|go back)/i.test(l)))return null;
  const bash=lines[at+1][0]==='!', cols=feedCells(lines[end]);
  const own=lines.slice(at+1,end).map((l,i)=>i?l:l.slice(1)).join('\n').trim();
  const hint=/^\s*$/.test(own)||!!(dim&&dim(at+1,lines[at+1].slice(1).search(/[^\s ]/)+1));
  let top=at;
  const note=lines[at-1]||'';
  if(/^\s+Update available/.test(note)||/^\s{12,}\S/.test(note)&&!/Jump to bottom/.test(note)&&!feedJump(note,cols,lit&&(x=>lit(at-1,x)))&&/ · |Update available|\/effort|ctrl\+/.test(note))top=at-1;
  const foot=(top<at?[note]:[]).concat(below), all=foot.join('\n'), num=re=>{const m=re.exec(all);return m?+m[1]:0};
  const m=/Update available(?: · run |! Run: | · Run: )(.+?)\s*$/m.exec(all);
  const mode=FEED_MODES.find(x=>new RegExp('[⏵⏸][^\\n]*\\b(?:'+x[2]+')','i').test(all)||new RegExp('^\\s*(?:'+x[2]+') on','im').test(all));
  const modeAt=below.findIndex(l=>/[⏵⏸]|\? for shortcuts|for shell mode/.test(l));
  const from=Math.max(0,top-5), near=lines.slice(from,top);
  return{top,end,bash,text:hint?'':own,mode:mode?mode[0]:'',shells:num(/(\d+) shells?\b/),tasks:num(/(\d+) background tasks?\b/),agents:num(/← (\d+) agents?\b/),
    update:m?m[1].replace(/^`|`$/g,''):/Update available/.test(all)?'…':'',status:below.slice(0,modeAt<0?below.length:modeAt).map(l=>l.trim()).filter(l=>l&&!/Update available/.test(l)),
    rate:lines.slice(Math.max(0,top-8),top).some(l=>/\b1: \S.*\s2: \S/.test(l)),work:/esc to interrupt/.test(all)||near.some(l=>/^\S \S+… ?(\(|$)/.test(l)),jump:near.some((l,i)=>feedJump(l,cols,lit&&(x=>lit(from+i,x))))};
}
/* where the session's frame goes. o: main its room, bar and dock what stands over it, row the slim message box's, high the
   frame's own height, pad its terminal's, cell a line, rows, foot (feedFoot's; null: show all), short (it is not full:
   its words, the working lines apart, end at this row, with nothing above to scroll to; 0 when it is full), whole, last (whole: the last row with words), off how far the reader has scrolled it down, top: the
   session has nothing older (its first line may go clear of the bar), hold: the shift to keep (scrolled up: what stands over it may change, its lines stay). t: its shift; off: that, past its rest;
   far: how far it can go; cut: how much of its bottom is hidden */
const FOOT_ROWS=6;  // rows past the edge for the lines at the bottom, so more or fewer of them never resize the session
function feedSpot(o){
  if(o.whole||!o.foot)return{t:o.main-o.dock-(o.whole&&o.last?Math.min(o.high,o.pad+o.last*o.cell):o.high),off:0,far:0,cut:0};
  const end=o.pad+o.foot.top*o.cell, words=o.short?o.pad+o.short*o.cell:end;
  const rest=o.short?Math.min(o.bar,o.main-o.dock-words):o.main-o.dock-words, low=Math.max(rest,o.top?o.bar:o.short?rest:Math.min(o.bar,o.main-o.row-end));
  const t=o.hold!=null?Math.min(o.hold,low):rest+Math.min(Math.max(o.off||0,0),low-rest);
  return{t,off:Math.max(0,t-rest),far:low-rest,cut:Math.max(0,o.high-end)};
}
/* B828: the height of a whole frame with this much room, over a question card this high (0: none): the card never makes it
   so low that the agent CLI draws its prompt cut off, as feedFoot would never find it again. It cuts its lines at the
   bottom, from under 8 rows or so; the rest is for a note or a longer prompt. What does not fit lies under the top bar */
const WHOLE_ROWS=12;
const feedWholeHigh=(room,pad,cell,card)=>Math.max(60,room,Math.min(room+card,Math.ceil(2*pad+WHOLE_ROWS*cell)));
/* B766: has the screen a gap over the agent CLI's working lines, right above its prompt (row top)? Then it is not full, and
   there is nothing older to scroll to. B786: the row the words over the gap end at (0: none);
   work: only a gap over the agent CLI's working line counts, or one no answer has */
function feedGap(lines,top,work){
  for(let y=top-1,blank=0,seen=0;y>=0;y--){
    if(lines[y].trim()){if(seen&&blank>3&&(!work||blank>7||lines.slice(y+1,top).some(l=>/^\S [^…]+… ?(\(|$)/.test(l))))return y+1;if(top-y>(work?24:8))return 0;seen=1;blank=0}else blank++;
  }
  return 0;
}
/* B192: a scroll of px (down is more): the part the frame takes, its lines going with the finger; the rest is the session's.
   Up only once the session itself is scrolled up (it stops following its new words) and the bars are away, to bring lines
   into the room they left, or once it has nothing older (top, B766), to bring its first lines from under the top bar;
   down all of it before the session, so at the session's end the frame is at rest again */
function feedShare(px,o){return px<0?o.top||o.jump&&o.slim?-Math.min(Math.max(0,o.far-o.off),-px):0:Math.min(o.off,px)}
/* B192: the bars after a scroll of px. o: slim (they are away), run (how far it went one way). Away 8px up, back 8px down */
function feedBars(px,o){const run=px*o.run<0?px:o.run+px;return{run,slim:run<=-8?true:run>=8?false:o.slim}}
/* which chips a session has: only what there is to say. o: foot, live (the run's /live), working, model (F406g: the
   provider's name and model of a chat on the harness loop, which has no modes, shells, agents or updates) */
function sessionChips(o){
  const f=o.foot||{}, l=o.live||{}, run=k=>(l.tasks||[]).filter(t=>t.kind===k&&t.running).length, out=[];
  if(o.working)out.push({key:'work',label:'Working'});
  if(o.model){out.push({key:'model',label:o.model});return out}
  const mode=FEED_MODES.find(m=>m[0]===(f.mode||l.mode));
  out.push({key:'mode',label:mode?mode[1].replace(' permissions',''):'Session'});
  const sh=run('shell')||f.shells||0, ag=run('agent')||f.agents||0;
  if(sh)out.push({key:'shells',label:`${sh} shell${sh===1?'':'s'}`});
  if(ag)out.push({key:'agents',label:`${ag} agent${ag===1?'':'s'}`});
  if(f.update)out.push({key:'update',label:'Update'});
  return out;
}
/* B190: a key pressed in the session's frame, or words pasted there (e.paste). 'box': it goes to the message box, as the
   prompt is hidden and typing in it would bring the agent CLI's input up; 'line': a new line in the prompt that shows (a
   terminal sends Shift+Enter as Enter, so it would send the words); '': the session's own (a menu, a question, Esc, Enter…) */
function feedHand(e,foot,whole){
  if(!foot||e.isComposing||e.keyCode===229)return'';
  const mod=e.metaKey||(e.ctrlKey||e.altKey)&&!(e.getModifierState&&e.getModifierState('AltGraph'));
  const line=e.key==='Enter'&&e.shiftKey&&!mod, shown=whole||!!foot.text||foot.bash;
  if(shown)return line?'line':'';
  if(foot.rate&&/^\d$/.test(e.key||''))return'';
  return line||e.paste||!mod&&!!e.key&&[...e.key].length===1?'box':'';
}
const forWords=s=>s<60?`${Math.max(0,Math.floor(s))}s`:s<3600?`${Math.floor(s/60)}m ${Math.floor(s%60)}s`:`${Math.floor(s/3600)}h ${Math.floor(s%3600/60)}m`;
/* the agent CLI's own list of background work, off its screen: [{y, name, on, running}], in order */
function taskLines(lines){
  const from=lines.map(l=>/^\s*Background\s*$/.test(l)).lastIndexOf(true);if(from<0)return[];
  return lines.slice(from+1).map((l,i)=>({l,y:from+1+i})).map(({l,y})=>{const m=/^\s+(❯\s)?\s*[●◯○◉✓✗✔✘]\s(.+?)\s{2,}(.*)$/.exec(l);return m?{y,name:m[2].replace(/…$/,''),on:!!m[1],running:/running/.test(m[3])}:null}).filter(Boolean);
}
/* whole wheel steps in a drag of px with cells of h, and what is left */
function feedSteps(px,h){const n=Math.trunc(px/h);return[n,px-n*h]}
/* is the session working: its last entry is a tool step, its output, or your words not yet answered */
function working(entries){
  const l=(entries||[])[(entries||[]).length-1];
  if(!l)return false;
  if(l.kind==='out'&&l.text==='interrupted')return false;
  return l.kind!=='say';
}
/* a queued task's state, in plain words */
function planWords(q,sessions){
  const s=(sessions||[]).find(x=>x.task===q.id);
  if(q.release)return q.release.words;  // F131, F185: its row's words, as status says them
  const on=/^running(?: (\S+))?(?: (\d+)m)?$/.exec(q.state||'');  // B824a: 'running s2 4m' (queue_state)
  if(on){const name=s?s.name:on[1], min=s?s.minutes:on[2];return name?`${name} is on it${min!=null?` · ${min} min`:''}`:'Being worked on'}
  if(q.state==='blocked')return 'Waits for you';
  if(q.under_way&&!q.waits_run)return q.way?q.way.words:'Being worked on';  // B846: merging, taken by hand, waiting to resume (an older run's snapshot has no way); with no run up that last one waits for the run
  if(q.state==='critical')return 'Goes first, as soon as a slot is free';
  if(q.state==='after')return q.after_title?`Waits for ${q.after_title}`:'Waits for another task';
  if(q.state==='tool'&&q.tool_wait)return q.tool_wait.charAt(0).toUpperCase()+q.tool_wait.slice(1);  // F168
  if(q.state==='split'&&q.split)return q.split.words;  // B811b
  if(q.state==='shelved')return 'Shelved until you bring it back';  // F184
  if(q.state==='held')return "Held: a run won't start it";  // F429
  if(q.state==='parked')return "Parked: a run won't start it";  // B118: never 'Ready'
  if(q.state==='done'||q.state==='dropped'||q.state==='open')return q.state.charAt(0).toUpperCase()+q.state.slice(1);  // F212: a search hit
  if(q.pri==='high')return 'High priority: goes ahead of normal tasks, as soon as a slot is free';  // F438
  return 'Ready to start when a slot is free';
}
/* F449: Settings' Ask about my settings: the first message, put in the box to edit (the settings kind sends the words as they are) */
const SETTINGS_ASK='What settings fit how I use this project?\n\nRead `agent-runner guide settings` and `agent-runner settings`, look at the project (its tests, size, recent run log, usage, this machine), and ask me about my use case what you cannot see. Then recommend each change in one line: `[table] key = value`, why, and who it is saved for (this machine or everyone). Make only the changes I say yes to.';
/* what the message box sends: the About line, your words, then the attachments' paths on this machine */
function compose(ctx,text,paths){
  text=String(text||'').trim();
  let msg=text;
  if(ctx&&ctx.kind==='new')msg=`Add a task: ${text}`;
  else if(ctx&&ctx.kind==='newconcept')msg=`Concept: ${text}`;  // F183: guide concepts: the options page in that chat
  else if(ctx&&ctx.kind==='plan')msg=`About ${ctx.id}${ctx.title?` (${ctx.title})`:''}: ${text}`;
  else if(ctx&&ctx.kind==='report')msg=`A problem with ${ctx.id}${ctx.title?` (${ctx.title})`:''}, which ${ctx.did||'has landed'}: ${text}\n\nFind out what is wrong, and add a bug task for it.`;  // F426c
  else if(ctx&&ctx.kind==='concept'&&ctx.lead)msg=ctx.lead+(text?`\n\n${text}`:'');  // B219a: what the chat is about (ui_model.concept_chat_text), then your words
  else if(ctx&&ctx.kind==='concept')msg=`About concept ${ctx.id}${ctx.title?` (${ctx.title})`:''}: ${text}`;
  else if(ctx&&ctx.kind==='setting')msg=`Change the setting ${ctx.id} (${ctx.title}) in the project file: ${text}`;
  else if(ctx&&ctx.kind==='need')msg=`About ${ctx.id}${ctx.title?` (${ctx.title})`:''}, which needs me: ${text}`;
  if(paths&&paths.length)msg+=(msg?'\n\n':'')+'Attached: '+paths.join(', ');
  return msg;
}
/* B139: where the message box sends msg: with a card's context (Add a task, a card's Chat) a new control
   session that gets it as its first message; F176: with no chat open (Home) too; else chat_to the open chat */
function sendReq(ctx,to,msg){if(ctx&&ctx.kind==='response')return{name:'response_chat',args:{rid:ctx.id,text:msg}};return ctx||!to?{name:'new_control',args:{ask:msg}}:{name:'chat_to',args:{text:msg,to}}}
/* B219b: a Needs you item that is a concept waiting for a pick: its place in concepts, else -1 (its Chat then opens the
   concept's new chat view, as the Concepts card's Chat does) */
function needConcept(tid,concepts){return tid?(concepts||[]).findIndex(c=>(c.concept||c.id)===tid):-1}
/* F172: the new chat view of a card's Chat, before its first message: its name in S.thread ('+plan:F1'; no session has it) */
const ctxKey=ctx=>'+'+(ctx.kind==='new'||ctx.kind==='newconcept'||ctx.kind==='settings'?ctx.kind:ctx.kind+':'+ctx.id);
/* its message box's placeholder */
const newPh=ctx=>({new:'Describe the task in your own words',newconcept:'What should the concept show?',report:'What is the problem?'})[ctx&&ctx.kind]||'Write your first message';
