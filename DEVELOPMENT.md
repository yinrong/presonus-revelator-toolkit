# Development & AI-Assisted Exploration Guide

**Core architecture principle: end users run 100% deterministic, zero-AI local programs (`$0` runtime cost); AI agent skills are reserved strictly for developers exploring unsolved hardware, driver, Android HAL, or acoustic problems—and every newly solved problem should graduate into pure local code.**

[End-User README](./README.md) · [中文用户文档](./README.zh-CN.md) · [Technical Root Cause](./docs/TECHNICAL_ROOT_CAUSE.md) · [AI Exploration Skill (`SKILL.md`)](./skills/revelator-toolkit/SKILL.md)

---

## 1. Two-Layer Repository Architecture

| Layer | Audience | Runtime Cost | Where It Lives |
|---|---|---|---|
| **User Layer (Pure Program)** | Revelator owners fixing Android audio or tuning vocals | **`$0` (100% local, deterministic, zero LLM)** | `fix_android_mode.bat`, `scripts/revelator_mode.py`, `scripts/auto_tune.py`, `scripts/*.py`, `presets/*.channel`, `README.md`, `README.zh-CN.md` |
| **Exploration & Dev Layer (AI Skill + Deep Docs)** | Developers/contributors investigating new devices, OS versions, driver regressions, or novel acoustic problems | Uses your AI coding agent only while exploring a new issue | `skills/revelator-toolkit/SKILL.md`, `docs/TECHNICAL_ROOT_CAUSE.md`, `tests/` |

### The Graduation Rule ("Explore with AI → Ship Pure Code")

When you encounter a brand-new problem (for example: verifying `Revelator Dynamic` / `io24` / `io44`, a new Windows Universal Control driver release changing `paedspusb.inf`, or an Android OEM USB Audio HAL quirk):

1. **Explore with the AI Skill:** Load `skills/revelator-toolkit/SKILL.md` in Claude Code, OpenAI Codex, or Antigravity so the agent follows our probe-first diagnostic discipline (ADB USB/HAL capture, Windows PnP/INF inspection, quantitative acoustic measurements) without repeating dead ends or touching unsafe firmware endpoints.
2. **Verify on real physical hardware:** Never treat passing offline unit tests as proof that a hardware/driver fix works end-to-end. Capture real device output (USB re-enumeration PID, clean Android audio capture, real recorded waveform).
3. **Distill into pure local code:** Turn the proven fix into deterministic code in `scripts/` + offline unit tests in `tests/` + clear user instructions in `README.md` / `README.zh-CN.md`. End users then run the fix locally forever at **`$0` AI cost**.

---

## 2. Running Tests & Local Development

### Unit Tests (Offline, Fast)

Requires Python 3.9+ and `numpy`:

```bash
python -m unittest discover -s tests -v
```

What the unit suite covers:
- `tests/test_revelator_mode.py`: VID/PID parsing, Revelator-family PID classification, `RestartDeviceRequest` registry scanning, exact `TUSBAUDIO_ClassVendorRequestOut` argument layout (`bRequest=0x42`), safety refusal on non-Revelator devices, dry-run & JSON backup flows.
- `tests/test_auto_tune.py`: WAV PCM round-trip, mud/presence spectral EQ generation, analog clipping detection & hardware gain warning, reference-vocal tonal matching, style profiles (`natural`/`pop`/`ballad`/`ktv`), and safe parameter clamping.

### Live Read-Only Windows Diagnostic

```powershell
python scripts/revelator_mode.py diag --json
```

---

## 3. Installing the AI Exploration Skill

Use this **only** when developing, debugging new hardware/OS combos, or conducting iterative vocal R&D with an AI coding assistant:

```bash
# Claude Code (global)
ln -s "$(pwd)/skills/revelator-toolkit" ~/.claude/skills/revelator-toolkit

# Or project-local (Claude Code / Codex / Antigravity)
cp -r skills/revelator-toolkit /path/to/workspace/.claude/skills/
```

The skill instructs the agent to:
- Always run the zero-cost pure programs (`revelator_mode.py diag --json`, `auto_tune.py --json`, `rec_report.py`) first before spending tokens on reasoning.
- Probe real device logs (Android `dumpsys usb`, `dumpsys audio`, `logcat` HAL/DSP errors; Windows `paedspusb.inf`, `Microsoft-Windows-Kernel-PnP/Configuration`) instead of guessing.
- Obey strict hardware safety rails (never call `TUSBAUDIO_StartDfu*` or touch `ucdaemon` TCP `51567` firmware endpoints).

---

## 4. Hardware Safety Rules & Verification Matrix

### Never Violate These Safety Boundaries
- **Never** send DFU commands or interact with `ucdaemon` (`127.0.0.1:51567` UCNET protocol), which exposes firmware flashing calls.
- **Never** send `bRequest=0x42` to any USB device unless `VID == 0x194F` and `PID` is explicitly listed in `KNOWN_PIDS`.
- **Never** claim a model is hardware-verified unless you observed real USB re-enumeration and real-device Android playback + capture.

### Current Physical Hardware Verification Matrix

| Model | Single Mode PID | Multi Mode PID | `paedspusb.inf` Rule | Physical Hardware Verified? |
|---|---|---|---|---|
| PreSonus Revelator | `0x0D08` (`0x0D01`) | `0x0D09` (`0x0D03`) | `RestartDeviceRequest` (`RequestCode=66`) | **Yes** (Windows 11 + Android 17) |
| PreSonus Revelator Dynamic | `0x0D0A` (`0x0D04`) | `0x0D0B` (`0x0D06`) | `RestartDeviceRequest` (`RequestCode=66`) | Pending community report |
| PreSonus Revelator io24 | `0x0422` (`0x0407`) | `0x0423` (`0x0406`) | `RestartDeviceRequest` (`RequestCode=66`) | Pending community report |
| PreSonus Revelator io44 | `0x0424` (`0x041A`) | `0x0425` (`0x0419`) | `RestartDeviceRequest` (`RequestCode=66`) | Pending community report |

### How to Contribute a Hardware Verification Report

If you own a **Revelator Dynamic**, **io24**, or **io44**:
1. Run `python scripts/revelator_mode.py diag --json` on Windows.
2. Follow the disarm + switch flow and test playback + recording on Android.
3. Open a GitHub Issue or PR with your OS version, Universal Control version, `diag --json` output (redact your device serial if desired), and Android test outcome so we can flip `verified=True` in `scripts/revelator_mode.py`.
