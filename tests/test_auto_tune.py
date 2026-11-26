import json
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import auto_tune as at  # noqa: E402


def write_pcm16_wav(path: str, x: np.ndarray, sr: int = 48000) -> None:
    clipped = np.clip(x, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def synth_voice(
    sr: int = 48000,
    dur_s: float = 2.0,
    amp_220: float = 0.05,
    amp_1800: float = 0.04,
    amp_3500: float = 0.01,
    amp_10000: float = 0.005,
) -> np.ndarray:
    t = np.arange(int(sr * dur_s), dtype=np.float32) / float(sr)
    sig = (
        amp_220 * np.sin(2.0 * np.pi * 220.0 * t)
        + amp_1800 * np.sin(2.0 * np.pi * 1800.0 * t)
        + amp_3500 * np.sin(2.0 * np.pi * 3500.0 * t)
        + amp_10000 * np.sin(2.0 * np.pi * 10000.0 * t)
    )
    # Add short quiet segment at the start so noise floor is well-separated
    sig[: int(0.3 * sr)] = 1e-4 * np.sin(2.0 * np.pi * 60.0 * t[: int(0.3 * sr)])
    return sig.astype(np.float32)


class AutoTuneTests(unittest.TestCase):
    def test_wav_roundtrip_and_cli_generates_valid_channel_json(self):
        sig = synth_voice(amp_220=0.06, amp_1800=0.02, amp_3500=0.003)
        with tempfile.TemporaryDirectory() as td:
            wav_path = os.path.join(td, "vocal.wav")
            out_path = os.path.join(td, "MyVoice.channel")
            write_pcm16_wav(wav_path, sig)

            rc = at.main([wav_path, "--style", "natural", "--name", "MyVoice", "--out", out_path])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(out_path))

            with open(out_path, "r", encoding="utf-8") as f:
                preset = json.load(f)

            self.assertEqual(preset["preset_name"], "MyVoice")
            self.assertEqual(preset["limit"]["limiteron"], 1)
            self.assertEqual(preset["limit"]["threshold"], -1.0)
            # Muddy low-mid (220Hz loud) should produce a negative EQ2 cut
            self.assertLess(preset["eq"]["eqgain2"], 0.0)
            # Dark presence (3.5kHz weak) should produce a positive EQ3 boost
            self.assertGreater(preset["eq"]["eqgain3"], 0.0)
            # Safe bounds check
            self.assertGreaterEqual(preset["eq"]["eqgain2"], -6.0)
            self.assertLessEqual(preset["eq"]["eqgain3"], 6.0)
            self.assertGreaterEqual(preset["comp"]["gain"], 0.0)
            self.assertLessEqual(preset["comp"]["gain"], 18.0)

    def test_clipping_triggers_hardware_preamp_warning(self):
        sr = 48000
        t = np.arange(sr, dtype=np.float32) / float(sr)
        clipped = np.clip(2.0 * np.sin(2.0 * np.pi * 440.0 * t), -1.0, 1.0)
        metrics = at.analyze_signal(clipped, sr)
        self.assertGreater(metrics.clipped_samples, 100)
        self.assertGreater(metrics.clipping_runs, 0)

        _preset, warnings, _summary = at.generate_preset(metrics, style="natural")
        self.assertTrue(any("ANALOG CLIPPING DETECTED" in w for w in warnings))

    def test_reference_matching_reduces_excess_mud_and_boosts_missing_presence(self):
        mic_sig = synth_voice(amp_220=0.08, amp_1800=0.03, amp_3500=0.004)
        ref_sig = synth_voice(amp_220=0.02, amp_1800=0.03, amp_3500=0.025)

        m_mic = at.analyze_signal(mic_sig, 48000)
        m_ref = at.analyze_signal(ref_sig, 48000)
        preset, _warnings, summary = at.generate_preset(m_mic, style="natural", ref_metrics=m_ref)

        self.assertTrue(summary["reference_matched"])
        self.assertLess(preset["eq"]["eqgain2"], -2.0)
        self.assertGreater(preset["eq"]["eqgain3"], 2.0)
        self.assertEqual(preset["voicefx"]["on"], 0)

    def test_pop_style_enables_short_reflection_voicefx(self):
        sig = synth_voice()
        metrics = at.analyze_signal(sig, 48000)
        preset, _warnings, summary = at.generate_preset(metrics, style="pop")
        self.assertTrue(summary["voicefx_on"])
        self.assertEqual(preset["voicefx"]["on"], 1)
        self.assertLessEqual(preset["voicefx"]["time"], 0.035)


if __name__ == "__main__":
    unittest.main()
