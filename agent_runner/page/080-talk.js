/* Talk's words; talkShown: yours without their brief or reminder */
function talkConvo(n){
  const f=S.feeds[n];
  if(!f)return `<div class="msgs"><div class="think">${LOGO()}Loading…</div>${sentBubbles(n,talkShown)}${startLine(n)}</div>`;
  const ms=talkMsgs(f.entries);
  let h='';
  if(!ms.length)h+=`<div class="small" style="text-align:center">${esc(f.out||'Nothing said here yet.')}</div>`;
  ms.forEach((m,i)=>{
    const k=m.k||n+':'+i, mk=esc(k);
    if(m.w==='u'){h+=`<div class="u" data-k="${mk}" data-t="${esc(tkey(talkShown(m.text)))}">${esc(talkShown(m.text))}</div>`;return}
    const lead=i===0||ms[i-1].w!=='a'?`<div class="lead">${LOGO()}${esc(PN())}</div>`:'';
    const on=TK.playing===k;  // F124: a reply's play button
    h+=`<div class="a" data-k="${mk}">${lead}<div class="say" data-k="say:${mk}">${md(m.text)}</div><button type="button" class="speakb${on?' on':''}" data-speak="${mk}" aria-pressed="${on}" aria-label="${on?'Stop reading':'Read this reply aloud'}" title="${on?'Stop reading':'Read this reply aloud'}">${on?I.stop:I.speak}</button></div>`;
  });
  h+=sentBubbles(n,talkShown);  // B154
  if(starting(n))h+=startLine(n);
  else if(ended(n))h+=`<div class="small" style="text-align:center">This chat has ended.</div>`;  // B177
  else if(busy(n))h+=`<div class="think" data-k="think">${LOGO()}${WAVE}Working on it… · Ctrl+C interrupts</div>`;
  return `<div class="msgs">${h}</div>`;
}
