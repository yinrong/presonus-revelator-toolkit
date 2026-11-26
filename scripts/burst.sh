#!/bin/bash
# 用法: burst.sh 名称 振幅 —— 录 6 秒，第 1 秒起从 MacBook 喇叭放 2 秒粉红噪声（固定种子，每次相同）
HERE="$(cd "$(dirname "$0")" && pwd)"; OUT="${OUT:-./revelator-tests}"; mkdir -p "$OUT"; cd "$OUT"
# MacBook 内置喇叭在 ffmpeg audiotoolbox 里的序号（插拔设备会变，按名字找）
SPK=$(ffmpeg -hide_banner -f lavfi -i anullsrc -t 0.1 -f audiotoolbox -list_devices true - 2>&1 | sed -n "s/.*\[\([0-9]*\)\].*BuiltInSpeakerDevice.*/\1/p" | head -1)
ffmpeg -hide_banner -loglevel error -f avfoundation -i ":Revelator" -t 6 -ac 1 -ar 48000 -c:a pcm_s24le -y "b_$1.wav" &
R=$!
python3 -c "import time;time.sleep(1.2)"
ffmpeg -hide_banner -loglevel error -f lavfi -i "anoisesrc=color=pink:duration=2:amplitude=$2:seed=42" -af "afade=t=in:d=0.005,afade=t=out:st=1.995:d=0.005" -f audiotoolbox -audio_device_index "$SPK" - 
wait $R
"$HERE/py" - "b_$1.wav" <<'PY'
import sys,numpy as np,soundfile as sf
x,sr=sf.read(sys.argv[1]); x=x if x.ndim==1 else x.mean(1)
h=int(0.1*sr); r=20*np.log10(np.sqrt((x[:len(x)//h*h].reshape(-1,h)**2).mean(1))+1e-12)
print(sys.argv[1], "每0.1s电平:", " ".join(f"{v:.0f}" for v in r))
PY
