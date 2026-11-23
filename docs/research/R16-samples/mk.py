import json, numpy as np, soundfile as sf
from kokoro_onnx import Kokoro
d='/home/ryha/.local/share/agent-runner/speech/kokoro/'
k=Kokoro(d+'kokoro-v1.0.onnx', d+'voices-v1.0.bin')
T={
 's3':"Open task R sixteen and run the tests.",
 'm10':"Please check why task B one sixty two heard nothing on the iPhone. Then file a follow up for T nineteen and merge the branch when the gate passes.",
 'l30':"Start with the plan list, then look at task F one oh six and tell me which files it changes. After that, read the run page for task R fifteen, and compare the Piper voice with the Kokoro voice. If the merge test fails, block the task and say what a person has to decide. Finally, queue a research task for the Talk microphone, and note that the first word of each sentence is often cut off on the phone.",
}
ref={}
for n,t in T.items():
    a,sr=k.create(t,voice='af_heart',speed=1.0,lang='en-us')
    # trim leading/trailing silence
    nz=np.where(np.abs(a)>0.01)[0]; a=a[nz[0]:nz[-1]+1]
    sf.write(f'{n}_lead0.wav',a,sr)
    sf.write(f'{n}_lead500.wav',np.concatenate([np.zeros(int(.5*sr)),a]),sr)
    print(n,len(a)/sr)
# run from the clips/ directory next to bench.py; then encode the copies, see the findings doc section 7
