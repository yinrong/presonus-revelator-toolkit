import sys, glob, numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt
for p in sys.argv[1:]:   # 用法: ./py rec_report.py a.wav b.wav ...
    x, sr = sf.read(p); L, R = x[:,0], x[:,1]; m = x.mean(1)
    side = 20*np.log10(np.sqrt(np.mean((L-R)**2))+1e-12) - 20*np.log10(np.sqrt(np.mean(m**2))+1e-12)
    h = int(0.05*sr); fr = m[:len(m)//h*h].reshape(-1,h); r = 20*np.log10(np.sqrt((fr**2).mean(1))+1e-12)
    floor = np.percentile(r, 5); voiced = r > min(floor + 20, np.percentile(r, 60))
    pk = 20*np.log10(np.abs(x).max()); clip = int((np.abs(x) > 0.98).sum())
    # 削波连续段（≥3 个采样贴顶）
    a = np.abs(m) > 0.97; runs = np.diff(np.concatenate([[0], a.astype(int), [0]])); starts = np.where(runs==1)[0]; ends = np.where(runs==-1)[0]
    cliprun = int(np.sum((ends-starts) >= 3))
    # 喷麦：<120Hz 能量 50ms 帧内突增并占主导
    lo = sosfilt(butter(4, 120, 'lp', fs=sr, output='sos'), m)
    lr = 20*np.log10(np.sqrt((lo[:len(lo)//h*h].reshape(-1,h)**2).mean(1))+1e-12)
    plos = int(np.sum((lr - r > -3) & (lr > floor + 25) & (np.r_[0, np.diff(lr)] > 10)))
    # 咔哒：>6kHz 高通后的瞬时尖峰（比 10ms 局部 RMS 高 12 倍，且持续 <1ms）
    hp = sosfilt(butter(4, 6000, 'hp', fs=sr, output='sos'), m)
    w = int(0.01*sr); loc = np.sqrt(np.convolve(hp**2, np.ones(w)/w, 'same')) + 1e-9
    spikes = np.where(np.abs(hp) > 12*loc)[0]
    clicks = 0; last = -10**9
    for s in spikes:
        if s - last > int(0.005*sr): clicks += 1
        last = s
    zeros = int(np.max(np.diff(np.where(np.concatenate([[1], (m!=0).astype(int), [1]]))[0])) - 1)
    print(f"{p.split('/')[-1]:28s} {len(m)/sr:4.0f}s | 立体差 {side:6.1f} dB | 峰值 {pk:5.1f} | 贴顶采样 {clip:5d} 连续削波段 {cliprun:4d} | 唱段RMS p50/p95 {np.percentile(r[voiced],50):5.1f}/{np.percentile(r[voiced],95):5.1f} | 底噪 {floor:5.1f} | 疑似喷麦 {plos:3d} | 高频尖峰 {clicks:4d} | 最长全零 {zeros} 采样")
