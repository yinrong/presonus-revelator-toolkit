"""两条伴奏相同、伴奏增益相同（或接近）的录音对齐相减：伴奏抵消，残差≈两次人声之差，用来量录音里人声有多大。
用法: ./py cancel.py a.wav b.wav   （a 当参考；先用 a 的 2-12s 前奏在 b 里找对齐，再按 5s 窗逐段微调）
读法：前奏窗 resid-a 应在 -20dB 以下（伴奏抵消干净）；唱段 resid ≈ 人声电平 +3dB（两次人声不相关）。"""
import sys, subprocess, numpy as np
from scipy.signal import fftconvolve
def load(p, sr=44100):
    # 用 ffmpeg 解码成立体声再在这里取平均（ffmpeg 的 -ac 1 下混会把 L=R 的信号抬高 3dB，量电平会错）
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64).reshape(-1, 2).mean(1), sr
a, sr = load(sys.argv[1]); b, _ = load(sys.argv[2])
db = lambda x: 20*np.log10(np.sqrt(np.mean(x**2))+1e-12)
seg = a[int(2*sr):int(12*sr)]
c = fftconvolve(b[:int(40*sr)], seg[::-1], mode="valid"); lag0 = int(np.argmax(c)) - int(2*sr)
print(f"整体对齐：b 比 a 偏移 {lag0/sr*1000:.1f} ms")
L = int(5*sr); search = int(0.3*sr)
print(" t(s)  lag(ms)  a(dB)  resid(dB)  resid-a")
for t0 in range(0, len(a)-L, L):
    x = a[t0:t0+L]; lo = max(0, t0+lag0-search); hi = min(len(b), t0+lag0+L+search)
    if hi-lo < L: break
    y = b[lo:hi]; k = int(np.argmax(fftconvolve(y, x[::-1], mode="valid"))); yy = y[k:k+L]
    g = np.dot(x, yy)/np.dot(yy, yy); r = x - g*yy
    print(f"{t0/sr:5.0f}  {(lo+k-t0)/sr*1000:7.1f}  {db(x):6.1f}  {db(r):7.1f}  {db(r)-db(x):+6.1f}  g={g:.2f}")
