#!/bin/bash
# 用法: click.sh 名称 —— 录 5 秒，第 1.2 秒从喇叭放 3 下 15ms 噪声"咔哒"（间隔 1.2 秒），分析冲激响应
HERE="$(cd "$(dirname "$0")" && pwd)"; OUT="${OUT:-./revelator-tests}"; mkdir -p "$OUT"; cd "$OUT"
# MacBook 内置喇叭在 ffmpeg audiotoolbox 里的序号（插拔设备会变，按名字找）
SPK=$(ffmpeg -hide_banner -f lavfi -i anullsrc -t 0.1 -f audiotoolbox -list_devices true - 2>&1 | sed -n "s/.*\[\([0-9]*\)\].*BuiltInSpeakerDevice.*/\1/p" | head -1)
ffmpeg -hide_banner -loglevel error -f avfoundation -i ":Revelator" -t 5.5 -ac 1 -ar 48000 -c:a pcm_s24le -y "c_$1.wav" &
R=$!
python3 -c "import time;time.sleep(1.0)"
ffmpeg -hide_banner -loglevel error -f lavfi -i "anoisesrc=color=white:duration=0.015:amplitude=0.9:seed=7,apad=pad_dur=1.185,aloop=loop=2:size=57600" -f audiotoolbox -audio_device_index "$SPK" -
wait $R
"$HERE/py" - "c_$1.wav" <<'PY'
import sys,numpy as np,soundfile as sf
x,sr=sf.read(sys.argv[1]); x=x if x.ndim==1 else x.mean(1)
h=int(0.01*sr); e=20*np.log10(np.sqrt((x[:len(x)//h*h].reshape(-1,h)**2).mean(1))+1e-12)
floor=np.median(e)
pk=[i for i in range(1,len(e)-1) if e[i]>floor+25 and e[i]>=e[i-1] and e[i]>=e[i+1]]
cl=[]
for i in pk:
    if not cl or i-cl[-1]>60: cl.append(i)
print(f"{sys.argv[1]} 底噪 {floor:.0f}  咔哒: "+", ".join(f"{i*0.01:.2f}s({e[i]:.0f})" for i in cl))
# 三次平均的包络（相对峰值），每 20ms
segs=[e[c:c+110] for c in cl[:3] if c+110<=len(e)]
if segs:
    m=10*np.log10(np.mean([10**((s-s[0])/10) for s in segs],axis=0))
    print("  峰后每20ms(dB): "+" ".join(f"{m[k:k+2].max():.0f}" for k in range(0,110,2)))
PY
