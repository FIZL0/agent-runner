/* B851c: what a run control's toast says, in plain words: never the command's raw output or a path */
/* a line of the command's output fit to show: one short line with no path, command or code in it */
function plainWhy(out){
  const s=String(out||'').split('\n')[0].trim();
  return s&&s.length<=90&&!/[\/\\`$<>{}]|\brun (status|plan|done)\b|Traceback|Error:/.test(s)?s:'';
}
/* the toast for a control's answer j: '' when the button itself shows the result (shows) */
function ctlSaid(say,j,shows){
  if(!j||!j.ok){const why=j&&(j.said||plainWhy(j.error||j.out));return `Not done: ${say}`+(why?`. ${why}`:'')}
  if(shows)return '';
  return j.said||`${say}: done`;
}
/* Home's project controls: the card shows pause, go on, stop and a set slot count at once; '+1'/'-1' say the change */
function homeSaid(name,arg,say,j){
  if(!j||!j.ok)return ctlSaid(say,j,false);
  if(name==='slots'&&!/^\d+$/.test(String(arg||'')))return arg==='-1'?'One slot less':'One more slot';
  return ctlSaid(say,j,['start','pause','resume','stop','slots'].includes(name));
}
if(typeof module!=='undefined')module.exports={plainWhy,ctlSaid,homeSaid};
