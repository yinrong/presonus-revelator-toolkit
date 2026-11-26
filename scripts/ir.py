"""冲激响应分析：3 下咔哒平均，列回声峰（时刻/电平），算衰减到 -20/-30 dB 的时间、50-500ms 湿声能量"""
import sys,numpy as np,soundfile as sf
for p in sys.argv[1:]:
    x,sr=sf.read(p); x=x if x.ndim==1 else x.mean(1)
    h=int(0.005*sr); e=10*np.log10((x[:len(x)//h*h].reshape(-1,h)**2).mean(1)+1e-15)
    floor=np.median(e); pk=[i for i in range(1,len(e)-1) if e[i]>floor+25 and e[i]>=e[i-1] and e[i]>=e[i+1]]
    cl=[]
    for i in pk:
        if not cl or i-cl[-1]>150: cl.append(i)
    n=200  # 1 秒
    segs=[e[c:c+n]-e[c] for c in cl[:3] if c+n<=len(e)]
    m=10*np.log10(np.mean([10**(s/10) for s in segs],axis=0)); fl=floor-np.mean([e[c] for c in cl[:3]])
    # 回声峰：>-25dB 且为局部峰、距前一峰 >=20ms
    ech=[]
    for i in range(4,n-3):
        if m[i]>-25 and m[i]>=m[i-1] and m[i]>=m[i+1] and m[i]>max(m[i-3],m[i+3])+2:
            if not ech or i-ech[-1]>=4: ech.append(i)
    sm=np.convolve(10**(m/10),np.ones(10)/10,'same'); smd=10*np.log10(sm+1e-15)
    def t_to(th):
        idx=np.where(smd<th)[0]; idx=idx[idx>4]; return idx[0]*5 if idx.size else None
    wet=10*np.log10(np.sum(10**(m[10:100]/10))*0.005/0.005/90+1e-15)
    print(f"{p}: 咔哒数 {len(cl)} 底噪相对 {fl:.0f} dB | 回声峰: "+", ".join(f"{i*5}ms({m[i]:.0f})" for i in ech[:8])+f" | 平滑包络降到-20dB {t_to(-20)}ms, -30dB {t_to(-30)}ms | 50-500ms 平均 {wet:.1f} dB")
