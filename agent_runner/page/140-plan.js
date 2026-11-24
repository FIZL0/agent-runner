function planHTML(){
  const pk=queueGroups(S.snap.queue)[1], sh=S.snap.shelved||[], shOb=obCards(x=>x.shelved), qs=planQueue(S.snap), rs=planReleases(S.snap);
  return `<div class="col">${releasesOn(S.snap)?`<div class="sec">Releases<span class="ln"></span></div>${rs.length?`${rs.map(q=>q.placeholder?nextReleaseCard(q):releaseCard(q)).join('')}`:''}`:''}${newReleaseCard()}<div class="sec">Queue<span class="ln"></span></div>${qs.length?qs.map(planCard).join(''):emptyCard('The queue is empty.')}
    ${obCards(x=>obActs(x,'queue'))}${pk.length||sh.length||shOb?`<div class="sec">Parked<span class="ln"></span></div>${pk.map(parkedCard).join('')}${shOb}${sh.map(shelvedCard).join('')}`:''}</div>`;
}
/* F87: the Concepts view: every concept waiting for a pick, as agent-runner ui's Concepts panel lists them */
function conceptsHTML(){
  const cs=S.snap.concepts||[];
  return `<div class="col"><div class="sec">Concepts<span class="ln"></span></div>
    ${obCards(x=>x.concept)}${cs.length?cs.map(conceptCard).join(''):emptyCard(`${NO_CONCEPT}`)}</div>`;
}
/* F83: where each view was scrolled to (S.at), whether Talk follows its newest words (S.pin) */
