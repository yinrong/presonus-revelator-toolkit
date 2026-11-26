"""人声干声分析：底噪、电平、动态、音域、频谱形状、齿音、喷麦。用法: analyze.py file.wav [noise_seconds]"""
import sys
import numpy as np
import soundfile as sf
import librosa
from scipy.signal import welch

path = sys.argv[1]
noise_sec = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
x, sr = sf.read(path, always_2d=True)
x = x.mean(axis=1)
dur = len(x) / sr
db = lambda v: 20 * np.log10(np.maximum(v, 1e-12))

# 帧 RMS（50 ms）
hop = int(0.05 * sr)
frames = x[: len(x) // hop * hop].reshape(-1, hop)
rms = np.sqrt((frames ** 2).mean(axis=1))
rms_db = db(rms)
noise_frames = rms_db[: int(noise_sec / 0.05)]
noise_db = np.median(noise_frames)
active = rms_db > noise_db + 20
act_db = rms_db[active]

peak = db(np.abs(x).max())
clip = int((np.abs(x) > 0.989).sum())
print(f"时长 {dur:.1f}s  采样率 {sr}")
print(f"底噪(前{noise_sec:.0f}s中位) {noise_db:.1f} dBFS   峰值 {peak:.1f} dBFS   近削波样本 {clip}")
if act_db.size == 0:
    print("没有检测到明显的人声段")
    sys.exit()
p10, p50, p95 = np.percentile(act_db, [10, 50, 95])
print(f"有声帧占比 {active.mean()*100:.0f}%   有声段RMS p10/p50/p95 = {p10:.1f}/{p50:.1f}/{p95:.1f} dBFS   动态(p95-p10) {p95-p10:.1f} dB")
print(f"信噪比(有声中位-底噪) {p50-noise_db:.1f} dB   峰值余量(0dBFS-峰值) {-peak:.1f} dB")

# 音域：pYIN
f0, vflag, _ = librosa.pyin(x.astype(np.float32), fmin=65, fmax=1200, sr=sr, frame_length=4096, hop_length=512)
f0v = f0[vflag & ~np.isnan(f0)]
if f0v.size:
    q = np.percentile(f0v, [3, 10, 50, 90, 97])
    names = [librosa.hz_to_note(v) for v in q]
    print("音高 p3/p10/p50/p90/p97: " + "  ".join(f"{n}({v:.0f}Hz)" for n, v in zip(names, q)))
    print(f"有音高帧 {f0v.size}  音域(p3~p97) {names[0]} ~ {names[-1]}")

# 长时平均频谱（只用有声帧）
act_idx = np.repeat(active, hop)[: len(x)]
xa = x[: len(act_idx)][act_idx[: len(x)]]
f, pxx = welch(xa, fs=sr, nperseg=8192)
pdb = 10 * np.log10(pxx + 1e-20)

bands = [(40, 80, "超低/喷麦"), (80, 150, "低频胸腔"), (150, 300, "温暖"), (300, 600, "浑浊/箱声"),
         (600, 1200, "鼻音/喇叭"), (1200, 2500, "中高"), (2500, 5000, "清晰度/穿透"),
         (5000, 9000, "齿音"), (9000, 16000, "空气感")]
band_db = []
for lo, hi, _ in bands:
    m = (f >= lo) & (f < hi)
    band_db.append(10 * np.log10(np.mean(pxx[m]) + 1e-20))
band_db = np.array(band_db)
# 以 200 Hz–8 kHz 的对数线性趋势为基准，看各频段偏离
m = (f >= 200) & (f <= 8000)
coef = np.polyfit(np.log10(f[m]), pdb[m], 1)
print(f"频谱斜率(200Hz-8kHz) {coef[0]*np.log10(2):.1f} dB/倍频程")
print("频段  相对1-2.5k(dB)  偏离趋势(dB)")
ref = band_db[5]
for (lo, hi, name), bd in zip(bands, band_db):
    centre = np.sqrt(lo * hi)
    trend = np.polyval(coef, np.log10(centre))
    trend_band = 10 * np.log10(np.mean(10 ** (pdb[(f >= lo) & (f < hi)] / 10)))
    print(f"  {lo:>5}-{hi:<5} {name:<8} {bd-ref:+6.1f}        {trend_band-trend:+5.1f}")

# 齿音：5-9k 能量相对 1-4k 的逐帧比，看尖峰
S = np.abs(librosa.stft(x.astype(np.float32), n_fft=2048, hop_length=512)) ** 2
fr = librosa.fft_frequencies(sr=sr, n_fft=2048)
e_s = S[(fr >= 5000) & (fr < 9000)].sum(axis=0)
e_m = S[(fr >= 1000) & (fr < 4000)].sum(axis=0)
loud = db(np.sqrt(S.sum(axis=0))) > np.percentile(db(np.sqrt(S.sum(axis=0))), 40)
ratio = 10 * np.log10((e_s + 1e-12) / (e_m + 1e-12))[loud]
print(f"齿音比(5-9k/1-4k) 中位 {np.median(ratio):.1f} dB   p95 {np.percentile(ratio,95):.1f} dB   >0dB帧占比 {(ratio>0).mean()*100:.1f}%")

# 喷麦：<100 Hz 能量突发
e_low = S[fr < 100].sum(axis=0)
e_all = S.sum(axis=0) + 1e-12
low_ratio = 10 * np.log10(e_low / e_all + 1e-12)[loud]
print(f"低频占比(<100Hz) 中位 {np.median(low_ratio):.1f} dB   p99 {np.percentile(low_ratio,99):.1f} dB")
