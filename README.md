# PreSonus Revelator Toolkit

**Free, pure-local tools (no AI, no API fees, no Mac required) to fix PreSonus Revelator microphones that stop working on Android after plugging into Windows, plus an automatic vocal preset generator and 5 ready-to-use Fat Channel presets.**

[中文文档 (README.zh-CN.md)](./README.zh-CN.md) · [Technical Root Cause](./docs/TECHNICAL_ROOT_CAUSE.md) · [Developer & AI Skill Guide (`DEVELOPMENT.md`)](./DEVELOPMENT.md)

[![Platform: Windows + Android + macOS](https://img.shields.io/badge/platform-Windows%20%7C%20Android%20%7C%20macOS-blue)](#)
[![Zero AI / Local Only](https://img.shields.io/badge/runtime-100%25%20local%20%7C%20%240%20cost-brightgreen)](#)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB)](./scripts/revelator_mode.py)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

---

## Does This Match Your Problem?

| Symptom | What Is Actually Happening |
|---|---|
| Works fine on Windows PC, completely silent on Android (both recording and 3.5mm headphone playback fail across every app) | The mic is stuck in **Single Mode (`VID_194F&PID_0D08`, 6-channel)**. Android requires **Multi Mode (`PID_0D09`, 2-channel stereo)**. |
| Stopped working on Android right after plugging it into a Windows PC—even though you never changed any settings | PreSonus's Windows kernel driver (`PaeDSPUSB.sys`) writes a `RestartDeviceRequest` registry rule that silently forces Multi Mode back to Single Mode within ~1 second of plug-in. |
| Windows Universal Control hides the Single/Multi Mode toggle, and you do not have a Mac | Our local script sends the exact official driver vendor command (`bRequest=0x42`) directly on Windows. |
| Windows Device Manager shows **`Revelator (unsupported mode)`** | That label is actually **Multi Mode (`PID_0D09`)**—the exact mode Android needs. |
| Android logs show `bNrChannels=6`, `transfer failed`, Audio DSP `SSR`, or `AudioRecord read -> buffer is mute` | Android's USB Audio HAL / DSP crashes when opening the 6-channel Single Mode stream. |

> **Hardware verification status:** End-to-end verified on physical **PreSonus Revelator (`VID_194F&PID_0D08` ↔ `PID_0D09`)** with Windows 11 + Android 17 (Xiaomi 18 Fold). **Revelator Dynamic**, **Revelator io24**, and **Revelator io44** have the identical `RestartDeviceRequest` rule (`RequestCode=66`) in `paedspusb.inf`, though they have not yet been verified on physical hardware (test reports welcome).

---

## Tool 1: Fix Revelator on Android From Windows (No Mac Needed)

**Requirements:** Windows 10/11, Python 3.9+ (standard library only, zero `pip install`), Fender/PreSonus Universal Control drivers installed.

### Fastest Way: Double-Click `fix_android_mode.bat`

1. Download or clone this repo and plug your Revelator into your Windows PC.
2. Double-click [`fix_android_mode.bat`](./fix_android_mode.bat) (approve the Windows UAC prompt once to disarm the driver's auto-revert registry key).
3. Wait for `[SUCCESS] Revelator is locked in Multi Mode (PID_0D09)`, unplug from Windows, and plug straight into your Android phone.

### Or Run the 3 CLI Commands Yourself

```powershell
git clone https://github.com/yinrong/presonus-revelator-toolkit.git
cd presonus-revelator-toolkit

# 1. Diagnose current USB mode (PID_0D08 Single vs PID_0D09 Multi) and traps (read-only)
python scripts/revelator_mode.py diag

# 2. Close Universal Control and disarm PaeDSPUSB.sys auto-revert (saves backup JSON)
python scripts/revelator_mode.py disarm --elevate --backup trap-backup.json

# 3. Switch to Multi Mode (PID_0D09) and verify 10 seconds with zero revert
python scripts/revelator_mode.py switch multi
```

*(First time on a given Windows USB port: `diag` may show 0 traps before `PID_0D09` has ever connected. Run step 3 once so Windows creates the `PID_0D09` PnP instance, then run `disarm --elevate` and repeat step 3—`fix_android_mode.bat` handles this automatically.)*

### Switching Back to Windows Single Mode Later

```powershell
python scripts/revelator_mode.py switch single
```

To restore the factory Windows driver auto-revert registry key anytime:

```powershell
python scripts/revelator_mode.py rearm --backup trap-backup.json --elevate
```

> **Port-scope warning:** Windows creates a separate PnP registry key per physical USB port. Disarming protects the USB port you ran it on. Plugging a Multi-Mode Revelator into a **different USB port**, another Windows PC with PreSonus drivers, or reinstalling Universal Control will recreate `RestartDeviceRequest` and silently revert the mic to Single Mode again.

---

## Tool 2: Pure-Program Automatic Vocal Tuner (`auto_tune.py`)

Record 10–30 seconds of dry singing or speaking, run one local command (`pip install numpy`; plus `ffmpeg` only if your input is `.m4a`/`.mp3`), and get a ready-to-import Fat Channel `.channel` preset—**100% deterministic DSP, \$0 cost**:

```bash
# Auto-tune a dry WAV recording for natural vocals and install straight into Universal Control
python scripts/auto_tune.py my_vocal.wav --style natural --name "My Natural" --install

# Or match the tone of a reference recording (e.g. a phone-mic take whose clarity you like)
python scripts/auto_tune.py revelator_take.wav --ref phone_mic_take.wav --name "Matched Voice" --install
```

What `auto_tune.py` checks and generates automatically:
- **Analog clipping alert:** Counts clipped samples and consecutive clipping runs; warns you when to lower hardware preamp gain (hold the Monitor knob until green) because digital EQ cannot repair clipped ADC peaks.
- **Plosive & rumble control:** Detects sub-120 Hz plosive bursts and sets HPF to `80 Hz` or `100 Hz`.
- **Safe 4-band EQ:** Measures mud (`150–350 Hz`), presence (`2.5–5 kHz`), and air (`8–15 kHz`) relative to midrange (`1.2–2.5 kHz`), damped and clamped to `[-6, +6] dB`.
- **Safe loudness staging:** Calculates compressor ratio and digital makeup gain (clamped `[0, +18] dB`) targeting `-20 dBFS` voiced RMS with the limiter locked at `-1.0 dB`.
- **4 styles:** `--style natural` (dry/clean), `pop` (25 ms studio reflection), `ballad` (315 ms soft echo), `ktv` (karaoke echo).

---

## Ready-to-Use Vocal Presets (`presets/*.channel`)

Copy any `.channel` file into `Documents/PreSonus/Revelator Mic/Fat/` (Windows or macOS), load it in Universal Control, and make sure **`Fat Channel on USB Stream Outputs — Ch 1`** is turned ON so phones receive the processed vocal:

| Preset | Best For | Key Settings |
|---|---|---|
| [`Natural Voice.channel`](./presets/Natural%20Voice.channel) | Natural singing & voiceover without proximity mud | HPF 80 Hz · EQ 220 Hz -6 dB, 3.5 kHz +5 dB · Comp -30 dB 2:1 (+15 dB) · Limiter -1 dB · Voice FX off |
| [`Pop Studio.channel`](./presets/Pop%20Studio.channel) | Bright pop vocal with subtle room width | EQ 350 Hz -5 dB, 4 kHz +5 dB, 10 kHz +6 dB · Comp -26 dB 2.5:1 (+11 dB) · 25 ms reflection |
| [`Ballad.channel`](./presets/Ballad.channel) | Warm slow vocal with soft echo tail | HPF 100 Hz · EQ 300 Hz -3.5 dB, 3.5 kHz +3 dB, 10 kHz +4.5 dB · Echo ~315 ms |
| [`KTV Echo.channel`](./presets/KTV%20Echo.channel) | Karaoke-style audible echo | Echo ~270 ms |
| [`Raw Voice.channel`](./presets/Raw%20Voice.channel) | Clean dry A/B comparison baseline | HPF only |

---

## Standalone Acoustic Analysis Scripts (`scripts/`)

| Script | Platform | Purpose |
|---|---|---|
| [`revelator_mode.py`](./scripts/revelator_mode.py) | Windows | `diag` / `disarm` / `rearm` / `switch multi\|single` (stdlib only) |
| [`auto_tune.py`](./scripts/auto_tune.py) | Cross-platform | Pure-DSP vocal diagnosis + `.channel` preset generator (`numpy` only for WAV) |
| [`analyze.py`](./scripts/analyze.py) | Cross-platform | Full vocal audit: noise floor, pitch range, dynamics, spectral bands, sibilance, plosives |
| [`rec_report.py`](./scripts/rec_report.py) | Cross-platform | Clipped samples, clipping runs, plosives, high-frequency clicks, RMS percentiles |
| [`voice_compare.py`](./scripts/voice_compare.py) | Cross-platform | Compare two dry vocals by frequency bands, HNR, 4–8 kHz flatness, and dynamics |
| [`cancel.py`](./scripts/cancel.py) | Cross-platform | Phase-cancel two takes sharing a backing track to isolate true vocal level |
| [`ir.py`](./scripts/ir.py) | Cross-platform | Impulse response echo peak and decay analyzer |
| [`burst.sh`](./scripts/burst.sh) / [`click.sh`](./scripts/click.sh) / [`spkvol.swift`](./scripts/spkvol.swift) | macOS | Repeatable speaker-to-mic pink-noise and click acoustic benchmarks |

---

## Why Does Windows Break Android Mode? (30-Second Summary)

PreSonus's Windows driver (`paedspusb.inf`) attaches a kernel auto-revert rule to Multi Mode (`PID_0D09`):

```ini
"Revelator (unsupported mode)" = _Install_4,USB\VID_194F&PID_0D09&MI_00

[_AddReg_4]
HKR,"Config\RestartDeviceRequest","RequestCode",%REG_DWORD%,66   ; 0x42 = SwitchAudioMode
HKR,"Config\RestartDeviceRequest","RequestIndex",%REG_DWORD%,0
HKR,"Config\RestartDeviceRequest","RequestType",%REG_DWORD%,64   ; 0x40 = Vendor OUT
```

The instant a Multi-Mode Revelator plugs into Windows, `PaeDSPUSB.sys` fires `bRequest=0x42, mode=0` in kernel mode and rewrites the mic's onboard flash back to 6-channel Single Mode (`PID_0D08`), breaking Android USB audio. Full disassembly and Android HAL log breakdown: [`docs/TECHNICAL_ROOT_CAUSE.md`](./docs/TECHNICAL_ROOT_CAUSE.md).

---

## Contributing & Exploring New Issues

For contributors, unit tests, adding support for `Revelator Dynamic / io24 / io44`, or using the optional **AI Agent Exploration Skill** (`skills/revelator-toolkit/SKILL.md` for Claude Code / Codex / Antigravity) to investigate brand-new hardware/driver issues and graduate them into pure local code, see **[`DEVELOPMENT.md`](./DEVELOPMENT.md)**.

## License

[MIT](./LICENSE)
