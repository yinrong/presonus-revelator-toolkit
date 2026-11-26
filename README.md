# PreSonus Revelator Toolkit

**Fix PreSonus Revelator microphones that stop working on Android after being plugged into Windows (no Mac required), plus an AI agent skill, vocal Fat Channel presets, and acoustic analysis scripts.**

[中文文档 (README.zh-CN.md)](./README.zh-CN.md) · [Technical Root Cause Deep Dive](./docs/TECHNICAL_ROOT_CAUSE.md) · [AI Agent Skill (`SKILL.md`)](./skills/revelator-toolkit/SKILL.md)

[![Platform: Windows + Android + macOS](https://img.shields.io/badge/platform-Windows%20%7C%20Android%20%7C%20macOS-blue)](#)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB)](./scripts/revelator_mode.py)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

---

## Does This Match Your Problem?

If your PreSonus Revelator shows **any** of these symptoms, this repo fixes it in 60 seconds:

| Symptom | What Is Actually Happening |
|---|---|
| Works fine on Windows PC, completely silent on Android (both recording and 3.5mm headphone playback fail across every app) | The mic is stuck in **Single Mode (`VID_194F&PID_0D08`, 6-channel)**. Android requires **Multi Mode (`PID_0D09`, 2-channel stereo)**. |
| Stopped working on Android right after plugging it into a Windows PC—even though you never changed any settings | PreSonus's Windows kernel driver (`PaeDSPUSB.sys`) writes a `RestartDeviceRequest` registry rule that silently forces Multi Mode back to Single Mode within ~1 second of plug-in. |
| Windows Universal Control has no Single/Multi Mode toggle, and you do not have a Mac | PreSonus hides the mode switcher in the Windows UI. Our script invokes the exact driver vendor request (`bRequest=0x42`) directly on Windows. |
| Windows Device Manager shows **`Revelator (unsupported mode)`** | That label is actually **Multi Mode (`PID_0D09`)**—the mode Android needs. |
| Android logs show `bNrChannels=6`, `transfer failed`, Audio DSP `SSR`, or `AudioRecord read -> buffer is mute` | Android's USB Audio HAL / DSP crashes when trying to open the 6-channel Single Mode interface. |

> **Hardware verification status:** End-to-end verified on physical **PreSonus Revelator (`VID_194F&PID_0D08` ↔ `PID_0D09`)** with Windows 11 + Android 17 (Xiaomi 18 Fold). **Revelator Dynamic**, **Revelator io24**, and **Revelator io44** have the exact same `RestartDeviceRequest` rule (`RequestCode=66`) in `paedspusb.inf`, though they have not yet been verified on physical hardware (PRs and test reports welcome!).

---

## 3-Step Quick Fix: Switch Revelator to Android Multi Mode on Windows

**Prerequisites:** Windows 10/11, Python 3.9+ (standard library only, zero pip installs), and Fender/PreSonus Universal Control drivers installed.

### 1. Plug the Revelator into your Windows PC and diagnose

```powershell
git clone https://github.com/yinrong/presonus-revelator-toolkit.git
cd presonus-revelator-toolkit
python scripts/revelator_mode.py diag
```

This read-only command prints your current USB mode (`PID_0D08` Single vs `PID_0D09` Multi) and lists any armed `RestartDeviceRequest` auto-revert registry traps.

### 2. Disarm the Windows kernel auto-revert trap

Close Universal Control if it is open, then remove the `PaeDSPUSB.sys` auto-revert trigger (with a JSON backup so you can restore it anytime via `rearm`):

```powershell
python scripts/revelator_mode.py disarm --elevate --backup trap-backup.json
```

*(Note: If this Windows USB port has never seen `PID_0D09` before, `diag` will show 0 traps initially. Run step 3 once—Windows will create the `PID_0D09` PnP instance and revert once—then run `disarm --elevate` and repeat step 3.)*

### 3. Switch to Multi Mode (`PID_0D09`) and verify zero revert

```powershell
python scripts/revelator_mode.py switch multi
```

The tool sends PreSonus's exact `SwitchAudioMode` vendor command (`bRequest=0x42, arg6=1`) via `PaeDSPUSBapi_x64.dll` and checks PnP at `+4s` and `+10s` to verify the device stays locked on **`VID_194F&PID_0D09`** (`Revelator`, `Stream Mix A`, `Stream Mix B`).

Unplug from Windows, plug into your Android phone, and both headphone monitoring and microphone recording work immediately.

### Switching Back to Windows Single Mode Later

```powershell
python scripts/revelator_mode.py switch single
```

Or restore the original Windows driver auto-revert behavior from your backup:

```powershell
python scripts/revelator_mode.py rearm --backup trap-backup.json --elevate
```

> **Important scope warning:** Windows creates a separate PnP instance key per physical USB port. Disarming protects the USB port you ran it on. Plugging a Multi-Mode Revelator into a **different USB port**, another Windows PC with PreSonus drivers, or reinstalling Universal Control will recreate `RestartDeviceRequest` and silently revert the mic to Single Mode again.

---

## Why This Happens (1-Minute Summary)

PreSonus's Windows driver (`paedspusb.inf`) attaches this registry entry to Multi Mode (`PID_0D09`):

```ini
"Revelator (unsupported mode)" = _Install_4,USB\VID_194F&PID_0D09&MI_00

[_AddReg_4]
HKR,"Config\RestartDeviceRequest","RequestCode",%REG_DWORD%,66   ; 0x42 = SwitchAudioMode
HKR,"Config\RestartDeviceRequest","RequestIndex",%REG_DWORD%,0
HKR,"Config\RestartDeviceRequest","RequestType",%REG_DWORD%,64   ; 0x40 = Vendor OUT
```

The moment a Multi-Mode Revelator connects to Windows, `PaeDSPUSB.sys` fires `bRequest=0x42, mode=0` in kernel mode and reprograms the mic's onboard flash back to Single Mode (`PID_0D08`, 6 channels)—which breaks Android USB audio. Read the full reverse-engineering and Android HAL log breakdown in [`docs/TECHNICAL_ROOT_CAUSE.md`](./docs/TECHNICAL_ROOT_CAUSE.md).

---

## Install as an AI Agent Skill (Claude Code / Codex / Antigravity)

Want your AI coding assistant to automatically diagnose USB modes, fix Android recording issues, tune Fat Channel vocal presets, and analyze vocal recordings?

Copy or symlink `skills/revelator-toolkit` into your agent's skills directory:

```bash
# Claude Code (global)
ln -s "$(pwd)/skills/revelator-toolkit" ~/.claude/skills/revelator-toolkit

# Or copy directly into any project's .claude/skills/
cp -r skills/revelator-toolkit /path/to/your/project/.claude/skills/
```

Once installed, the agent knows how to:
- Diagnose `PID_0D08` vs `PID_0D09` and `RestartDeviceRequest` traps via `scripts/revelator_mode.py diag --json`
- Safely disarm and switch USB modes without touching DFU / firmware endpoints
- Tune onboard Fat Channel presets (EQ, compressor makeup gain, limiter, delay/Voice FX) and headphone `Blend`
- Run quantitative vocal quality checks (clipping, plosives, spectral balance, harmonic-to-noise ratio, backing-track cancellation)

---

## Ready-to-Use Vocal Presets (`presets/*.channel`)

Five hardware-tested Fat Channel presets for singing, streaming, and voiceover (copy into `Documents/PreSonus/Revelator Mic/Fat/` and load via Universal Control):

| Preset | Character | Key Settings |
|---|---|---|
| [`Natural Voice.channel`](./presets/Natural%20Voice.channel) | Natural, clear vocals without proximity-effect mud | HPF 80 Hz · EQ 220 Hz -6 dB, 3.5 kHz +5 dB · Comp -30 dB 2:1 (+15 dB) · Limiter -1 dB · Voice FX off |
| [`Pop Studio.channel`](./presets/Pop%20Studio.channel) | Bright pop vocal with subtle studio room width | EQ 350 Hz -5 dB, 4 kHz +5 dB, 10 kHz +6 dB · Comp -26 dB 2.5:1 (+11 dB) · 25 ms reflection (mix 0.25) |
| [`Ballad.channel`](./presets/Ballad.channel) | Warm slow vocal with soft echo tail | HPF 100 Hz · EQ 300 Hz -3.5 dB, 3.5 kHz +3 dB, 10 kHz +4.5 dB · Echo ~315 ms |
| [`KTV Echo.channel`](./presets/KTV%20Echo.channel) | Karaoke-style audible echo | Echo ~270 ms |
| [`Raw Voice.channel`](./presets/Raw%20Voice.channel) | Clean dry A/B baseline | HPF only |

---

## Acoustic Analysis & Testing Scripts (`scripts/`)

| Script | Platform | What It Does |
|---|---|---|
| [`revelator_mode.py`](./scripts/revelator_mode.py) | Windows | `diag` / `disarm` / `rearm` / `switch multi\|single` CLI (stdlib only) |
| [`analyze.py`](./scripts/analyze.py) | Cross-platform | Measures noise floor, dynamic range, pitch range, spectral bands, sibilance, plosives |
| [`rec_report.py`](./scripts/rec_report.py) | Cross-platform | Detects clipped samples, consecutive clipping runs, plosives, clicks, and RMS percentiles |
| [`voice_compare.py`](./scripts/voice_compare.py) | Cross-platform | Compares dry vocal recordings by frequency bands, HNR, 4–8 kHz flatness, and dynamics |
| [`cancel.py`](./scripts/cancel.py) | Cross-platform | Phase-cancels two takes sharing a backing track to measure true vocal level |
| [`ir.py`](./scripts/ir.py) | Cross-platform | Measures impulse response echo peaks and decay times |
| [`burst.sh`](./scripts/burst.sh) / [`click.sh`](./scripts/click.sh) | macOS | Reproducible pink-noise and click speaker-to-mic benchmarks |
| [`spkvol.swift`](./scripts/spkvol.swift) | macOS | Reads/sets macOS built-in speaker volume for repeatable acoustic tests |

---

## Testing

```bash
python -m unittest discover -s tests -v
```

Unit tests verify VID/PID classification, `RestartDeviceRequest` registry scanning, exact `TUSBAUDIO_ClassVendorRequestOut` argument layout (`bRequest=0x42`), safety refusal on non-Revelator devices, and backup/dry-run flows offline. End-to-end hardware switching was verified on a physical PreSonus Revelator (`PID_0D08` ↔ `PID_0D09`) with Windows 11 and Android 17.

## License

[MIT](./LICENSE)
