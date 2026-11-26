# Technical Root Cause: Why PreSonus Revelator Stops Working on Android After Being Plugged Into Windows

**Short answer:** Plugging a PreSonus Revelator into a Windows PC with Universal Control installed silently overwrites its onboard USB audio mode from **Multi Mode** (2-channel stereo streams, required by Android) to **Single Mode** (6-channel stream, Windows-only), because the Windows kernel driver `PaeDSPUSB.sys` automatically fires a USB vendor reset command within one second of connection.

---

## 1. The False-Exclusion Trap

Many users hit the exact same misleading troubleshooting loop:

1. The microphone + headphone monitoring jack works fine on a Windows PC.
2. Generic Android apps (karaoke apps, voice recorders, camera apps) all fail to record or play audio through the Revelator.
3. Conclusion: *"The mic works on PC, so the mic is fine; it must be a broken Android phone setting."*

**Why that reasoning fails:** PreSonus Revelator stores its USB Audio Class mode (**Single Mode** vs **Multi Mode**) in onboard non-volatile flash memory. The exact mode that Windows requires (`PID_0D08`, Single Mode) is the exact mode that crashes Android USB audio backends.

---

## 2. USB Descriptors: Single Mode vs Multi Mode

| Property | Single Mode (Windows) | Multi Mode (Android / iOS / macOS) |
|---|---|---|
| USB Vendor / Product ID (Revelator) | `VID_194F&PID_0D08` | `VID_194F&PID_0D09` |
| Audio Interface Topology | 1 capture + 1 playback interface, **6 channels (`bNrChannels=6`)** at 48 kHz / 24-in-32-bit | 3 independent **2-channel stereo (`bNrChannels=2`)** UAC2 interfaces (`Revelator`, `Stream Mix A`, `Stream Mix B`) |
| Windows Universal Control | Supported (default) | Hidden from Windows UI; Device Manager shows **`Revelator (unsupported mode)`** |
| Android Compatibility | Fails (playback + recording broken) | Works natively (official PreSonus requirement for Android) |

### What Actually Happens on Android in Single Mode (`PID_0D08`)

On real-device Android captures (Android 17 / Xiaomi 18 Fold / XRing O3 Audio DSP):

1. Android enumerates `VID=0x194f, PID=0x0d08` with `bNrChannels=6`.
2. The USB Audio HAL configures both RX and TX DSP backends to 6 channels:
   `AHAL_BeDevice: XR_AUDIO_USB_RX / XR_AUDIO_USB_TX -> rate(48000) ch(6) fmt(32)`
3. As soon as any app starts playback or recording:
   - `AHAL_StreamPrimaryOut: transfer: stream playback dp transfer failed` (every 100 ms)
   - `AHAL_StreamPrimaryIn: transfer: stream record prim transfer failed` (every 100 ms)
   - Audio DSP crashes and enters Subsystem Restart (`SSR recoveryVadAlgo` / `onSSREvent`)
   - Capture fails with `prepare failed: -1 cannot prepare channel: Invalid argument`
   - Apps receive silence (`AudioRecord read -> buffer is mute`) and headphone output stays silent.

Switching the exact same microphone on the exact same phone (without changing a single Android setting) to **Multi Mode (`PID_0D09`)** immediately restores both headphone playback and microphone recording.

---

## 3. Why Windows Silently Breaks Android Mode (Even Without Opening Universal Control)

Inspection of PreSonus's Windows driver INF (`C:\Program Files\Fender\Universal Control\Drivers\DSPUSBSeries\x64\paedspusb.inf`) reveals an intentional kernel-mode auto-revert rule attached to every Multi Mode PID:

```ini
[_Models.ntamd64.10.0...17134]
"Revelator"                    = _Install_1,USB\VID_194F&PID_0D08&MI_00
"Revelator (unsupported mode)" = _Install_4,USB\VID_194F&PID_0D09&MI_00

[_AddReg_4]
HKR,"Config\RestartDeviceRequest","RequestCode",%REG_DWORD%,66
HKR,"Config\RestartDeviceRequest","RequestIndex",%REG_DWORD%,0
HKR,"Config\RestartDeviceRequest","RequestType",%REG_DWORD%,64
```

What those decimal registry values mean:

- `RequestType = 64` (`0x40`): USB Host-to-Device Vendor Control Transfer (`bmRequestType = 0x40`)
- `RequestCode = 66` (`0x42`): PreSonus `SwitchAudioMode` vendor command (`bRequest = 0x42`)
- `RequestValue = 0`, `RequestIndex = 0`: Target mode = **Single Mode (`PID_0D08`)**

When Windows installs the driver for `PID_0D09&MI_00`, it writes those values to:

```text
HKLM\SYSTEM\CurrentControlSet\Enum\USB\VID_194F&PID_0D09&MI_00\<instance>\Device Parameters\Config\RestartDeviceRequest
```

Every time `PID_0D09` enumerates on that Windows USB port, `PaeDSPUSB.sys` (Thesycon TUSBAUDIO kernel driver) reads `Config\RestartDeviceRequest` during device start and immediately sends `bRequest=0x42, mode=0` — silently forcing the microphone back to Single Mode (`PID_0D08`) in under 1 second. Even stopping `PreSonus Hardware Access Service` does **not** prevent this, because the revert happens inside `PaeDSPUSB.sys` in kernel mode.

### Same Pattern Across the Revelator Family in `paedspusb.inf`

| Product | Single Mode PID | Multi Mode PID (has `RestartDeviceRequest`) | Verified on Physical Hardware? |
|---|---|---|---|
| PreSonus Revelator | `0x0D08` (legacy `0x0D01`) | `0x0D09` (legacy `0x0D03`) | **Yes** (Windows 11 + Android 17) |
| PreSonus Revelator Dynamic | `0x0D0A` (legacy `0x0D04`) | `0x0D0B` (legacy `0x0D06`) | Same INF rule; hardware test PR welcome |
| PreSonus Revelator io24 | `0x0422` (legacy `0x0407`) | `0x0423` (legacy `0x0406`) | Same INF rule; hardware test PR welcome |
| PreSonus Revelator io44 | `0x0424` (legacy `0x041A`) | `0x0425` (legacy `0x0419`) | Same INF rule; hardware test PR welcome |

---

## 4. Exact Mode-Switch Control Transfer

Disassembly of `paesdk::JacksonDevice::SwitchAudioMode` in `hwaccess\dspusbdevice.dll` shows the exact call into `PaeDSPUSBapi_x64.dll`:

```c
TUSBAUDIO_ClassVendorRequestOut(
    handle,   // uint32 from TUSBAUDIO_OpenDeviceByIndex(0, &handle)
    0,        // target = USB_DEVICE
    0,        // isClassRequest = 0 (Vendor)
    0x42,     // bRequest = 0x42
    0,        // arg5 = 0
    mode,     // arg6 = 1 for Multi Mode (PID_0D09), 0 for Single Mode (PID_0D08)
    0,        // dataSize = 0
    NULL,     // data
    NULL,     // bytesTransferred
    5000      // timeoutMs
);
```

This does **not** touch DFU interfaces or firmware flashing endpoints.

---

## 5. Safe Recovery Flow on Windows

1. **Disarm the kernel auto-revert trigger** by deleting `Config\RestartDeviceRequest` under `HKLM\SYSTEM\CurrentControlSet\Enum\USB\VID_194F&PID_0D09&MI_00\<instance>\Device Parameters\Config\` (`python scripts/revelator_mode.py disarm --elevate --backup trap-backup.json`).
2. **Send the mode switch** (`python scripts/revelator_mode.py switch multi`), which invokes `TUSBAUDIO_ClassVendorRequestOut(..., bRequest=0x42, arg6=1)` and verifies the device stays enumerated as `PID_0D09` for 10 seconds with zero revert.
3. **Unplug from Windows and plug into Android.** Both headphone playback and microphone capture work immediately.

> **Scope caveat:** Windows creates a separate PnP `<instance>` key per physical USB port. Disarming one port protects that port only. Plugging a Multi-Mode Revelator into a **different USB port**, another Windows PC with PreSonus drivers, or reinstalling Universal Control will create a new `RestartDeviceRequest` key and revert the mic to Single Mode again until disarmed.
