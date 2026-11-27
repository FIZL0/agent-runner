/* F509: a task's folded-open text: a landed task's finished write-up first, its original prompt folded under Asked; else the prompt */
function taskBodyHTML(t,k,landed){
  const e=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pre=(s,key)=>`<pre class="tasktext" data-k="${e(key)}">${e(s)}</pre>`;
  if(!(landed&&t.writeup))return pre(t.text,'text:'+k);
  return `${pre(t.writeup,'writeup:'+k)}<details class="asked" data-k="asked:${e(k)}"><summary>Asked</summary>${pre(t.text,'text:'+k)}</details>`;
}
if(typeof module!=='undefined')module.exports=Object.assign(module.exports||{},{taskBodyHTML});
