/* F202b: the changes on the Settings page that are not saved yet (the draft): {field: {id, side, text} or {id, side, unset}}, by
   `setField`; `set`: asked for by name in More…, so it counts even where the value in force is that already; `err`: why the last
   Save did not take it. And `undo`: what the last Save replaced, as `settings_save` answers it */
const setField=(id,side)=>`set:${side}:${id}`;
function draftParse(text){
  let j=null;try{j=JSON.parse(text||'null')}catch(e){}
  const o=j&&typeof j==='object'?j:{}, draft={};
  for(const d of Object.values(o.draft&&typeof o.draft==='object'?o.draft:{}))
    if(d&&typeof d.id==='string'&&['device','project'].includes(d.side)&&(d.unset===true||typeof d.text==='string'))draft[setField(d.id,d.side)]=d;
  return{draft,undo:(Array.isArray(o.undo)?o.undo:[]).filter(x=>x&&x.table&&x.key&&x.was&&x.now)};
}
/* a value with its keys in order, to compare; [models] kinds counts with its defaults, as it is in force */
const inOrder=v=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(x=>[x,inOrder(v[x])])):v;
const sameValue=(k,a,b)=>{const f=v=>JSON.stringify(inOrder(k.table==='models'&&k.key==='kinds'?{...k.default,...v}:v));return f(a)===f(b)};
/* what is left on `side` once its own value is taken out */
const resetValue=(k,side)=>side==='device'&&k.has_project?k.project:k.default;
const draftValue=(k,d)=>d.unset?{v:resetValue(k,d.side)}:pickOptions(k,d.text)?{v:pickValue(k,d.text)}:settingValue(k,d.text);
/* a change that changes nothing */
function draftSame(k,d){
  if(d.unset)return !k['has_'+d.side];
  if(d.set&&!k['has_'+d.side])return false;
  const r=draftValue(k,d);
  return !r.err&&sameValue(k,r.v,k['has_'+d.side]?k[d.side]:k.value);
}
/* the draft as what `settings_save` takes, and the fields whose words are no value: {f: why} */
function draftChanges(draft,all){
  const changes=[], errs={};
  for(const [f,d] of Object.entries(draft)){
    const k=all.find(x=>`${x.table}.${x.key}`===d.id);if(!k)continue;
    const r=draftValue(k,d);
    if(r.err)errs[f]=r.err;
    else changes.push({table:k.table,key:k.key,side:d.side,...(d.unset?{unset:true}:{value:r.v})});
  }
  return{changes,errs};
}
/* the settings rows of several kinds (KINDS_ROWS) that a change to [models] kinds changes */
const kindsDrafted=(k,d)=>{const r=draftValue(k,d);return r.err?[]:KINDS_ROWS.filter(g=>kindsModel(g.kinds,{...k.default,...r.v})!==kindsModel(g.kinds,k.value))};
/* how many changes a person sees in the draft */
const draftCount=(draft,all)=>Object.values(draft).reduce((n,d)=>{const k=all.find(x=>`${x.table}.${x.key}`===d.id);
  return n+(!k?0:d.id==='models.kinds'?Math.max(1,kindsDrafted(k,d).length):1)},0);
/* what puts the earlier values back, each only while the saved one is still there */
const undoChanges=undo=>undo.map(x=>({table:x.table,key:x.key,side:x.side,...(x.was.has?{value:x.was.value}:{unset:true}),expect:x.now}));
const undoCount=undo=>undo.reduce((n,x)=>n+(x.key==='kinds'&&x.table==='models'?Math.max(1,KINDS_ROWS.filter(g=>kindsModel(g.kinds,x.was.value)!==kindsModel(g.kinds,x.now.value)).length):1),0);
const changeWords=n=>n===1?'1 change':`${n} changes`;
/* F460a: Settings > Plan's "Share the plan between machines": what `plan_share` answered as {lines, cmd, err}: the lines it says
   and, when it worked, its last one apart: what the other machine runs */
function planShareView(j){
  const lines=(j&&Array.isArray(j.lines)?j.lines:[]).map(String).filter(x=>x.trim());
  if(!j||!j.ok)return{lines:lines.length?lines:[String((j&&j.out)||'It did not work')],cmd:'',err:true};
  return{lines:lines.slice(0,-1),cmd:lines.length?lines[lines.length-1]:'',err:false};
}
