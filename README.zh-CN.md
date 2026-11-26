# PreSonus Revelator 工具箱（Android 修复 + AI 自动调音 Skill）

**不借 Mac，在 Windows 上一键修复 PreSonus Revelator 插安卓手机不能录音/耳机无声的问题；附带通用 AI Agent 调音 Skill、5 套实测人声预设和声学分析脚本。**

[English README](./README.md) · [技术根因深度报告](./docs/TECHNICAL_ROOT_CAUSE.md) · [AI Agent Skill (`SKILL.md`)](./skills/revelator-toolkit/SKILL.md)

---

## 你是不是遇到了完全一样的症状？

| 现象 | 真正原因 |
|---|---|
| 插 Windows 电脑录音和监听都正常，插安卓手机（小米/华为/三星等）后**录音机、全民K歌、相机全部既无声又录不到声音** | 麦克风板载模式处于 **Single Mode（`VID_194F&PID_0D08`，单接口 6 声道）**；安卓系统必须使用 **Multi Mode（`PID_0D09`，独立 2 声道立体声）**。 |
| 明明没改过麦克风设置，只是插过一次 Windows 电脑，插回手机就突然彻底失效 | PreSonus 的 Windows 内核驱动 `PaeDSPUSB.sys` 给 `PID_0D09` 写了 `RestartDeviceRequest` 自动回刷规则，**插上电脑 1 秒内就会静默把麦克风刷回 Single Mode**，连 Universal Control 都不用打开。 |
| Windows 版 Universal Control 里压根找不到 Single / Multi 模式切换开关，手边又没有 Mac | PreSonus 在 Windows 界面里隐藏了切换入口。本工具直接调用驱动官方 DLL（`PaeDSPUSBapi_x64.dll`）下发底层切模式指令（`bRequest=0x42`）。 |
| Windows 设备管理器里显示 **`Revelator (unsupported mode)`** | 这个提示恰恰说明麦克风已经在 **Multi Mode（`PID_0D09`）**，正是安卓手机需要的模式。 |
| 安卓底层日志出现 `bNrChannels=6`、`transfer failed`、音频 DSP 崩溃重启（`SSR`）或 `AudioRecord read -> buffer is mute` | 安卓 USB Audio HAL / DSP 打开 6 声道流直接报错崩溃。 |

> **实机验证范围：** 已在真实 **PreSonus Revelator（`VID_194F&PID_0D08` ↔ `PID_0D09`）** + Windows 11 + 小米 18 Fold（Android 17）完成全链路实机验收。`paedspusb.inf` 中 **Revelator Dynamic**、**Revelator io24**、**Revelator io44** 使用完全相同的 `RestartDeviceRequest`（`RequestCode=66`）规则，但尚未在对应实机硬件上验证（欢迎提 Issue/PR 反馈）。

---

## 三步修复：在 Windows 上切回 Android Multi Mode

**前置条件：** Windows 10/11、Python 3.9+（纯标准库，无需 `pip install`）、已安装 Fender/PreSonus Universal Control 驱动。

### 第 1 步：把 Revelator 插到 Windows 电脑，运行诊断

```powershell
git clone https://github.com/yinrong/presonus-revelator-toolkit.git
cd presonus-revelator-toolkit
python scripts/revelator_mode.py diag
```

只读检查当前 USB 模式（`PID_0D08` Single 还是 `PID_0D09` Multi），以及是否存在已激活的 `RestartDeviceRequest` 自动回刷注册表陷阱。

### 第 2 步：解除 Windows 内核驱动的自动回刷陷阱

先关闭 Universal Control 界面，再运行（带 `--backup` 备份，随时可通过 `rearm` 还原）：

```powershell
python scripts/revelator_mode.py disarm --elevate --backup trap-backup.json
```

*（提示：如果这个 Windows USB 口以前从未识别过 `PID_0D09`，初次 `diag` 会显示 0 条陷阱。先执行一次第 3 步让系统生成 `PID_0D09` 设备记录后，再跑 `disarm --elevate` 并重跑第 3 步即可。）*

### 第 3 步：切换到 Multi Mode（`PID_0D09`）并验证 10 秒零回弹

```powershell
python scripts/revelator_mode.py switch multi
```

脚本会通过 `PaeDSPUSBapi_x64.dll` 发送 `bRequest=0x42, arg6=1`，并在 `+4s` 与 `+10s` 两次复查 PnP，确认设备稳定停留在 **`VID_194F&PID_0D09`**（拆分为 `Revelator`、`Stream Mix A`、`Stream Mix B` 三个立体声设备）。

此时从电脑拔下麦克风，直接插回安卓手机，耳机监听和麦克风录音立即恢复正常。

### 以后想切回 Windows Single Mode

```powershell
python scripts/revelator_mode.py switch single
```

> **防复发提醒：** Windows 会为每个物理 USB 口生成独立的 PnP 实例键。`disarm` 只保护你操作过的那个 USB 口；如果把 Multi Mode 麦克风插到**其他 USB 口**、**另一台装了 PreSonus 驱动的 Windows 电脑**，或**重装 Universal Control**，驱动会重新生成 `RestartDeviceRequest` 并再次静默刷回 Single Mode。

---

## 安装为 AI Agent Skill（Claude Code / Codex / Antigravity）

将 `skills/revelator-toolkit` 链接或复制到你的 Agent skills 目录，即可让 AI 自动完成：
- **USB 模式故障诊断与恢复**（识别 `PID_0D08`/`PID_0D09`、解除 `RestartDeviceRequest`、一键切 Multi Mode）
- **Fat Channel 人声自动调音与耳返排障**（EQ / 压缩补偿 / 限幅 / 延迟 / `Blend` 监听比例 / 防削波）
- **录音质量量化分析**（削波统计、喷麦检测、频段对比、谐噪比、伴奏相减测人声电平）

```bash
# Claude Code 全局安装示例
ln -s "$(pwd)/skills/revelator-toolkit" ~/.claude/skills/revelator-toolkit
```

---

## 内置 5 套实测人声预设（`presets/*.channel`）

将 `presets/*.channel` 复制到 `文档\PreSonus\Revelator Mic\Fat\`（macOS 为 `~/Documents/PreSonus/Revelator Mic/Fat/`），在 Universal Control 中导入设备预设格并绑定到 4 个颜色按钮即可（注意在设置中开启 `Fat Channel on USB Stream Outputs — Ch 1`，否则手机录到的是干声）：

| 预设文件 | 适用场景 | 核心参数 |
|---|---|---|
| [`Natural Voice.channel`](./presets/Natural%20Voice.channel) | 自然人声（去近讲闷糊、贴近真实原声） | HPF 80 Hz · EQ 220 Hz -6 dB / 3.5 kHz +5 dB · 压缩 -30 dB 2:1 (+15 dB) · 限幅 -1 dB · Voice 关 |
| [`Pop Studio.channel`](./presets/Pop%20Studio.channel) | 明亮流行人声（轻短反射） | EQ 350 Hz -5 dB / 4 kHz +5 dB / 10 kHz +6 dB · 压缩 -26 dB 2.5:1 (+11 dB) · 25 ms 短反射 (mix 0.25) |
| [`Ballad.channel`](./presets/Ballad.channel) | 抒情慢歌（柔和回声尾音） | HPF 100 Hz · EQ 300 Hz -3.5 dB / 3.5 kHz +3 dB / 10 kHz +4.5 dB · Echo ~315 ms |
| [`KTV Echo.channel`](./presets/KTV%20Echo.channel) | KTV 混响风格 | Echo ~270 ms |
| [`Raw Voice.channel`](./presets/Raw%20Voice.channel) | 纯干声 A/B 对比基准 | 仅开 HPF |

---

## 声学分析与测试脚本（`scripts/`）

| 脚本 | 平台 | 用途 |
|---|---|---|
| [`revelator_mode.py`](./scripts/revelator_mode.py) | Windows | `diag` / `disarm` / `rearm` / `switch multi\|single` 一键工具（零第三方依赖） |
| [`analyze.py`](./scripts/analyze.py) | 跨平台 | 人声分析：底噪、动态范围、音域、频段偏离、齿音、喷麦 |
| [`rec_report.py`](./scripts/rec_report.py) | 跨平台 | 削波采样数、连续削波段、喷麦、咔哒尖峰、RMS 分位数 |
| [`voice_compare.py`](./scripts/voice_compare.py) | 跨平台 | 纯人声频段差、谐噪比（HNR）、4–8 kHz 平坦度、有声动态对比 |
| [`cancel.py`](./scripts/cancel.py) | 跨平台 | 同伴奏两条录音对齐相减，估算混音成品里的真实人声电平 |
| [`ir.py`](./scripts/ir.py) | 跨平台 | 冲激响应分析（回声峰间隔与衰减时间） |
| [`burst.sh`](./scripts/burst.sh) / [`click.sh`](./scripts/click.sh) | macOS | 粉红噪声电平对比与咔哒声冲激响应测试 |
| [`spkvol.swift`](./scripts/spkvol.swift) | macOS | 读取/设置 macOS 内置扬声器音量，保证多次测试电平可复现 |

---

## 运行单元测试

```bash
python -m unittest discover -s tests -v
```

## 开源协议

[MIT](./LICENSE)
