/* --- F191b: the session history as lines of text, as the agent CLI's terminal draws it ------------------------------
   A line is {t: its text, h: its markup}. A span is [text, class]; the classes are .hist's (page/092-history.css). */
const PAST_BLANK={t:'',h:''};
const pastEsc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'})[c]);
const pastPlain=/^[\x20-\x7e]*$/;
/* how many cells a text takes: 2 for a wide letter */
const pastWide=s=>pastPlain.test(s)?s.length:feedCells(s);
/* a letter the font may lack has a box of its own cells, so the ones after it stand in their columns */
const pastOwn=/^[\x20-\x7e\u2500-\u257f]*$/;  // and the box lines, which the session's own font has
const pastCellsHTML=s=>pastOwn.test(s)?pastEsc(s):[...feedSeg.segment(s)].map(({segment:c})=>pastOwn.test(c)?pastEsc(c):`<b style="--w:${feedCells(c)}">${pastEsc(c)}</b>`).join('');
function pastLine(spans){
  const l=spans.filter(s=>s[0]);
  return{t:l.map(s=>s[0]).join('').trimEnd(),h:l.map(([t,c])=>c?`<span class="${c}">${pastCellsHTML(t)}</span>`:pastCellsHTML(t)).join('')};
}
/* spans broken at spaces into lines of w cells, a word longer than a line broken as it comes */
function pastWrap(spans,w){
  w=Math.max(8,w);
  const rows=[];
  for(const part of pastParts(spans)){
    let row=[],at=0;
    const put=(t,c)=>{if(!t)return;const l=row[row.length-1];if(l&&l[1]===c)l[0]+=t;else row.push([t,c])}, next=()=>{rows.push(row);row=[];at=0};
    for(const word of pastWords(part)){
      const n=word.reduce((k,s)=>k+pastWide(s[0]),0), space=word[0][0]===' ';
      if(space){if(at<w){put(' ',word[0][1]);at++}else at++;continue}
      if(n>w){
        const rest=w-at;
        if(at&&(rest<=0||Math.floor((n-1)/w)<1+Math.floor((n-rest-1)/w)))next();
        for(const [t,c] of word)for(const g of pastPlain.test(t)?t:[...feedSeg.segment(t)].map(x=>x.segment)){const k=pastWide(g);if(at+k>w)next();put(g,c);at+=k}
        continue;
      }
      if(at&&at+n>w)next();
      for(const [t,c] of word)put(t,c);at+=n;
    }
    rows.push(row);
  }
  return rows;
}
function pastParts(spans){
  const out=[[]];
  for(const [t,c] of spans)String(t).replace(/\t/g,'    ').split('\n').forEach((x,i)=>{if(i)out.push([]);if(x)out[out.length-1].push([x,c])});
  return out;
}
/* words (runs of spans with no space in them) and single spaces */
function pastWords(spans){
  const out=[];let word=null;
  for(const [t,c] of spans)for(const x of t.split(/( )/)){if(!x)continue;
    if(x===' '){word=null;out.push([[' ',c]])}else{if(!word)out.push(word=[]);word.push([x,c])}}
  return out;
}
/* spans as lines: the first starts with lead, the others with hang (spans or a text) */
function pastFlow(spans,cols,lead,hang){
  const as=x=>typeof x==='string'?[[x,'']]:x, l=as(lead), g=as(hang), w=cols-l.reduce((n,s)=>n+pastWide(s[0]),0);
  return pastWrap(spans,w).map((r,i)=>pastLine([...(i?g:l),...r]));
}
/* markdown within a line */
function pastInline(s,cls){
  const out=[], re=/(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)|\*\*(\S(?:[\s\S]*?\S)?)\*\*|__(\S(?:[\s\S]*?\S)?)__|\*(\S(?:[^*]*?\S)?)\*(?!\*)|(?<![\w])_(\S(?:[^_]*?\S)?)_(?![\w])|~~(\S(?:[\s\S]*?\S)?)~~|!?\[([^\]]+)\]\((\S+?)\)/g;
  let at=0,m;const c0=cls||'', add=c=>[c0,c].filter(Boolean).join(' ');
  while((m=re.exec(s))){
    if(m.index>at)out.push([s.slice(at,m.index),c0]);at=re.lastIndex;
    if(m[2]!=null)out.push([m[2],add('hc')]);
    else if(m[3]||m[4])out.push(...pastInline(m[3]||m[4],add('hb')));
    else if(m[5]||m[6])out.push(...pastInline(m[5]||m[6],add('hi')));
    else if(m[7])out.push(...pastInline(m[7],add('hx')));
    else out.push([m[8],add('hl')]);
  }
  if(at<s.length)out.push([s.slice(at),c0]);
  return out;
}
/* a table's lines, as wide as its words, or narrowed to the room */
function pastTable(rows,w){
  const n=rows[0].length, cell=rows.map(r=>Array.from({length:n},(x,i)=>pastInline(r[i]||''))), len=s=>s.reduce((k,x)=>k+pastWide(x[0]),0);
  let size=rows[0].map((x,i)=>Math.max(3,...cell.map(r=>len(r[i]))));
  const room=w-3*n-1, all=size.reduce((a,b)=>a+b,0);
  if(all>room){
    const least=size.map((x,i)=>Math.min(x,Math.max(3,...cell.map(r=>Math.max(0,...r[i].flatMap(s=>s[0].split(' ').map(pastWide))))))), low=least.reduce((a,b)=>a+b,0);
    size=low<=room&&all>low?size.map((x,i)=>least[i]+Math.floor((x-least[i])*(room-low)/(all-low))):size.map(x=>Math.max(3,Math.floor(x*room/all)));
  }
  const bar=(a,b,c)=>pastLine([[a+size.map(x=>'─'.repeat(x+2)).join(b)+c,'']]), out=[bar('┌','┬','┐')];
  cell.forEach((r,y)=>{
    if(y)out.push(bar('├','┼','┤'));
    const ls=r.map((s,i)=>pastWrap(s,size[i])), high=Math.max(...ls.map(l=>l.length));
    for(let k=0;k<high;k++)out.push(pastLine([['│',''],...ls.flatMap((l,i)=>{const s=l[k]||[], gap=Math.max(0,size[i]-len(s)), left=y?0:Math.floor(gap/2);return[[' '.repeat(left+1),''],...s,[' '.repeat(gap-left+1)+'│','']]})]));
  });
  return[...out,bar('└','┴','┘')];
}
const pastRow=l=>l.trim().replace(/^\||\|$/g,'').split(/(?<!\\)\|/).map(x=>x.trim().replace(/\\\|/g,'|'));
/* markdown as lines of w cells, with no lead of their own */
function pastMd(text,w){
  const src=String(text).replace(/\r/g,'').split('\n'), out=[];
  const gap=()=>{if(out.length&&out[out.length-1].t)out.push(PAST_BLANK)};
  let lists=[];
  for(let i=0;i<src.length;i++){
    const l=src[i];let m;
    if(!l.trim()){gap();let k=i+1;while(k<src.length&&!src[k].trim())k++;if(!/^\s*([-*+]|\d+[.)])\s/.test(src[k]||'')&&!/^\s{2,}\S/.test(src[k]||''))lists=[];continue}
    if(m=/^\s*(```+|~~~+)/.exec(l)){
      gap();lists=[];const code=[];for(i++;i<src.length&&!src[i].trim().startsWith(m[1]);i++)code.push(src[i]);
      for(const c of code)out.push(...(c.trim()?pastWrap([[c,'']],w).map(pastLine):[PAST_BLANK]));gap();continue}
    if(m=/^(#{1,6})\s+(.*)$/.exec(l)){gap();lists=[];out.push(...pastWrap(pastInline(m[2].replace(/\s#+\s*$/,''),m[1].length===1?'hb hi hu':'hb'),w).map(pastLine),PAST_BLANK);continue}
    if(/^\s*\|?.*\|/.test(l)&&/^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(src[i+1]||'')&&(src[i+1]||'').includes('|')){
      gap();lists=[];const rows=[pastRow(l)];for(i+=2;i<src.length&&src[i].includes('|')&&src[i].trim();i++)rows.push(pastRow(src[i]));i--;
      out.push(...pastTable(rows,w-2));gap();continue}
    if(m=/^\s*>\s?(.*)$/.exec(l)){const q=[m[1]];while(i+1<src.length&&/^\s*>/.test(src[i+1]))q.push(src[++i].replace(/^\s*>\s?/,''));gap();lists=[];
      out.push(...pastFlow(pastInline(q.join('\n'),'hi'),w,[['▎','hd'],[' ','']],[['▎','hd'],[' ','']]));gap();continue}
    if(m=/^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(l)){
      const at=m[1].length, num=/\d/.test(m[2]);
      while(lists.length&&lists[lists.length-1].at>at)lists.pop();
      let cur=lists[lists.length-1];
      if(!cur||at>cur.at+1){const up=cur?cur.pad+(cur.lead||2):0;cur={at,pad:up,n:num?parseInt(m[2],10)-1:0,lead:2};lists.push(cur)}
      const mark=num?`${++cur.n}. `:'- ';cur.lead=mark.length;
      out.push(...pastFlow(pastInline(m[3]),w,' '.repeat(cur.pad)+mark,' '.repeat(cur.pad+mark.length)));continue}
    if(lists.length&&/^\s+\S/.test(l)){const c=lists[lists.length-1], p=' '.repeat(c.pad+c.lead);out.push(...pastFlow(pastInline(l.trim()),w,p,p));continue}
    lists=[];
    const para=[l.trimEnd()];
    while(i+1<src.length&&src[i+1].trim()&&!/^\s*(```|~~~|#{1,6}\s|>|[-*+]\s|\d+[.)]\s|\|)/.test(src[i+1])&&!/^\s*\|?\s*:?-+:?\s*\|/.test(src[i+2]||''))para.push(src[++i].trimEnd());
    out.push(...pastWrap(pastInline(para.join('\n')),w).map(pastLine));
  }
  while(out.length&&!out[out.length-1].t)out.pop();
  return out;
}
/* calls one line stands for: what a call counts as */
function pastFold(e){
  if(e.kind!=='tool'||(e.diff&&e.diff.length))return'';
  if(e.group==='read'||e.group==='search')return e.group;
  const m=/^(.+) - .+ \(MCP\)$/.exec(e.name);if(m)return'mcp:'+m[1];
  if(e.name!=='Bash')return'';
  const c=(/^\s*(\S+)/.exec(e.arg||'')||[])[1]||'';
  return /[;&|<>\n]/.test(e.arg||'')?'run':/^(ls|tree|du)$/.test(c)?'list':/^(cat|head|tail|less|wc|stat|file|jq|awk|cut)$/.test(c)?'read':/^(grep|rg|find|ag|which)$/.test(c)?'search':'run';
}
function pastFoldLine(group,cols){
  const n=k=>group.filter(x=>x[1]===k).length, many=(k,one,more)=>[[`${k}`,'hm hb'],[` ${k===1?one:more}`,'hm']], out=[];
  const add=(word,spans)=>{out.push([out.length?', '+word.toLowerCase():word,'hm'],...spans)};
  if(n('search'))add('Searched for ',many(n('search'),'pattern','patterns'));
  if(n('read'))add('Read ',many(n('read'),'file','files'));
  if(n('list'))add('Listed ',many(n('list'),'directory','directories'));
  for(const k of new Set(group.map(x=>x[1]).filter(x=>x.startsWith('mcp:'))))add('Called ',[[k.slice(4),'hm'],...(n(k)>1?[[` ${n(k)} times`,'hm']]:[])]);
  if(n('run'))add('Ran ',many(n('run'),'shell command','shell commands'));
  const bad=group.filter(x=>x[0].state==='error').length;
  if(bad)out.push([' · ','hm'],[`${bad} failed`,'hr']);
  return pastFlow(out,cols,'  ','  ');
}
/* what stands under a call or a message */
const pastUnder=(spans,cols,out)=>out.push(...pastFlow(spans,cols-5,[['  ⎿  ','hm']],'     '));
const pastNums=s=>s.split(/(\d+)/).map((x,i)=>[x,i%2?'hb':'']);
function pastDiff(d,cols,out){
  const w=Math.max(8,cols-12);
  d.hunks.forEach((h,i)=>{
    if(i)out.push(pastLine([['     ...','hm']]));
    let a=h.old||0,b=h.new||0;
    const old=h.lines.filter(l=>l[0]!=='+').length, now=h.lines.filter(l=>l[0]!=='-').length, digits=String(Math.max(a+old,b+now)-1).length;
    for(const l of h.lines){
      if(l[0]==='\\')continue;
      const k=l[0]==='-'||l[0]==='+'?l[0]:' ', no=k==='-'?a++:k==='+'?b++:(a++,b++), room=Math.max(4,w-digits-3), text=l.slice(1).replace(/\t/g,'    ');
      const parts=pastHard(text,room);
      parts.forEach((t,j)=>{
        const num=` ${j?' '.repeat(digits):String(no||'').padStart(digits)} `, pad=' '.repeat(Math.max(0,room-pastWide(t)));
        out.push(pastLine(k===' '?[['     ',''],[num,'hd'],[' '+t,'']]:[['     ',''],[num+k,k==='+'?'hpn hp':'hgn hg'],[t+pad,k==='+'?'hp':'hg']]));
      });
    }
  });
  if(d.cut)out.push(pastLine([[`     … +${d.cut} line${d.cut===1?'':'s'}`,'hm']]));
}
function pastHard(t,w){
  if(!t)return[''];
  const out=[];let cur='',n=0;
  for(const g of pastPlain.test(t)?t:[...feedSeg.segment(t)].map(x=>x.segment)){const k=pastWide(g);if(n+k>w){out.push(cur);cur='';n=0}cur+=g;n+=k}
  return[...out,cur];
}
function pastTool(e,cols){
  const out=[], mark=e.state==='error'?'hr':e.state==='ok'?'hk':'hm', bash=e.name==='Bash';
  let arg=String(e.arg||'');if(bash){arg=arg.split('\n').slice(0,2).join('\n');if(arg.length>160)arg=arg.slice(0,159)+'…';else if(arg!==e.arg)arg+='…'}
  out.push(...pastFlow([[e.name,'hb'],[arg?`(${arg})`:'','']],cols,[['● ',mark]],bash?'      ':'  '));
  let sum=e.summary||'';
  if(e.name==='Write'&&/^Wrote \d+ lines? to /.test(sum))sum=sum.replace(/ to .*/,' to '+(e.arg||''));
  if(sum==='Done')sum='';
  const red=e.state==='error'?'hr':'', text=(e.text||'').split('\n').slice(0,e.show||0), more=(e.lines||0)-(e.show||0);
  if(sum)pastUnder(sum==='Backgrounded agent'?[[sum+' (↓ to manage · ctrl+o to expand)','']]:pastNums(sum),cols,out);
  if(e.show&&e.name==='Write'){
    const digits=Math.max(2,String(Math.min(e.lines,e.show)).length);
    text.forEach((t,i)=>pastHard(t,Math.max(8,cols-12-digits-2)).forEach((x,j)=>out.push(pastLine([['     ',''],[` ${j?' '.repeat(digits):String(i+1).padStart(digits)} `,'hd'],[x,'']]))));
  }else if(e.show){if(sum)for(const t of text)out.push(...pastFlow([[t,red]],cols,'     ','     '));else pastUnder([[text.join('\n'),red]],cols,out)}
  if(e.show&&more>0)out.push(pastLine([[`     … +${more} line${more===1?'':'s'}`,'hm']]));
  for(const d of e.diff||[]){if(bash)pastUnder([['Updated ',''],[d.file,'hb'],[` +${d.added} -${d.removed}`,'']],cols,out);pastDiff(d,cols,out)}
  return out;
}
const pastClock=at=>{const d=new Date(at*1000), h=d.getHours();return `${h%12||12}:${String(d.getMinutes()).padStart(2,'0')} ${h<12?'AM':'PM'}`};
const pastDecode=s=>String(s||'').replace(/&(lt|gt|quot|amp);/g,(m,k)=>({lt:'<',gt:'>',quot:'"',amp:'&'})[k]);
/* a note's lines, and whether it stands right under what is before it */
function pastNote(e,cols){
  const t=pastDecode(e.text), say=(mark,cls,text)=>pastFlow([[text,cls]],cols,[[mark,cls]],'  ');
  if(e.what==='turn')return[false,say('✻ ','hm',`Worked for ${forWords(e.ms/1000)}${e.at?` · done ${pastClock(e.at)}`:''}`)];
  if(e.what==='compacted')return[false,say('✻ ','hm',t+' (ctrl+o for history)')];
  if(e.what==='recap')return[false,say('※ ','hm',`recap: ${t}`)];
  if(e.what==='event')return[false,pastFlow([[t,'']],cols,[['● ','hk']],'  ')];
  if(e.what==='hook'){const m=/^(\S+) hook error: ([\s\S]*)$/.exec(t), out=[];out.push(...pastFlow([[`Ran 1 ${(m?m[1]:'stop').toLowerCase()} hook`,'']],cols,[['● ','']],'  '));
    pastUnder([[`${m?m[1]:'Stop'} hook reported a problem`,'hw']],cols,out);out.push(...pastFlow([[m?m[2]:t,'hm']],cols,'     ','     '));return[false,out]}
  if(e.what==='interrupted')return[true,[pastLine([['  ⎿  Interrupted','hm']])]];
  const out=[];pastUnder([[t,e.what==='error'?'hr':'']],cols,out);
  return[true,out];
}
function pastYou(e,cols){
  const words=(e.text||'')+(e.images&&!/\[Image/.test(e.text||'')?' [Image]'.repeat(e.images):'')+(e.cut?`… +${e.cut} characters`:'');
  return pastWrap([[words,'']],cols-2).map((r,i)=>{const used=2+r.reduce((n,s)=>n+pastWide(s[0]),0), l=pastLine([[i?'  ':'❯ ',i?'':'hm'],...r,[' '.repeat(Math.max(0,cols-used)),'']]);return{t:l.t,h:`<span class="hy">${l.h}</span>`}});
}
/* F489: a fold line ('Ran 3 shell commands') opens to the calls it stands for, as Claude Code's ctrl+o does: its key
   is its first call's id; open holds the keys of the open ones. A tap on it opens or folds it: whether it was one */
const pastFoldKey=e=>String(e.call||e.id||'');
function pastFoldTap(open,el){
  const f=el&&el.closest&&el.closest('[data-fold]');if(!f||!open)return false;
  const k=f.getAttribute('data-fold');if(open.has(k))open.delete(k);else open.add(k);
  return true;
}
/* a page's entries as lines of cols cells; a blank line stands before each block */
function pastLines(entries,cols,open){
  const out=[];
  for(let i=0;i<entries.length;i++){
    const e=entries[i];let part=[],under=false;
    if(e.kind==='you')part=pastYou(e,cols);
    else if(e.kind==='say')part=pastMd(e.text,cols-2).map((l,j)=>({t:j?l.t&&'  '+l.t:'● '+l.t,h:(j?l.t?'  ':'':'● ')&&(j?'  ':pastCellsHTML('● '))+l.h}));
    else if(e.kind==='tool'&&pastFold(e)){const g=[];for(;i<entries.length&&pastFold(entries[i]);i++)g.push([entries[i],pastFold(entries[i])]);i--;
      const k=pastFoldKey(g[0][0]), at=`<span class="hfold" data-fold="${pastEsc(k).replace(/"/g,'&quot;')}">`;
      part=pastFoldLine(g,cols).map(l=>({t:l.t,h:at+l.h+'</span>'}));
      if(open&&open.has(k))for(const [x] of g)part.push(...pastTool(x,cols))}
    else if(e.kind==='tool')part=pastTool(e,cols);
    else if(e.kind==='note')[under,part]=pastNote(e,cols);
    if(!part.length)continue;
    if(!under)out.push(PAST_BLANK);
    out.push(...part);
  }
  return out;
}
/* entries newer than `old` put in: a result goes in its call's entry */
function pastMerge(old,more){
  const out=[...old], at=new Map();out.forEach((e,i)=>{if(e.kind==='tool'&&e.call)at.set(e.call,i)});
  for(const e of more){
    const i=e.kind==='result'?at.get(e.call):undefined;
    if(e.kind==='result'){if(i!=null){const {kind,id,call,...f}=e;out[i]={...out[i],...f}}continue}
    if(e.kind==='tool'&&e.call)at.set(e.call,out.length);
    out.push(e);
  }
  return out;
}
/* where a screen's lines (texts) stand in lines: the index of the screen's first one, the lines from there on are the
   screen's; -1 when none of them is there. Each line that is the same word for word speaks for one place; a line that is
   there once speaks loudest, and of two as likely the later one is it. Only the last `back` lines are looked at */
const pastKey=t=>String(t).replace(/ /g,' ').replace(/\s+$/,'').replace(/^[●⏺✻❯]\s/,'  ').replace(/^  \S+ (for (?:\d+[hms] ?)+· done)/,'  $1');
function pastJoin(lines,screen,back){
  const from=Math.max(0,lines.length-(back||4000)), where=new Map();
  for(let i=from;i<lines.length;i++){const k=pastKey(lines[i].t);if(k.trim().length<3)continue;const a=where.get(k);if(a)a.push(i);else where.set(k,[i])}
  const votes=new Map();
  screen.forEach((s,y)=>{const a=where.get(pastKey(s.t));if(a)for(const i of a.slice(-40))votes.set(i-y,(votes.get(i-y)||0)+1/a.length)});
  let best=null,at=-1;for(const [d,v] of votes)if(best==null||v>best+1e-9||v>best-1e-9&&d>at){best=v;at=d}
  if(best==null)return-1;
  return Math.max(0,at);
}
/* the colour xterm.js draws fg with on bg ([r,g,b] each), at a contrast of at least `least` (its own way, 10% a step) */
function pastInk(fg,bg,least){
  const lum=c=>{const [r,g,b]=c.map(v=>{v/=255;return v<=.03928?v/12.92:((v+.055)/1.055)**2.4});return r*.2126+g*.7152+b*.0722};
  const ratio=(a,b)=>{const x=lum(a),y=lum(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
  if(ratio(fg,bg)>=least)return fg;
  const go=step=>{let c=fg;while(ratio(c,bg)<least){const n=c.map(step);if(n.every((v,i)=>v===c[i]))break;c=n}return c};
  const down=()=>go(v=>v-Math.max(0,Math.ceil(v*.1))), up=()=>go(v=>Math.min(255,v+Math.ceil((255-v)*.1)));
  const [one,two]=lum(fg)<lum(bg)?[down,up]:[up,down], a=one();if(ratio(a,bg)>=least)return a;
  const b=two();return ratio(a,bg)>ratio(b,bg)?a:b;
}
