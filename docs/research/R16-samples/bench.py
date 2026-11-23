import json, re, subprocess, sys, time, os, jiwer
S=os.path.dirname(os.path.abspath(__file__)); C=S+'/clips/'
REF={'s3':"Open task R16 and run the tests.",
 'm10':"Please check why task B162 heard nothing on the iPhone. Then file a follow up for T19 and merge the branch when the gate passes.",
 'l30':"Start with the plan list, then look at task F106 and tell me which files it changes. After that, read the run page for task R15, and compare the Piper voice with the Kokoro voice. If the merge test fails, block the task and say what a person has to decide. Finally, queue a research task for the Talk microphone, and note that the first word of each sentence is often cut off on the phone."}
PROMPT="Task ids like R16, B162, T19, F106, R15. Words: Talk, Kokoro, Piper, iPhone, agent-runner, Hold."
def norm(t):
    t=t.lower().replace('-',' ')
    t=re.sub(r"[^a-z0-9' ]",' ',t)
    t=re.sub(r'\b([a-z]) (\d+)\b',r'\1\2',t)
    t=t.replace('follow up','followup')
    return ' '.join(t.split())
def score(n,hyp):
    r=norm(REF[n]); h=norm(hyp)
    return round(jiwer.wer(r,h),3), (h.split()[:1]==r.split()[:1]), h
rows=[]
def rec(eng,model,dev,prompt,clip,ext,dt,hyp):
    n=clip.split('_')[0]; w,f,h=score(n,hyp)
    rows.append(dict(engine=eng,model=model,device=dev,prompt=prompt,clip=clip,fmt=ext,sec=round(dt,2),wer=w,first=f,hyp=h)); print(rows[-1],flush=True)
which=sys.argv[1]
clips=[f'{n}_{l}' for n in ('s3','m10','l30') for l in ('lead0','lead500')]
if which=='fw':
    from faster_whisper import WhisperModel
    for model in ('base.en','small.en','large-v3-turbo'):
        for dev,ct in (('cpu','int8'),):
            m=WhisperModel(model,device=dev,compute_type=ct,cpu_threads=8)
            list(m.transcribe(C+'s3_lead0.wav',language='en')[0])  # warm
            for prompt in (False,True):
                for c in clips:
                    for ext in ('wav','m4a','webm'):
                        if ext!='wav' and not c.endswith('lead0'): continue
                        if ext!='wav' and prompt: continue
                        t=time.time(); segs,_=m.transcribe(C+f'{c}.{ext}',language='en',initial_prompt=PROMPT if prompt else None,beam_size=5)
                        txt=' '.join(s.text for s in segs); dt=time.time()-t
                        rec('faster-whisper',model,dev,prompt,c,ext,dt,txt)
else:
    build=which  # bcpu or bvk
    for model in ('base.en','small.en','large-v3-turbo-q5_0'):
        for prompt in (False,True):
            for c in clips:
                for ext in ('wav',) if prompt or not c.endswith('lead0') else ('wav','m4a','webm'):
                    # whisper-cli only reads wav/mp3/flac/ogg: convert others via ffmpeg to 16k wav first (as server would)
                    f=C+f'{c}.{ext}'
                    t=time.time()
                    if ext!='wav':
                        subprocess.run(['ffmpeg','-loglevel','error','-y','-i',f,'-ar','16000','-ac','1',S+'/x16.wav'],check=True); f=S+'/x16.wav'
                    cmd=[S+f'/wcpp/{build}/bin/whisper-cli','-m',S+f'/models/ggml-{model}.bin','-f',f,'-nt','-np','-t','8','-l','en']
                    if prompt: cmd+=['--prompt',PROMPT]
                    p=subprocess.run(cmd,capture_output=True,text=True)
                    wall=time.time()-t
                    load=re.search(r'load time =\s+([\d.]+) ms',p.stderr); tot=re.search(r'total time =\s+([\d.]+) ms',p.stderr)
                    dt=(float(tot.group(1))-float(load.group(1)))/1000 if load and tot else wall
                    rec('whisper.cpp-'+('vulkan' if build=='bvk' else 'cpu'),model,'gpu' if build=='bvk' else 'cpu',prompt,c,ext,dt,p.stdout)
json.dump(rows,open(S+f'/res_{which}.json','w'))
