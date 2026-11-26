#!/usr/bin/env python3
"""
Pure-program (zero-AI, zero-API-fee) vocal analyzer & PreSonus Revelator Fat Channel
`.channel` preset generator.

Analyzes a vocal recording (WAV natively via stdlib `wave` + `numpy`, or M4A/MP3/FLAC
if `ffmpeg` is installed) and outputs:
  1. Concrete acoustic diagnosis (clipping, noise floor, voiced RMS, dynamics, plosives,
     4-band tonal balance).
  2. Hardware gain / monitoring guidance when analog clipping is detected.
  3. A ready-to-import Universal Control Fat Channel `.channel` JSON preset, optionally
     installed straight into `Documents/PreSonus/Revelator Mic/Fat/`.

Two tuning modes:
  - Standalone mode: targets an empirically balanced singing/speaking curve (`--style`).
  - Reference-matching mode (`--ref <reference_vocal>`): measures spectral delta between
    your Revelator take and a dry reference recording (e.g., a phone mic take whose tone
    you prefer) and generates damped, safe EQ & dynamics corrections.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

try:
    import numpy as np
except ImportError:
    print(
        "ERROR: `numpy` is required for DSP analysis.\n"
        "Install with: pip install numpy",
        file=sys.stderr,
    )
    raise SystemExit(2)


# Empirically calibrated vocal reference curve (dB relative to 1.2-2.5 kHz midrange)
# Based on real-world Revelator vs clean mobile-mic vocal comparisons.
DEFAULT_TARGET_BANDS_DB = {
    "low_rumble_80_150": -6.0,
    "low_mid_150_350": -1.5,
    "presence_2500_5000": -8.0,
    "air_8000_15000": -18.0,
}

STYLE_PROFILES: dict[str, dict[str, Any]] = {
    "natural": {
        "target_rms_db": -20.0,
        "comp_ratio": 2.0,
        "comp_threshold": -30.0,
        "presence_bias_db": 0.0,
        "air_bias_db": 0.0,
        "voicefx": {"on": 0, "time": 0.022, "feedback": 0.7, "mix": 0.15},
    },
    "pop": {
        "target_rms_db": -18.5,
        "comp_ratio": 2.5,
        "comp_threshold": -26.0,
        "presence_bias_db": 1.5,
        "air_bias_db": 2.5,
        "voicefx": {"on": 1, "time": 0.025, "feedback": 1.0, "mix": 0.25},
    },
    "ballad": {
        "target_rms_db": -19.5,
        "comp_ratio": 2.2,
        "comp_threshold": -28.0,
        "presence_bias_db": 0.5,
        "air_bias_db": 1.5,
        "voicefx": {"on": 1, "time": 0.25, "feedback": 0.52, "mix": 0.14},
    },
    "ktv": {
        "target_rms_db": -18.5,
        "comp_ratio": 2.5,
        "comp_threshold": -26.0,
        "presence_bias_db": 1.0,
        "air_bias_db": 1.5,
        "voicefx": {"on": 1, "time": 0.27, "feedback": 0.55, "mix": 0.24},
    },
}


@dataclass
class AudioMetrics:
    sample_rate: int
    duration_s: float
    peak_dbfs: float
    clipped_samples: int
    clipping_runs: int
    voiced_rms_p50_dbfs: float
    voiced_rms_p95_dbfs: float
    noise_floor_dbfs: float
    dynamic_range_db: float
    plosive_events: int
    band_rel_db: dict[str, float]


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def round_half(val: float) -> float:
    return round(val * 2.0) / 2.0


def load_wav_pcm(path: str) -> tuple[np.ndarray, int]:
    """Read uncompressed 16/24/32-bit PCM WAV using Python stdlib + numpy."""
    with wave.open(path, "rb") as wf:
        nch = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        sr = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if sampwidth == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sampwidth == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        ints = (
            b[:, 0].astype(np.int32)
            | (b[:, 1].astype(np.int32) << 8)
            | (b[:, 2].astype(np.int32) << 16)
        )
        ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
        data = ints.astype(np.float32) / 8388608.0
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sampwidth} bytes")

    if nch > 1:
        data = data.reshape(-1, nch).mean(axis=1)
    return data.astype(np.float32), sr


def load_audio(path: str, target_sr: int = 48000) -> tuple[np.ndarray, int]:
    """Load WAV natively, or decode M4A/MP3/FLAC/etc. via ffmpeg."""
    ext = Path(path).suffix.lower()
    if ext == ".wav":
        try:
            return load_wav_pcm(path)
        except Exception:
            # Fall back to ffmpeg for IEEE-float WAV or compressed WAV containers
            pass

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            f"Cannot decode '{path}' without `ffmpeg` in PATH. "
            "Either pass an uncompressed PCM `.wav` file, or install ffmpeg."
        )

    proc = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            path,
            "-ac",
            "1",
            "-ar",
            str(target_sr),
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    data = np.frombuffer(proc.stdout, dtype="<f4").copy()
    return data, target_sr


def analyze_signal(x: np.ndarray, sr: int) -> AudioMetrics:
    if x.size == 0:
        raise ValueError("Audio signal is empty.")

    duration_s = float(x.size) / float(sr)
    abs_x = np.abs(x)
    peak = float(np.max(abs_x))
    peak_dbfs = 20.0 * math.log10(max(peak, 1e-12))

    # Clipping detection (samples hitting >= 0.999 full scale)
    clipped_mask = abs_x >= 0.999
    clipped_samples = int(np.sum(clipped_mask))
    clipping_runs = 0
    if clipped_samples > 0:
        padded = np.concatenate(([0], clipped_mask.astype(np.int8), [0]))
        diffs = np.diff(padded)
        starts = np.where(diffs == 1)[0]
        ends = np.where(diffs == -1)[0]
        clipping_runs = int(np.sum((ends - starts) >= 3))

    # Frame-based energy (50ms window, 25ms hop)
    win = max(256, int(0.05 * sr))
    hop = max(128, win // 2)
    n_frames = max(1, 1 + (x.size - win) // hop)
    if x.size < win:
        frames = np.pad(x, (0, win - x.size))[None, :]
    else:
        idx = np.arange(win)[None, :] + (np.arange(n_frames) * hop)[:, None]
        frames = x[idx]

    rms_lin = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    rms_db = 20.0 * np.log10(rms_lin)

    noise_floor_dbfs = float(np.percentile(rms_db, 10))
    max_frame_db = float(np.max(rms_db))

    # Voiced/active frames: within 28 dB of loudest frame and above -55 dBFS
    active_thresh = max(max_frame_db - 28.0, noise_floor_dbfs + 8.0, -55.0)
    active = rms_db >= active_thresh
    if not np.any(active):
        active = np.ones_like(rms_db, dtype=bool)

    voiced_rms_p50 = float(np.percentile(rms_db[active], 50))
    voiced_rms_p95 = float(np.percentile(rms_db[active], 95))
    voiced_rms_p10 = float(np.percentile(rms_db[active], 10))
    dynamic_range_db = max(0.0, voiced_rms_p95 - voiced_rms_p10)

    # STFT spectrum on active frames using Hann window (4096-point FFT)
    n_fft = 4096
    hann = np.hanning(n_fft).astype(np.float32)
    fft_hop = 1024
    if x.size < n_fft:
        fft_frames = np.pad(x, (0, n_fft - x.size))[None, :]
    else:
        nf = 1 + (x.size - n_fft) // fft_hop
        fidx = np.arange(n_fft)[None, :] + (np.arange(nf) * fft_hop)[:, None]
        fft_frames = x[fidx]

    spec = np.abs(np.fft.rfft(fft_frames * hann[None, :], axis=1)) ** 2
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    frame_energy_db = 10.0 * np.log10(np.sum(spec, axis=1) + 1e-12)
    spec_active = frame_energy_db >= (float(np.max(frame_energy_db)) - 30.0)
    if not np.any(spec_active):
        spec_active = np.ones_like(frame_energy_db, dtype=bool)

    mean_spec = np.mean(spec[spec_active], axis=0)

    def band_mean(f_lo: float, f_hi: float) -> float:
        mask = (freqs >= f_lo) & (freqs < f_hi)
        if not np.any(mask):
            return 1e-12
        return float(np.mean(mean_spec[mask])) + 1e-12

    ref_mid = band_mean(1200.0, 2500.0)
    band_rel_db = {
        "low_rumble_80_150": 10.0 * math.log10(band_mean(80.0, 150.0) / ref_mid),
        "low_mid_150_350": 10.0 * math.log10(band_mean(150.0, 350.0) / ref_mid),
        "presence_2500_5000": 10.0 * math.log10(band_mean(2500.0, 5000.0) / ref_mid),
        "air_8000_15000": 10.0 * math.log10(band_mean(8000.0, 15000.0) / ref_mid),
    }

    # Plosive detector: frames where sub-120 Hz energy exceeds 300-2500 Hz energy by > 12 dB
    sub_mask = (freqs >= 30.0) & (freqs < 120.0)
    mid_mask = (freqs >= 300.0) & (freqs < 2500.0)
    sub_e = np.sum(spec[:, sub_mask], axis=1) + 1e-12
    mid_e = np.sum(spec[:, mid_mask], axis=1) + 1e-12
    ratio_db = 10.0 * np.log10(sub_e / mid_e)
    plosive_frames = np.where((ratio_db > 12.0) & spec_active)[0]
    plosive_events = 0
    last_pf = -100
    min_gap = max(1, int(0.25 * sr / fft_hop))
    for pf in plosive_frames:
        if pf - last_pf >= min_gap:
            plosive_events += 1
        last_pf = int(pf)

    return AudioMetrics(
        sample_rate=sr,
        duration_s=round(duration_s, 2),
        peak_dbfs=round(peak_dbfs, 2),
        clipped_samples=clipped_samples,
        clipping_runs=clipping_runs,
        voiced_rms_p50_dbfs=round(voiced_rms_p50, 2),
        voiced_rms_p95_dbfs=round(voiced_rms_p95, 2),
        noise_floor_dbfs=round(noise_floor_dbfs, 2),
        dynamic_range_db=round(dynamic_range_db, 2),
        plosive_events=plosive_events,
        band_rel_db={k: round(v, 2) for k, v in band_rel_db.items()},
    )


def generate_preset(
    metrics: AudioMetrics,
    preset_name: str = "Auto Tuned",
    style: str = "natural",
    ref_metrics: Optional[AudioMetrics] = None,
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    """
    Compute deterministic, hardware-safe Revelator Fat Channel `.channel` JSON
    from measured vocal metrics (and optional reference vocal metrics).
    """
    if style not in STYLE_PROFILES:
        raise ValueError(f"Unknown style: {style!r}")
    prof = STYLE_PROFILES[style]

    target_bands = ref_metrics.band_rel_db if ref_metrics is not None else DEFAULT_TARGET_BANDS_DB
    damping = 0.75  # Conservative damping avoids harsh EQ over-correction

    warnings: list[str] = []
    notes: list[str] = []

    # 1. Analog clipping check (cannot be fixed digitally)
    if metrics.clipped_samples > 20 or metrics.clipping_runs > 0:
        warnings.append(
            f"ANALOG CLIPPING DETECTED ({metrics.clipped_samples} clipped samples, "
            f"{metrics.clipping_runs} runs, peak {metrics.peak_dbfs:.1f} dBFS). "
            "Lower Revelator hardware preamp gain (hold Monitor knob until green) by 3-6 dB."
        )

    # 2. HPF selection based on plosives and low-end rumble
    rumble_excess = metrics.band_rel_db["low_rumble_80_150"] - target_bands["low_rumble_80_150"]
    if metrics.plosive_events >= 4 or rumble_excess > 6.0:
        hpf_hz = 100.0
        notes.append(f"Raised HPF to 100 Hz (plosives={metrics.plosive_events}, 80-150Hz excess={rumble_excess:+.1f} dB).")
    else:
        hpf_hz = 80.0

    # 3. 4-band EQ deltas (clamped safely to [-6.0, +6.0] dB)
    mud_delta = metrics.band_rel_db["low_mid_150_350"] - target_bands["low_mid_150_350"]
    eq2_gain = round_half(clamp(-mud_delta * damping, -6.0, 2.0))

    pres_delta = metrics.band_rel_db["presence_2500_5000"] - target_bands["presence_2500_5000"]
    eq3_gain = round_half(clamp(-pres_delta * damping + prof["presence_bias_db"], -4.0, 6.0))

    air_delta = metrics.band_rel_db["air_8000_15000"] - target_bands["air_8000_15000"]
    eq4_gain = round_half(clamp(-air_delta * damping * 0.6 + prof["air_bias_db"], -4.0, 6.0))

    # 4. Compressor & digital makeup gain (safe loudness without analog clipping)
    target_rms = prof["target_rms_db"]
    comp_threshold = float(prof["comp_threshold"])
    comp_ratio = float(prof["comp_ratio"])
    if metrics.dynamic_range_db > 24.0:
        comp_ratio = round_half(min(3.0, comp_ratio + 0.5))
        notes.append(f"Wide vocal dynamics ({metrics.dynamic_range_db:.1f} dB) -> comp ratio {comp_ratio:.1f}:1.")

    # Estimate gain reduction at p50 voiced level so makeup gain hits target RMS accurately
    over_thresh = max(0.0, metrics.voiced_rms_p50_dbfs - comp_threshold)
    est_gr = over_thresh * (1.0 - 1.0 / comp_ratio)
    raw_makeup = (target_rms - metrics.voiced_rms_p50_dbfs) + est_gr
    comp_gain = round_half(clamp(raw_makeup, 0.0, 18.0))

    # 5. Noise gate (only enable if ambient room floor is noticeably noisy)
    gate_on = 1 if metrics.noise_floor_dbfs > -48.0 else 0
    gate_thresh = round_half(clamp(metrics.noise_floor_dbfs + 4.0, -60.0, -35.0))
    if gate_on:
        notes.append(f"High room noise floor ({metrics.noise_floor_dbfs:.1f} dBFS) -> enabled gentle expander/gate at {gate_thresh:.1f} dB.")

    vfx = prof["voicefx"]
    preset: dict[str, Any] = {
        "preset_name": preset_name,
        "opt": {"swapcompeq": 0},
        "filter": {"hpf": hpf_hz},
        "gate": {
            "on": gate_on,
            "keylisten": 0,
            "expander": 1,
            "keyfilter": 480.0,
            "threshold": gate_thresh,
            "range": -18.0 if gate_on else -60.0,
            "attack": 0.014,
            "release": 0.57,
        },
        "limit": {
            "limiteron": 1,
            "threshold": -1.0,
        },
        "voicefxopt": {" ": " "},
        "eq": {
            "__classid": "{A0A8A068-14F0-4B04-BB6F-AF8329D0E8EE}",
            "eqallon": 1,
            "eqgain1": 0.0,
            "eqq1": 1.0,
            "eqfreq1": 100.0,
            "eqbandon1": 1,
            "eqbandop1": 1,
            "eqgain2": eq2_gain,
            "eqq2": 1.0,
            "eqfreq2": 220.0 if style == "natural" else 300.0,
            "eqbandon2": 1,
            "eqgain3": eq3_gain,
            "eqq3": 0.8,
            "eqfreq3": 3500.0,
            "eqbandon3": 1,
            "eqgain4": eq4_gain,
            "eqq4": 1.0,
            "eqfreq4": 10000.0,
            "eqbandon4": 1,
            "eqbandop4": 1,
        },
        "voicefx": {
            "__classid": "{98A527BA-2D6E-4B35-BB26-251EC081A067}",
            "on": int(vfx["on"]),
            "time": float(vfx["time"]),
            "feedback": float(vfx["feedback"]),
            "mix": float(vfx["mix"]),
        },
        "comp": {
            "__classid": "{870D04F7-212E-4F9C-ADBB-39A97216433F}",
            "on": 1,
            "softknee": 1,
            "automode": 0,
            "threshold": comp_threshold,
            "ratio": comp_ratio,
            "attack": 0.02,
            "release": 0.15,
            "gain": comp_gain,
            "keyfilter": 40.0,
            "keylisten": 0,
        },
    }

    summary = {
        "style": style,
        "reference_matched": ref_metrics is not None,
        "hpf_hz": hpf_hz,
        "eq_low_mid_db": eq2_gain,
        "eq_presence_db": eq3_gain,
        "eq_air_db": eq4_gain,
        "comp_threshold_db": comp_threshold,
        "comp_ratio": comp_ratio,
        "comp_makeup_db": comp_gain,
        "limiter_db": -1.0,
        "gate_on": bool(gate_on),
        "voicefx_on": bool(vfx["on"]),
        "notes": notes,
    }
    return preset, warnings, summary


def default_uc_preset_dir() -> Path:
    return Path.home() / "Documents" / "PreSonus" / "Revelator Mic" / "Fat"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="auto_tune.py",
        description="Zero-AI vocal analyzer & PreSonus Revelator Fat Channel `.channel` preset generator.",
    )
    p.add_argument("input", help="Path to your vocal recording (.wav natively; .m4a/.mp3 with ffmpeg)")
    p.add_argument(
        "--ref",
        default=None,
        help="Optional dry reference vocal recording (e.g., a phone mic take) to match tonal balance",
    )
    p.add_argument(
        "--style",
        choices=sorted(STYLE_PROFILES.keys()),
        default="natural",
        help="Target vocal style (default: natural)",
    )
    p.add_argument("--name", default="Auto Tuned", help="Preset name inside the .channel file")
    p.add_argument("--out", default=None, help="Output .channel file path (default: ./<name>.channel)")
    p.add_argument(
        "--install",
        action="store_true",
        help="Also copy the generated preset into Documents/PreSonus/Revelator Mic/Fat/",
    )
    p.add_argument("--json", action="store_true", help="Print machine-readable JSON summary")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    x, sr = load_audio(args.input)
    metrics = analyze_signal(x, sr)

    ref_metrics = None
    if args.ref:
        rx, rsr = load_audio(args.ref)
        ref_metrics = analyze_signal(rx, rsr)

    preset, warnings, summary = generate_preset(
        metrics,
        preset_name=args.name,
        style=args.style,
        ref_metrics=ref_metrics,
    )

    out_path = Path(args.out) if args.out else Path(f"{args.name}.channel")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(preset, f, indent="\t", ensure_ascii=False)

    installed_path = None
    if args.install:
        uc_dir = default_uc_preset_dir()
        uc_dir.mkdir(parents=True, exist_ok=True)
        installed_path = uc_dir / f"{args.name}.channel"
        shutil.copy2(out_path, installed_path)

    if args.json:
        print(
            json.dumps(
                {
                    "input": args.input,
                    "ref": args.ref,
                    "metrics": asdict(metrics),
                    "ref_metrics": asdict(ref_metrics) if ref_metrics else None,
                    "preset_summary": summary,
                    "warnings": warnings,
                    "output_file": str(out_path),
                    "installed_file": str(installed_path) if installed_path else None,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    print("=== PreSonus Revelator Pure-Program Vocal Auto-Tuner ===")
    print(f"Input          : {args.input} ({metrics.duration_s:.1f}s @ {metrics.sample_rate} Hz)")
    if args.ref:
        print(f"Reference      : {args.ref} (tonal matching enabled)")
    print(f"Peak / Clip    : {metrics.peak_dbfs:.1f} dBFS | clipped={metrics.clipped_samples} (runs={metrics.clipping_runs})")
    print(f"Voiced RMS     : p50={metrics.voiced_rms_p50_dbfs:.1f} dBFS | p95={metrics.voiced_rms_p95_dbfs:.1f} dBFS | dynamics={metrics.dynamic_range_db:.1f} dB")
    print(f"Noise Floor    : {metrics.noise_floor_dbfs:.1f} dBFS | plosives={metrics.plosive_events}")
    print(
        "Spectral (vs 1.2-2.5k): "
        f"80-150Hz {metrics.band_rel_db['low_rumble_80_150']:+.1f} | "
        f"150-350Hz {metrics.band_rel_db['low_mid_150_350']:+.1f} | "
        f"2.5-5k {metrics.band_rel_db['presence_2500_5000']:+.1f} | "
        f"8-15k {metrics.band_rel_db['air_8000_15000']:+.1f} dB"
    )
    print("\n=== Generated Fat Channel Preset ===")
    print(f"Style / Name   : {args.style} / {args.name}")
    print(
        f"HPF & EQ       : HPF {summary['hpf_hz']:.0f} Hz | "
        f"Low-Mid {summary['eq_low_mid_db']:+.1f} dB | "
        f"Presence {summary['eq_presence_db']:+.1f} dB | "
        f"Air {summary['eq_air_db']:+.1f} dB"
    )
    print(
        f"Dynamics       : Comp {summary['comp_threshold_db']:.0f} dB @ {summary['comp_ratio']:.1f}:1 "
        f"(+{summary['comp_makeup_db']:.1f} dB) | Limiter {summary['limiter_db']:.1f} dB | "
        f"Gate={'ON' if summary['gate_on'] else 'OFF'} | VoiceFX={'ON' if summary['voicefx_on'] else 'OFF'}"
    )
    print(f"Saved Preset   : {out_path.resolve()}")
    if installed_path:
        print(f"Installed To   : {installed_path}")
    else:
        print(f"Next Step      : Copy to '{default_uc_preset_dir()}' (or re-run with --install) and load in Universal Control.")

    for note in summary["notes"]:
        print(f"  - {note}")
    if warnings:
        print("\nHARDWARE WARNINGS:")
        for w in warnings:
            print(f"  ! {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
