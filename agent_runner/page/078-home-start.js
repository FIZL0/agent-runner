/* F402c: Home's Start card while no run is up: Start the run, its starting state, or why it did not start with Retry, in place */
function homeStart(){
  const c=runStarts(S.snap)&&controlOf('start');if(!c)return '';
  const busy=ctlBusy('start')||Date.now()-(S.startOk||0)<10000, bad=!busy&&S.ob.find(x=>x.ctl==='start:'&&x.state==='failed');
  const said=busy?'Starting the run…':bad?`Not started: ${obRefused(bad)?OLD_RUN:bad.err||'it did not work'}`:'No task starts until the run does.';
  return card(`<div class="row">${busy?'<span class="livedot"></span>':''}<div class="grow"><b>Not running</b><div class="small${bad?' v-bad':''}" data-k="startsaid" data-roll data-v="${esc(said)}">${esc(said)}</div></div></div>
    <div class="btns">${bad?obBtns(bad):`<button class="btn acc${busy?' busy':''}" data-ctl="start">${I.play}${esc(c.label)}</button>`}</div>`,'','data-k="start"');
}
