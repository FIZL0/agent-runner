function settingValue(k,text){
  const t=String(text==null?'':text).trim(), also=k.also||[];
  if(k.type==='choice'||k.type==='switch'||typeof k.default==='boolean'||k.off){if(t==='true'&&k.type!=='text'||t==='true'&&typeof k.default==='boolean')return{v:true};if(t==='false')return{v:false}}
  if(k.type==='choice')return{v:t};
  if(k.type==='number'||(also.includes('number')&&/^\d/.test(t)))return /^-?\d+(\.\d+)?$/.test(t)?{v:Number(t)}:{err:`${k.key} takes a number`};
  const list=()=>t.split(/\n/).map(x=>x.trim()).filter(Boolean);
  if(k.type==='list')return{v:list()};
  if(k.type==='table'||/^\{/.test(t)){
    if(!t)return{v:{}};
    try{const v=JSON.parse(t.replace(/([{,]\s*)"?([\w-]+)"?\s*=\s*/g,'$1"$2": '));if(v&&typeof v==='object'&&!Array.isArray(v))return{v}}catch(e){}
    return{err:`${k.key} takes a table, like { every = 10 }`}}
  if(also.includes('list')&&(/\n|,/.test(t)||typeof k.default==='boolean'))return{v:t.split(/[\n,]/).map(x=>x.trim()).filter(Boolean)};
  return{v:String(text==null?'':text)};
}
/* F166: a control's option ('true', '{"every":10}', 'opus'; `settingText` writes it) back as a value */
function pickValue(k,t){
  if(k.choices&&k.choices.length){const c=k.choices.find(x=>String(x)===t);return c===undefined?t:c}
  if(t==='true'||t==='false')return t==='true';
  if(k.type==='number'&&/^-?\d+(\.\d+)?$/.test(t))return Number(t);
  if(/^\{/.test(t)){try{return JSON.parse(t)}catch(e){}}
  if((k.also||[]).includes('list')&&/[\n,]/.test(t))return t.split(/[\n,]/).map(x=>x.trim()).filter(Boolean);
  return t;
}
/* its options as [value, words], the one it has now among them; null when it is typed */
function pickOptions(k,now){
  if(isBranch(k)){const o=k.picks.map(p=>[p.value,branchWords(p)]);if(now!=null&&!o.some(x=>x[0]===now))o.push([now,now===''?'Found by itself':String(now)]);return o}
  const w=k.words||{}, o=(k.choices&&k.choices.length?k.choices.map(c=>[String(c),w[String(c)]||String(c)]):Object.keys(w).map(x=>[x,w[x]]));
  if(!o.length)return null;
  if(now!==''&&now!=null&&!o.some(x=>x[0]===now))o.push([now,settingSays(k,now)]);
  return o;
}
/* F174: a setting set by two controls, a count and a switch ([run] auto_release): what its words `t` hold, as
   autorelease.auto_release_of reads them; the count's options; and its words once one control changed. F422: where the
   parts have `on` ([run] auto_audit, as audit.every_of reads it) the switch turns the count itself on and off; `true` is `on`'s count */
const hasParts=k=>!!(k.parts&&k.parts.every);
function partsNow(t,k){
  let v=null;try{v=JSON.parse(t)}catch(e){}
  if(v===true&&k&&k.parts.on)v={every:k.parts.on.every};
  v=v||{};
  return{every:Number.isInteger(v.every)&&v.every>0?v.every:0,idle:v.idle===true};
}
const partCount=(k,n)=>`${n} ${n===1?k.parts.every.unit.replace(/s$/,''):k.parts.every.unit}`;
function partOptions(k,t){
  const n=partsNow(t,k).every, c=k.parts.every.counts;
  return [...(k.parts.on?[]:[[0,'Off']]),...(n&&!c.includes(n)?[...c,n].sort((a,b)=>a-b):c).map(x=>[x,partCount(k,x)])];
}
function partSet(t,part,x,k){
  const v={...partsNow(t,k),...(part==='on'?{every:x?k.parts.on.every:0}:{[part]:x})}, o={};
  if(v.every)o.every=v.every;
  if(v.idle)o.idle=true;
  return settingText(v.every||v.idle?o:false);
}
/* F405: [run] agent is picked from the programs found on this machine (`picks`, agents_here.py): its options as [value, words], the kept
   one among them, then Other path; and what the one picked is */
/* F447a: [git] master_branch, the working branch, is picked from the branches the snapshot gives (`picks`,
   working_branch.py): a plain pick of the row, not the agent's picker */
const isBranch=k=>!!k&&k.table==='git'&&k.key==='master_branch'&&Array.isArray(k.picks);
const branchWords=p=>`${p.auto?`Found by itself (${p.branch})`:p.branch}${p.bad?` (${p.bad})`:''}`;
/* what Save of `v` does, said before Save: {text, bad}; no text when `v` is the branch it has */
function branchSays(k,v,saved){
  if(v===saved)return{text:'',bad:false};
  const p=k.picks.find(x=>x.value===v), b=p?p.branch:v;
  if(p&&p.bad)return{text:`It cannot be saved: ${p.bad}.`,bad:true};
  return{text:`Save: finished work is applied to ${b}, and tasks start from it, once the run restarts.`,bad:false};
}
const AGENT_OTHER='other path', hasPicks=k=>Array.isArray(k.picks)&&!isBranch(k);
const agentSaved=(k,v)=>['value','device','project'].some(x=>k[x]!==undefined&&settingText(k[x])===v);
const agentWords=p=>`${p.value}${p.version?` ${p.version}`:''}${p.found?p.path&&p.path!==p.value?` · ${p.path}`:'':' (not found)'}`;
const agentPick=(k,v)=>k.picks.find(p=>p.value===v)||{value:v,path:'',version:'',found:!agentSaved(k,v),bad:agentSaved(k,v)?'It is not the name of a program.':''};
function agentOptions(k,now){
  const o=k.picks.map(p=>[p.value,agentWords(p)]);
  if(!o.some(x=>x[0]===now))o.push([now,agentWords(agentPick(k,now))]);
  return [...o,[AGENT_OTHER,'Other path…']];
}
const agentSays=p=>p.bad?p.bad:p.path?`At ${p.path}${p.version?`, version ${p.version}`:''}`:'';
const LOGIN_SAYS={in:'Logged in',out:'Not logged in',none:'No login needed'};  // claude's own is not checked here, and `says` so
/* F406c: the providers other than claude that setting `key` of [models] names in value `v`, of those in `names`; F443: a bare
   model name is `base`'s, the [models] provider */
function modelProviders(key,v,names,base){
  if(key==='providers'||key==='local'||key==='tiers')return [];
  if(key==='provider')return typeof v==='string'&&v!=='claude'&&names.includes(v)?[v]:[];
  const ms=typeof v==='string'?[v]:v&&typeof v==='object'?Object.values(v):[];
  return [...new Set(ms.filter(m=>typeof m==='string'&&(m.includes(':')||base)).map(m=>m.includes(':')?m.slice(0,m.indexOf(':')).trim():base))].filter(p=>p!=='claude'&&names.includes(p));
}
/* a provider's login: its row in the settings with what /logins (`logins`, none where it is refused) says of it now */
function loginNow(p,logins){
  const l=(logins||[]).find(x=>x.name===p.name), state=!l||p.state==='unchecked'||p.state==='none'?p.state:l.ok?'in':'out';
  return{...p,state,says:state==='in'&&l?l.where:p.says,terminal:l?l.terminal:'',run:l&&l.login&&l.login.state||'',said:l&&l.login&&l.login.said||''};
}
const loginsNow=(d,logins)=>(d&&d.providers||[]).map(p=>loginNow(p,logins));
/* what a setting's model does while its provider has no login */
const loginLater=key=>key==='fallback'?'It is passed over until the login.':key==='code'||key==='kinds'||key==='provider'?'Its tasks wait for the login.':'What runs on it needs the login.';
/* what the last Save left waiting for a login, in words; '' for nothing (`undo`: what it replaced; `base`: the [models] provider) */
function loginWaits(undo,rows,base){
  const names=rows.map(p=>p.name), out=rows.filter(p=>p.state==='out').map(p=>p.name);
  const by=keys=>[...new Set(undo.filter(x=>x.table==='models'&&keys(x.key)&&x.now&&x.now.has).flatMap(x=>modelProviders(x.key,x.now.value,names,base)))].filter(p=>out.includes(p));
  const tasks=by(k=>k==='code'||k==='kinds'||k==='provider'), rest=by(()=>true).filter(p=>!tasks.includes(p));
  return [tasks.length?`Tasks on ${tasks.join(', ')} wait for the login`:'',rest.length?`${rest.join(', ')} ${rest.length===1?'has':'have'} no login yet`:''].filter(Boolean).join('. ');
}
/* what a login's terminal shows: the link to open (the last one) and the code to enter there */
function loginAsks(text){
  const u=String(text).match(/https?:\/\/[^\s]+/g)||[], c=/enter the code ([A-Za-z0-9-]+)/.exec(String(text));
  return{url:u.length?u[u.length-1]:'',code:c?c[1]:''};
}
/* a value as a person reads it */
function settingSays(k,t){
  if(k.words&&k.words[t])return k.words[t];
  if(hasParts(k)){const v=partsNow(t,k), p=k.parts, e=v.every?`${p.every.label} ${partCount(k,v.every)}`:'';
    return e&&v.idle?`${e} and ${p.idle.label.toLowerCase()}`:e||(v.idle?p.idle.label:'Off')}
  if(k.type==='switch')return t==='true'?'On':'Off';
  if(t==='')return 'not set';
  if(t==='false')return 'Off';
  return k.unit==='$'&&/^\d/.test(t)?`$${t}`:k.unit&&/^\d/.test(t)?`${t}${k.unit==='%'?'':' '}${k.unit}`:t.split('\n').join(', ');
}
/* where a row's control saves: this device when it has its own value (it wins), else the setting's home */
const settingSide=k=>k.has_device||k.home==='device'?'device':'project';
const settingChanged=k=>k.source!=='default'&&JSON.stringify(k.value)!==JSON.stringify(k.default);
const settingHit=(k,q)=>!q||`${k.name} ${k.desc} ${k.table}.${k.key} [${k.table}] ${k.key}`.toLowerCase().includes(q);
/* shown only while its parent is on */
function settingShows(k,all){
  if(!k.parent)return true;
  const p=all.find(x=>`${x.table}.${x.key}`===k.parent);if(!p)return true;
  const v=p.value;
  return !(v===false||v===''||v==null);
}
/* F204b: a trip away from Settings: since when the person is away (0 while it is in view), and whether they came back too
   late for its search to stay */
const SEARCH_STAYS=5*60000;
const settingsAway=(since,inView,now)=>inView?{since:0,late:!!since&&now-since>=SEARCH_STAYS}:{since:since||now,late:false};
/* the rows that set several kinds' models at once */
const KINDS_ROWS=[{id:'build',name:'Features, fixes, tests',desc:'Also concepts and releases. A stronger model does them better and uses more of your limit.',kinds:['F','B','T','V','K']},
  {id:'light',name:'Docs, cleanup, research',desc:'Lighter work; a cheaper model does it and saves your limit.',kinds:['D','C','R']}];
/* F193: with Manage releases off ([run] releases in the settings answer; on when the run does not say), nothing about
   releases is listed, searched or counted: not Release by itself, and not the word in the kinds row */
const releasesSet=all=>!all.some(k=>k.table==='run'&&k.key==='releases'&&k.value===false);
const settingsListed=all=>releasesSet(all)?all:all.filter(k=>k.parent!=='run.releases');
const kindsRows=all=>releasesSet(all)?KINDS_ROWS:KINDS_ROWS.map(g=>({...g,desc:g.desc.replace('Also concepts and releases.','Also concepts.')}));
const kindsModel=(kinds,v)=>{const m=[...new Set(kinds.map(x=>(v||{})[x]||''))];return m.length===1?m[0]:''};
/* the live Talk session: the remembered one, else a chat titled Talk that is not in `old`, the Talk chats New Talk
   chat left (F157). remembered 'new': a new one was asked for and nothing was sent yet, so none */
function talkSession(sessions,remembered,old){
  if(remembered==='new')return '';
  const live=(sessions||[]).filter(s=>/^c\d+$/.test(s.name)&&s.state==='live');
  const r=live.find(s=>s.name===remembered);if(r)return r.name;
  const t=live.find(s=>s.title==='Talk'&&!(old||[]).includes(s.name));return t?t.name:'';
}
