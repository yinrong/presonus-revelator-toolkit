# PreSonus Revelator 工具箱（纯本地免费工具）

**零 AI 依赖、零 API 费用、无需 Mac：在 Windows 上一键修复 PreSonus Revelator 插安卓手机不能录音/耳机无声的问题，并附带纯程序人声自动调音器（自动生成 `.channel` 预设）和 5 套实测预设。**

[English README](./README.md) · [技术根因深度报告](./docs/TECHNICAL_ROOT_CAUSE.md) · [开发与 AI 探索指南 (`DEVELOPMENT.md`)](./DEVELOPMENT.md)

---

## 你是不是遇到了完全一样的症状？

| 现象 | 真正原因 |
|---|---|
| 插 Windows 电脑录音和监听都正常，插安卓手机（小米/华为/三星等）后**录音机、全民K歌、相机全部既无声又录不到声音** | 麦克风板载模式处于 **Single Mode（`VID_194F&PID_0D08`，单接口 6 声道）**；安卓必须使用 **Multi Mode（`PID_0D09`，独立 2 声道立体声）**。 |
| 明明没改过麦克风设置，只是插过一次 Windows 电脑，插回手机就彻底失效 | PreSonus 的 Windows 内核驱动 `PaeDSPUSB.sys` 给 `PID_0D09` 写了 `RestartDeviceRequest` 自动回刷规则，**插上电脑 1 秒内静默把麦克风刷回 Single Mode**，连 Universal Control 都不用打开。 |
| Windows 版 Universal Control 隐藏了 Single / Multi 切换开关，手边又没有 Mac | 本工具直接调用官方驱动 DLL（`PaeDSPUSBapi_x64.dll`）下发底层切模式指令（`bRequest=0x42`）。 |
| Windows 设备管理器里显示 **`Revelator (unsupported mode)`** | 这个提示恰恰说明麦克风已经在 **Multi Mode（`PID_0D09`）**，正是安卓手机需要的模式。 |
| 安卓底层日志出现 `bNrChannels=6`、`transfer failed`、音频 DSP 崩溃重启（`SSR`）或 `AudioRecord read -> buffer is mute` | 安卓 USB Audio HAL / DSP 打开 6 声道流报错崩溃。 |

> **实机验证范围：** 已在真实 **PreSonus Revelator（`VID_194F&PID_0D08` ↔ `PID_0D09`）** + Windows 11 + 小米 18 Fold（Android 17）完成全链路实机验收。`paedspusb.inf` 中 **Revelator Dynamic**、**Revelator io24**、**Revelator io44** 使用相同的 `RestartDeviceRequest`（`RequestCode=66`）规则，但尚未在对应实机硬件上验证（欢迎反馈）。

---

## 工具 1：在 Windows 上一键切回 Android Multi Mode（纯本地，无需 Mac）

**前置条件：** Windows 10/11、Python 3.9+（纯标准库，无需 `pip install`）、已安装 Fender/PreSonus Universal Control 驱动。

### 最省事用法：双击 `fix_android_mode.bat`

1. 下载或克隆本仓库，把 Revelator 插到 Windows 电脑 USB 口。
2. 双击运行 [`fix_android_mode.bat`](./fix_android_mode.bat)（弹出一次系统 UAC 确认框时点「是」，用于解除驱动的自动回刷项）。
3. 看到 `[SUCCESS] Revelator is locked in Multi Mode (PID_0D09)` 后，拔下直接插回安卓手机即可恢复播录。

### 或手动执行 3 条命令行

```powershell
git clone https://github.com/yinrong/presonus-revelator-toolkit.git
cd presonus-revelator-toolkit

# 1. 只读诊断当前 USB 模式（PID_0D08 还是 PID_0D09）与自动回刷陷阱
python scripts/revelator_mode.py diag

# 2. 关闭 Universal Control，解除 PaeDSPUSB.sys 自动回刷陷阱（自动留备份）
python scripts/revelator_mode.py disarm --elevate --backup trap-backup.json

# 3. 切到 Multi Mode（PID_0D09）并连续 10 秒核验零回弹
python scripts/revelator_mode.py switch multi
```

*（首次在某个 Windows USB 口操作时，`diag` 可能先显示 0 条陷阱；先跑一次第 3 步让系统生成 `PID_0D09` 设备记录，再跑 `disarm --elevate` 并重跑第 3 步即可，`fix_android_mode.bat` 已自动处理此情况。）*

### 以后想切回 Windows Single Mode

```powershell
python scripts/revelator_mode.py switch single
```

随时按备份恢复原厂 Windows 驱动回刷行为：

```powershell
python scripts/revelator_mode.py rearm --backup trap-backup.json --elevate
```

> **防复发提醒：** Windows 会为每个物理 USB 口生成独立的 PnP 实例键。`disarm` 只保护你操作过的那个 USB 口；把 Multi Mode 麦克风插到**其他 USB 口**、**另一台装了 PreSonus 驱动的 Windows 电脑**，或**重装 Universal Control**，都会重新生成 `RestartDeviceRequest` 并再次静默刷回 Single Mode。

---

## 工具 2：纯程序人声自动调音器（`auto_tune.py`，零 AI 费用）

录 10–30 秒干声（WAV 仅需 `pip install numpy`，M4A/MP3 另需 `ffmpeg`），一行命令自动体检并生成可直接导入 Universal Control 的 Fat Channel `.channel` 预设文件：

```bash
# 按自然人声目标曲线自动生成预设，并直接安装到 Universal Control 预设目录
python scripts/auto_tune.py my_vocal.wav --style natural --name "My Natural" --install

# 参考匹配模式：拿一条你喜欢的干声（例如手机自带话筒录的同一句）做音色对齐
python scripts/auto_tune.py revelator_take.wav --ref phone_mic_take.wav --name "Matched Voice" --install
```

`auto_tune.py` 自动完成 5 件事（全确定性 DSP 算法，0 Token）：
- **硬件削波告警：** 统计贴顶采样与连续削波段，若存在模拟削波直接提示调低硬件前级增益（长按 Monitor 旋钮变绿），不拿数字 EQ 假装救回削波。
- **喷麦与低频轰鸣控制：** 自动识别 120 Hz 以下喷麦突发，动态选择 80 Hz 或 100 Hz 高通滤波（HPF）。
- **安全边界 4 段 EQ：** 计算低中频闷糊（150–350 Hz）、咬字清晰度（2.5–5 kHz）、空气感（8–15 kHz）相对中频（1.2–2.5 kHz）的偏离，经阻尼并钳制在 `[-6, +6] dB`。
- **防爆音响度补偿：** 按目标有声 RMS（`-20 dBFS`）自动计算压缩比与数字增益补偿（钳制 `[0, +18] dB`），限幅器锁死 `-1.0 dB`。
- **4 种风格可选：** `--style natural`（自然干声）、`pop`（25 ms 短反射）、`ballad`（315 ms 柔和回声）、`ktv`（KTV 回声）。

---

## 内置 5 套实测人声预设（`presets/*.channel`）

将 `.channel` 文件复制到 `文档\PreSonus\Revelator Mic\Fat\`（macOS 为 `~/Documents/PreSonus/Revelator Mic/Fat/`），在 Universal Control 中导入设备预设格并绑定到颜色按钮；务必在设置中开启 **`Fat Channel on USB Stream Outputs — Ch 1`**，否则手机录到的是干声：

| 预设文件 | 适用场景 | 核心参数 |
|---|---|---|
| [`Natural Voice.channel`](./presets/Natural%20Voice.channel) | 自然人声（去近讲闷糊、贴近真实原声） | HPF 80 Hz · EQ 220 Hz -6 dB / 3.5 kHz +5 dB · 压缩 -30 dB 2:1 (+15 dB) · 限幅 -1 dB · Voice 关 |
| [`Pop Studio.channel`](./presets/Pop%20Studio.channel) | 明亮流行人声（轻短反射） | EQ 350 Hz -5 dB / 4 kHz +5 dB / 10 kHz +6 dB · 压缩 -26 dB 2.5:1 (+11 dB) · 25 ms 短反射 |
| [`Ballad.channel`](./presets/Ballad.channel) | 抒情慢歌（柔和回声尾音） | HPF 100 Hz · EQ 300 Hz -3.5 dB / 3.5 kHz +3 dB / 10 kHz +4.5 dB · Echo ~315 ms |
| [`KTV Echo.channel`](./presets/KTV%20Echo.channel) | KTV 混响风格 | Echo ~270 ms |
| [`Raw Voice.channel`](./presets/Raw%20Voice.channel) | 纯干声 A/B 对比基准 | 仅开 HPF |

---

## 独立声学分析脚本（`scripts/`）

| 脚本 | 平台 | 用途 |
|---|---|---|
| [`revelator_mode.py`](./scripts/revelator_mode.py) | Windows | `diag` / `disarm` / `rearm` / `switch multi\|single`（零第三方依赖） |
| [`auto_tune.py`](./scripts/auto_tune.py) | 跨平台 | 纯程序人声诊断 + 自动生成 `.channel` 预设（WAV 仅需 `numpy`） |
| [`analyze.py`](./scripts/analyze.py) | 跨平台 | 人声体检：底噪、动态范围、音域、频段偏离、齿音、喷麦 |
| [`rec_report.py`](./scripts/rec_report.py) | 跨平台 | 削波采样数、连续削波段、喷麦、咔哒尖峰、RMS 分位数 |
| [`voice_compare.py`](./scripts/voice_compare.py) | 跨平台 | 纯人声频段差、谐噪比（HNR）、4–8 kHz 平坦度、有声动态对比 |
| [`cancel.py`](./scripts/cancel.py) | 跨平台 | 同伴奏两条录音对齐相减，估算混音成品里的真实人声电平 |
| [`ir.py`](./scripts/ir.py) | 跨平台 | 冲激响应分析（回声峰间隔与衰减时间） |
| [`burst.sh`](./scripts/burst.sh) / [`click.sh`](./scripts/click.sh) / [`spkvol.swift`](./scripts/spkvol.swift) | macOS | 可复现粉红噪声电平对比与咔哒声冲激响应测试 |

---

## 参与开发与排查新硬件问题

如果你想运行单元测试、补充 `Revelator Dynamic / io24 / io44` 实机支持，或在探索未知驱动/声学新问题时使用仓库内置的 **AI Agent 探索技能**（`skills/revelator-toolkit/SKILL.md`，支持 Claude Code / Codex / Antigravity），请阅读 **[`DEVELOPMENT.md`](./DEVELOPMENT.md)**。

## 开源协议

[MIT](./LICENSE)
