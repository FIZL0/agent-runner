const pickVoice=(voices,name)=>name?(voices||[]).find(v=>v.name===name)||null:null;
/* F158: the run voice (speech made on the run's machine) that reads, '' for the browser's own: `got` is the run's
   /speech answer, `name` the voice set in Talk settings. A run voice that is gone gives the run's default */
function runVoice(got,name){
  const vs=(got&&got.voices)||[];if(!vs.length||name==='system')return '';
  if(!name||/^(kokoro|piper):/.test(name))return vs.some(v=>v.id===name)?name:got.default||'';
  return '';  // a voice of this device
}
/* F158: a reply as the clips it is read in: its first sentence alone, so sound starts soon, then about 200 letters, then
   400 each (B178: few clips, for each new one can make Bluetooth reopen) */
function speechClips(text){
  const out=[];
  for(const s of String(text||'').match(/\S[\s\S]*?(?:[.!?]+(?=\s|$)|$)/g)||[])
    for(let i=0;i<s.length;i+=1000){const p=s.slice(i,i+1000).trim(), l=out.length-1;if(!p)continue;
      if(out.length&&(l>0||out[0].length<15)&&out[l].length+p.length<(l>1?400:200))out[l]+=' '+p;else out.push(p)}
  return out;
}
/* F158: 0.1 s of silence as a WAV file's bytes: played in a tap, it lets the page's audio element play later without one */
function silentWav(n=800){
  const b=new Uint8Array(44+n).fill(128), v=new DataView(b.buffer), s=(i,t)=>[...t].forEach((c,j)=>b[i+j]=c.charCodeAt(0));
  s(0,'RIFF');v.setUint32(4,36+n,true);s(8,'WAVEfmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);
  v.setUint32(24,8000,true);v.setUint32(28,8000,true);v.setUint16(32,1,true);v.setUint16(34,8,true);s(36,'data');v.setUint32(40,n,true);
  return b;
}
/* B134: where a feed ends at a send, so what comes after it is found in a later feed even once the feed is capped and
   its indexes move: the last entry's own id, else (a transcript without ids) all its entries */
