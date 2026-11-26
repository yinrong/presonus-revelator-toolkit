"""比较几条纯人声录音的音色：频段（相对 1.2-2.5k）、谐噪比、4-8k 平坦度、有声段动态。
用法: ./py voice_compare.py a.m4a b.m4a   （输入要是纯人声，例如全民K歌 files/uploadpcm/*.m4a）"""
import sys, subprocess, numpy as np, librosa
def load(p, sr=44100):
    raw = subprocess.run(["ffmpeg","-v","error","-i",p,"-ac","2","-ar",str(sr),"-f","f32le","-"],capture_output=True,check=True).stdout
    return np.frombuffer(raw,np.float32).reshape(-1,2).mean(1).astype(np.float32), sr
bands=[(80,150),(150,300),(300,600),(600,1200),(1200,2500),(2500,5000),(5000,9000),(9000,16000)]
for p in sys.argv[1:]:
    x,sr=load(p)
    f0,vf,_=librosa.pyin(x,fmin=70,fmax=900,sr=sr,frame_length=4096,hop_length=1024)
    S=np.abs(librosa.stft(x,n_fft=4096,hop_length=1024))**2; fr=librosa.fft_frequencies(sr=sr,n_fft=4096)
    n=min(S.shape[1],len(vf)); S=S[:,:n]; vf=vf[:n]; f0=f0[:n]
    loud=10*np.log10(S.sum(0)+1e-12); act=loud>np.max(loud)-40
    v=vf&act
    spec=S[:,v].mean(1); ref=spec[(fr>=1200)&(fr<2500)].mean()
    bl=[10*np.log10(spec[(fr>=a)&(fr<b)].mean()/ref) for a,b in bands]
    # 谐波/噪声：每个有声帧，取 f0 各次谐波附近能量 vs 其余能量（2k 以下）
    hnr=[]
    for i in np.where(v)[0]:
        if np.isnan(f0[i]): continue
        m=fr<4000; h=np.zeros_like(fr,bool)
        for k in range(1,int(4000/f0[i])):
            h|=np.abs(fr-k*f0[i])<f0[i]*0.12
        e=S[:,i]; hnr.append(10*np.log10(e[h&m].sum()/(e[~h&m].sum()+1e-12)))
    # 高频（4-8k）在有声帧里的平坦度：越接近 1 越像噪声（沙哑/气声）
    hb=(fr>=4000)&(fr<8000); flat=np.exp(np.log(S[hb][:,v]+1e-12).mean(0))/(S[hb][:,v].mean(0)+1e-12)
    rms=10*np.log10(S[:,v].sum(0)); 
    print(f"{p.split('/')[-1]:32s} 有声帧 {v.sum():4d}  谐噪比中位 {np.median(hnr):5.1f} dB  4-8k平坦度 {np.median(flat):.2f}  有声动态 p95-p10 {np.percentile(rms,95)-np.percentile(rms,10):4.1f} dB")
    print("   频段(相对1.2-2.5k): "+"  ".join(f"{a}-{b}:{l:+.1f}" for (a,b),l in zip(bands,bl)))
