---
name: revelator-toolkit
description: Diagnose, fix, and tune PreSonus Revelator USB microphones for Android, Windows, and macOS. Use when Revelator works on Windows PC but has no playback or silent recording on Android (Single Mode PID_0D08 vs Multi Mode PID_0D09, PaeDSPUSB.sys RestartDeviceRequest auto-revert), or when tuning Fat Channel EQ/compressor/limiter/reverb presets, fixing headphone monitoring (Blend/Phones), removing clipping/plosives, or running vocal acoustic analysis.
---

# PreSonus Revelator Toolkit Skill

This skill solves two real-world problems for PreSonus Revelator users:

1. **Android USB Audio Recovery (from Windows, no Mac required):** Switching a Revelator trapped in Windows Single Mode (`PID_0D08`, 6-channel) back to Android-required Multi Mode (`PID_0D09`, 2-channel stereo) while disarming the `PaeDSPUSB.sys` kernel driver's silent auto-revert trap.
2. **Fat Channel Vocal Tuning & Acoustic Analysis:** Managing onboard `.channel` presets, headphone monitoring balance (`Blend` / `Phones`), preamp gain staging, and quantitative audio diagnostics (`analyze.py`, `rec_report.py`, `voice_compare.py`, `cancel.py`, `ir.py`).

All scripts referenced below live in `../../scripts/` (or `scripts/` at repo root) and presets live in `../../presets/`.

---

## Workflow 1: Fix Revelator Broken on Android (No Playback + Silent Recording)

### Symptom Fingerprint
- The microphone and its 3.5mm monitoring jack work normally on a Windows PC.
- On an Android phone, **both** headphone playback and microphone capture fail across every app (recorder, karaoke, camera).
- Android logs (if captured via ADB) show `VID=0x194f PID=0x0d08`, `bNrChannels=6`, `transfer failed`, Audio DSP Subsystem Restart (`SSR`), or `AudioRecord read -> buffer is mute`.

### Do Not Fall Into the False-Exclusion Trap
Do **not** assume "works on PC -> mic is fine -> phone settings are broken." Revelator persists its USB mode in onboard flash. Windows requires **Single Mode (`PID_0D08`, 6ch)**, while Android requires **Multi Mode (`PID_0D09`, 2ch stereo)**. Worse, PreSonus's Windows kernel driver (`PaeDSPUSB.sys`) registers `Config\RestartDeviceRequest` (`RequestCode=66 / 0x42, RequestValue=0`) on `PID_0D09`, silently forcing the mic back to Single Mode within ~1 second of being plugged into Windows—even without opening Universal Control.

### Step-by-Step Recovery (Windows Host)

1. **Diagnose first (read-only, no admin required):**
   ```powershell
   python scripts/revelator_mode.py diag
   ```
   Check three fields:
   - `Connected Mic`: `PID_0D08` confirms Single Mode (breaks Android); `PID_0D09` confirms Multi Mode (Android-ready).
   - `Auto-Revert Key`: non-zero count means `PaeDSPUSB.sys` will immediately revert Multi Mode back to Single Mode.
   - `TUSBAUDIO DLL`: verifies `PaeDSPUSBapi_x64.dll` from Fender/PreSonus Universal Control is present.

2. **Close Universal Control** (`Universal Control.exe`) if open. Optionally stop `PreSonus Hardware Access Service` (`Manual` startup prevents background interference).

3. **Disarm the kernel auto-revert trap (requires Administrator / UAC):**
   - If the `PID_0D09` PnP key has never been created on this USB port yet, running `switch multi --force` once will trigger Windows to create the `PID_0D09` PnP instance (and revert once); then run `diag` to see the exact key.
   - Remove the trap (with optional JSON backup for easy restoration via `rearm`):
     ```powershell
     python scripts/revelator_mode.py disarm --elevate --backup trap-backup.json
     ```

4. **Switch to Multi Mode and verify 10-second stability:**
   ```powershell
   python scripts/revelator_mode.py switch multi
   ```
   - Sends PreSonus's exact vendor request `bRequest=0x42, arg5=0, arg6=1` via `PaeDSPUSBapi_x64.dll`.
   - Waits +4s and +10s to confirm the device stays enumerated as **`PID_0D09`** (`Revelator`, `Stream Mix A`, `Stream Mix B`).
   - Windows Device Manager showing `Revelator (unsupported mode)` for `PID_0D09&MI_00` is **expected and harmless**.

5. **Real-device Android verification (mandatory before declaring fixed):**
   - Unplug the Revelator from Windows and plug it directly into the Android phone.
   - Play audio through the 3.5mm monitoring headphones and record a 10-second clip in any recorder app.
   - Confirm both audible headphone playback and non-silent recorded waveform.

6. **Warn the user about port scope:** Disarming removes `RestartDeviceRequest` only for the specific Windows USB port instance(s) currently registered. Plugging a Multi-Mode Revelator into a **different USB port**, another Windows PC with PreSonus drivers, or reinstalling Universal Control will recreate the trap and revert the mic back to Single Mode.

### Safety Boundaries (Never Violate)
- **Never** send DFU commands (`TUSBAUDIO_StartDfu*`) or touch `ucdaemon` (localhost TCP 51567 UCNET firmware endpoints).
- **Never** send `bRequest=0x42` to any device whose USB `VID` is not `0x194F` or whose `PID` is not in the Revelator family (`revelator_mode.py` enforces this check automatically).
- On physical hardware, `Revelator` (`0x0D08 <-> 0x0D09`) is verified end-to-end; `Revelator Dynamic` (`0x0D0A/0x0D0B`), `io24` (`0x0422/0x0423`), and `io44` (`0x0424/0x0425`) share the identical `paedspusb.inf` rule (`RequestCode=66`) but should be verified carefully if tested on those models.

---

## Workflow 2: Fat Channel Vocal Tuning & Acoustic Analysis

### Signal Flow Rules (Hardware-Verified)
- **What Android/phone apps record:** Raw `Mic 1/2` after the preamp and Fat Channel (if `Fat Channel on USB Stream Outputs — Ch 1` is enabled in Universal Control Settings). Mixer faders, `Blend`, and mixer `Reverb` do **not** enter the phone recording; **only Fat Channel `Voice` delay effects** enter the USB recording stream.
- **Zero-latency headphone monitoring:** Runs entirely inside the Revelator DSP (`Main Mix -> Blend -> Phones`). `Blend` ranges from `-1.0` (mic only) to `+1.0` (playback only, zero mic). If the singer cannot hear themselves in headphones, check `Blend` first.
- **Gain staging vs clipping:** Analog clipping comes from preamp gain being too high (hold the Monitor knob until it turns green to adjust preamp gain). Digital app gain cannot recover clipped ADC peaks. Keep preamp gain conservative (e.g., `12–14 dB` for close vocal singing) and build loudness digitally inside Fat Channel using **Compressor makeup gain + Limiter (`-1.0` to `-1.5 dB`)**.
- **Echo vs natural room ambience:** Delay times `> 35–40 ms` read as distinct rhythmic echoes. For subtle room ambience, keep delay `<= 25–30 ms` with low mix (`<= 0.25`), or turn Voice FX off for clean natural vocals.

### Included Onboard Presets (`presets/*.channel`)

| Preset | Best For | Key Parameters |
|---|---|---|
| `Natural Voice.channel` | Natural singing / speaking (close to phone-mic clarity without mud) | HPF 80 Hz; EQ 220 Hz -6 dB, 3.5 kHz +5 dB; Comp -30 dB 2:1 (+15 dB); Limiter -1 dB; Voice FX off |
| `Pop Studio.channel` | Bright pop vocals with subtle room width | EQ 350 Hz -5 dB, 4 kHz +5 dB, 10 kHz +6 dB; Comp -26 dB 2.5:1 (+11 dB); 25 ms reflection (mix 0.25) |
| `Ballad.channel` | Warm slow vocals with soft tail | HPF 100 Hz; EQ 300 Hz -3.5 dB, 3.5 kHz +3 dB, 10 kHz +4.5 dB; Echo ~315 ms |
| `KTV Echo.channel` | Karaoke-style audible echo | Echo ~270 ms, higher mix |
| `Raw Voice.channel` | A/B comparison baseline | HPF only, flat EQ/comp |

Import presets via Universal Control by copying `.channel` files into `~/Documents/PreSonus/Revelator Mic/Fat/` (macOS) or `Documents\PreSonus\Revelator Mic\Fat\` (Windows), then loading into one of the 8 onboard preset slots and assigning it to one of the 4 hardware color buttons. Always verify `Fat Channel on USB Stream Outputs — Ch 1` is ON before disconnecting from PC/Mac.

### Quantitative Acoustic Analysis Scripts (`scripts/`)

Run Python scripts with `scripts/py <script.py> ...` (uses `uv` ephemeral deps) or any Python environment with `numpy`, `scipy`, `soundfile`, `librosa`, and `ffmpeg`:

| Script | Purpose |
|---|---|
| `scripts/revelator_mode.py` | Windows Single ↔ Multi Mode diagnostics, `RestartDeviceRequest` disarmer, and switcher (stdlib only) |
| `scripts/analyze.py <audio>` | Vocal audit: noise floor, dynamic range, pitch range, spectral balance, sibilance, plosives |
| `scripts/rec_report.py <a.wav> ...` | Clipped sample count, consecutive clipping runs, plosives, high-frequency clicks, RMS percentiles |
| `scripts/voice_compare.py <a> <b>` | Spectral band deltas, harmonic-to-noise ratio (HNR), 4–8 kHz flatness, voiced dynamics |
| `scripts/cancel.py <a> <b>` | Aligns and subtracts two takes with the same backing track to isolate true vocal level |
| `scripts/ir.py <click.wav>` | Impulse response analyzer (echo peak intervals, RT20/RT30 decay) |
| `scripts/burst.sh <name> <amp>` | macOS reproducible 2s pink-noise speaker-to-mic level test (`OUT=./revelator-tests`) |
| `scripts/click.sh <name>` | macOS 3x 15ms click impulse response capture (`OUT=./revelator-tests`) |
| `scripts/spkvol.swift` | macOS built-in speaker volume reader/setter (always restore user's original volume after testing) |
