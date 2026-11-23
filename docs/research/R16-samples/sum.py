import json,collections,statistics as st
R=[]
for f in ('bcpu','bvk','fw'): R+=json.load(open(f'res_{f}.json'))
def key(r): return (r['engine'],r['model'])
g=collections.defaultdict(list)
for r in R: g[key(r)].append(r)
print('engine model | WERnoPrompt(all clips,wav) WERprompt | first-word hit lead0 | sec s3/m10/l30 (wav lead0 noprompt)')
for k,rs in sorted(g.items()):
    def w(p,lead=None): 
        x=[r['wer'] for r in rs if r['prompt']==p and r['fmt']=='wav' and (lead is None or r['clip'].endswith(lead))]; return round(st.mean(x),3)
    fh=[r['first'] for r in rs if r['clip'].endswith('lead0') and not r['prompt']]
    fh5=[r['first'] for r in rs if r['clip'].endswith('lead500') and not r['prompt']]
    t=[next(r['sec'] for r in rs if r['clip']==c+'_lead0' and r['fmt']=='wav' and not r['prompt']) for c in('s3','m10','l30')]
    tp=[next(r['sec'] for r in rs if r['clip']==c+'_lead0' and r['fmt']=='wav' and r['prompt']) for c in('s3','m10','l30')]
    fm=[r['wer'] for r in rs if r['fmt']!='wav']; fmw=[(r['fmt'],r['wer']) for r in rs if r['fmt']!='wav']
    print(k,w(False),w(True),'| first lead0',sum(fh),'/',len(fh),'lead500',sum(fh5),'/',len(fh5),'| s',t,'prompt s',tp,'| m4a/webm wer mean',round(st.mean(fm),3))
print()
for r in R:
    if r['prompt']==False and r['fmt']=='wav' and r['wer']>0: print(key(r),r['clip'],r['wer'],r['hyp'][:150])
print('PROMPT effects (wer noprompt->prompt per clip)')
for k,rs in sorted(g.items()):
    d=[(r['clip'],r['wer'],next(q['wer'] for q in rs if q['prompt'] and q['clip']==r['clip'])) for r in rs if not r['prompt'] and r['fmt']=='wav']
    print(k,[x for x in d if x[1]!=x[2]])
