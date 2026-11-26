#!/usr/bin/env python3
"""
PreSonus Revelator USB Audio Mode Diagnostic & Switcher for Windows.

Solves a widespread PreSonus Revelator + Android bug:
- Android requires Multi Mode (PID 0x0D09: separate 2-channel UAC2 stereo interfaces).
- Windows Universal Control / PaeDSPUSB.sys requires Single Mode (PID 0x0D08: 6-channel).
- Worse, PreSonus's Windows kernel driver (paedspusb.inf -> PaeDSPUSB.sys) installs a
  registry trigger `Config\\RestartDeviceRequest` (RequestType=0x40, RequestCode=0x42,
  RequestValue=0) on Multi Mode PIDs that silently reprograms the microphone back to
  Single Mode within ~1 second whenever it is plugged into Windows.

This tool lets Windows users (without needing a Mac):
  1. Diagnose current USB mode, active RestartDeviceRequest traps, and service state.
  2. Disarm (and optionally backup/rearm) the RestartDeviceRequest auto-revert registry trap.
  3. Switch Revelator between Single Mode (Windows) and Multi Mode (Android/iOS/macOS)
     via PreSonus's own PaeDSPUSBapi_x64.dll vendor request (bRequest=0x42).

Hardware verification status:
- Real-hardware verified end-to-end: PreSonus Revelator (VID 0x194F, PID 0x0D08 <-> 0x0D09)
  on Windows 11 + Android 17 (Xiaomi 18 Fold).
- Revelator Dynamic / io24 / io44 share the identical paedspusb.inf RestartDeviceRequest
  entries (RequestCode=66), but have not yet been verified on physical hardware.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from ctypes import byref, c_char_p, c_uint8, c_uint16, c_uint32, c_void_p
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional

VENDOR_ID = 0x194F
VENDOR_REQUEST_SWITCH_MODE = 0x42  # Disassembled from paesdk::JacksonDevice::SwitchAudioMode

DEFAULT_DLL_CANDIDATES = [
    r"C:\Program Files\Fender\Universal Control\Drivers\DSPUSBSeries\x64\PaeDSPUSBapi_x64.dll",
    r"C:\Program Files\PreSonus\Universal Control\Drivers\DSPUSBSeries\x64\PaeDSPUSBapi_x64.dll",
]

SERVICE_NAME = "PreSonus Hardware Access Service"


@dataclass(frozen=True)
class PidInfo:
    model: str
    mode: str  # "single" or "multi"
    channels_hint: str
    verified: bool
    legacy: bool = False


# Mapping derived directly from PreSonus paedspusb.inf
KNOWN_PIDS: dict[int, PidInfo] = {
    0x0D08: PidInfo("Revelator", "single", "6ch (Windows)", verified=True),
    0x0D09: PidInfo("Revelator", "multi", "2ch stereo x3 (Android/iOS/macOS)", verified=True),
    0x0D01: PidInfo("Revelator (legacy FW)", "single", "6ch", verified=False, legacy=True),
    0x0D03: PidInfo("Revelator (legacy FW)", "multi", "2ch stereo", verified=False, legacy=True),
    0x0D0A: PidInfo("Revelator Dynamic", "single", "6ch (Windows)", verified=False),
    0x0D0B: PidInfo("Revelator Dynamic", "multi", "2ch stereo (Android/iOS/macOS)", verified=False),
    0x0D04: PidInfo("Revelator Dynamic (legacy FW)", "single", "6ch", verified=False, legacy=True),
    0x0D06: PidInfo("Revelator Dynamic (legacy FW)", "multi", "2ch stereo", verified=False, legacy=True),
    0x0422: PidInfo("Revelator io24", "single", "multi-ch (Windows)", verified=False),
    0x0423: PidInfo("Revelator io24", "multi", "2ch stereo (Android/iOS/macOS)", verified=False),
    0x0407: PidInfo("Revelator io24 (legacy FW)", "single", "multi-ch", verified=False, legacy=True),
    0x0406: PidInfo("Revelator io24 (legacy FW)", "multi", "2ch stereo", verified=False, legacy=True),
    0x0424: PidInfo("Revelator io44", "single", "multi-ch (Windows)", verified=False),
    0x0425: PidInfo("Revelator io44", "multi", "2ch stereo (Android/iOS/macOS)", verified=False),
    0x041A: PidInfo("Revelator io44 (legacy FW)", "single", "multi-ch", verified=False, legacy=True),
    0x0419: PidInfo("Revelator io44 (legacy FW)", "multi", "2ch stereo", verified=False, legacy=True),
}

MULTI_MODE_PIDS = sorted(pid for pid, info in KNOWN_PIDS.items() if info.mode == "multi")


def parse_vid_pid(instance_id: str) -> tuple[Optional[int], Optional[int]]:
    """Extract (vid, pid) integers from a Windows USB PnP instance ID string."""
    m = re.search(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})", instance_id or "")
    if not m:
        return None, None
    return int(m.group(1), 16), int(m.group(2), 16)


def classify_device(vid: Optional[int], pid: Optional[int]) -> Optional[PidInfo]:
    if vid != VENDOR_ID or pid is None:
        return None
    return KNOWN_PIDS.get(pid)


def find_dll_path(override: Optional[str] = None) -> Optional[str]:
    if override:
        return override if os.path.isfile(override) else None
    for candidate in DEFAULT_DLL_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


def is_windows_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def scan_restart_traps(winreg_mod: Any = None) -> list[dict[str, Any]]:
    """
    Scan HKLM\\SYSTEM\\CurrentControlSet\\Enum\\USB for active PreSonus
    `Config\\RestartDeviceRequest` registry traps on Multi Mode PIDs.
    """
    if winreg_mod is None:
        if sys.platform != "win32":
            return []
        import winreg as winreg_mod  # type: ignore

    traps: list[dict[str, Any]] = []
    enum_usb_root = r"SYSTEM\CurrentControlSet\Enum\USB"

    for pid in MULTI_MODE_PIDS:
        pid_hex = f"{pid:04X}"
        dev_key_path = rf"{enum_usb_root}\VID_194F&PID_{pid_hex}&MI_00"
        try:
            dev_key = winreg_mod.OpenKey(winreg_mod.HKEY_LOCAL_MACHINE, dev_key_path, 0, winreg_mod.KEY_READ)
        except FileNotFoundError:
            continue
        except OSError:
            continue

        try:
            idx = 0
            while True:
                try:
                    inst_name = winreg_mod.EnumKey(dev_key, idx)
                except OSError:
                    break
                idx += 1
                trap_rel = rf"{dev_key_path}\{inst_name}\Device Parameters\Config\RestartDeviceRequest"
                try:
                    trap_key = winreg_mod.OpenKey(winreg_mod.HKEY_LOCAL_MACHINE, trap_rel, 0, winreg_mod.KEY_READ)
                except FileNotFoundError:
                    continue
                except OSError:
                    continue

                values: dict[str, Any] = {}
                try:
                    vidx = 0
                    while True:
                        try:
                            vname, vval, _vtype = winreg_mod.EnumValue(trap_key, vidx)
                            values[vname] = vval
                            vidx += 1
                        except OSError:
                            break
                finally:
                    winreg_mod.CloseKey(trap_key)

                traps.append(
                    {
                        "pid": f"0x{pid_hex}",
                        "model": KNOWN_PIDS[pid].model,
                        "instance": inst_name,
                        "reg_path": trap_rel,
                        "powershell_path": f"HKLM:\\{trap_rel}",
                        "values": values,
                    }
                )
        finally:
            winreg_mod.CloseKey(dev_key)

    return traps


def get_service_status() -> dict[str, Any]:
    if sys.platform != "win32":
        return {"present": False, "status": "N/A", "start_type": "N/A"}
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            f"$s = Get-Service -Name '{SERVICE_NAME}' -ErrorAction SilentlyContinue; "
            "if ($s) { [PSCustomObject]@{present=$true; status=$s.Status.ToString(); start_type=$s.StartType.ToString()} | ConvertTo-Json -Compress } "
            "else { '{\"present\":false,\"status\":\"NotInstalled\",\"start_type\":\"N/A\"}' }"
        ),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(res.stdout.strip())
    except Exception:
        return {"present": False, "status": "Unknown", "start_type": "Unknown"}


def list_pnp_presonus_devices(present_only: bool = True) -> list[dict[str, Any]]:
    if sys.platform != "win32":
        return []
    flag = "-PresentOnly" if present_only else ""
    ps = (
        f"Get-PnpDevice {flag} -ErrorAction SilentlyContinue | "
        "Where-Object { $_.InstanceId -match '194F' } | "
        "Select-Object Status, Present, Class, FriendlyName, InstanceId | "
        "ConvertTo-Json -Compress"
    )
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    raw = res.stdout.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else [parsed]
    except Exception:
        return []


def load_tusbaudio_api(dll_path: str) -> Any:
    dll = ctypes.WinDLL(dll_path)

    dll.TUSBAUDIO_EnumerateDevices.argtypes = []
    dll.TUSBAUDIO_EnumerateDevices.restype = c_uint32

    dll.TUSBAUDIO_GetDeviceCount.argtypes = []
    dll.TUSBAUDIO_GetDeviceCount.restype = c_uint32

    dll.TUSBAUDIO_OpenDeviceByIndex.argtypes = [c_uint32, ctypes.POINTER(c_uint32)]
    dll.TUSBAUDIO_OpenDeviceByIndex.restype = c_uint32

    dll.TUSBAUDIO_CloseDevice.argtypes = [c_uint32]
    dll.TUSBAUDIO_CloseDevice.restype = c_uint32

    dll.TUSBAUDIO_GetDeviceInstanceIdString.argtypes = [c_uint32, ctypes.c_wchar_p, c_uint32]
    dll.TUSBAUDIO_GetDeviceInstanceIdString.restype = c_uint32

    # Exact argument layout verified from paesdk::JacksonDevice::SwitchAudioMode
    dll.TUSBAUDIO_ClassVendorRequestOut.argtypes = [
        c_uint32,  # handle
        c_uint32,  # target (0 = USB_DEVICE)
        c_uint32,  # isClassRequest (0 = Vendor)
        c_uint8,   # bRequest (0x42)
        c_uint16,  # arg5 (0)
        c_uint16,  # arg6 (0 = Single Mode, 1 = Multi Mode)
        c_uint16,  # dataSize (0)
        c_void_p,  # data (NULL)
        c_void_p,  # bytesTransferred (NULL)
        c_uint32,  # timeoutMs (5000)
    ]
    dll.TUSBAUDIO_ClassVendorRequestOut.restype = c_uint32

    if hasattr(dll, "TUSBAUDIO_StatusCodeStringA"):
        dll.TUSBAUDIO_StatusCodeStringA.argtypes = [c_uint32]
        dll.TUSBAUDIO_StatusCodeStringA.restype = c_char_p

    return dll


def format_status(dll: Any, code: int) -> str:
    if hasattr(dll, "TUSBAUDIO_StatusCodeStringA"):
        try:
            s = dll.TUSBAUDIO_StatusCodeStringA(code)
            if s:
                return f"0x{code:08X} ({s.decode('ascii', errors='replace')})"
        except Exception:
            pass
    return f"0x{code:08X}"


def send_mode_switch_request(
    dll: Any,
    target_mode: str,
    device_index: int = 0,
    timeout_ms: int = 5000,
) -> dict[str, Any]:
    """
    Open the PreSonus device via PaeDSPUSBapi_x64.dll, verify it is a known
    Revelator-family VID/PID, and send the exact SwitchAudioMode vendor request.
    """
    if target_mode not in ("multi", "single"):
        raise ValueError(f"Unsupported target_mode: {target_mode!r}")

    st = dll.TUSBAUDIO_EnumerateDevices()
    if st != 0:
        raise RuntimeError(f"TUSBAUDIO_EnumerateDevices failed: {format_status(dll, st)}")

    count = int(dll.TUSBAUDIO_GetDeviceCount())
    if count == 0:
        raise RuntimeError(
            "No TUSBAUDIO device found via PaeDSPUSBapi_x64.dll. "
            "Check that the Revelator is plugged into USB and Universal Control drivers are installed."
        )
    if device_index >= count:
        raise RuntimeError(f"device_index={device_index} out of range (DeviceCount={count})")

    handle = c_uint32(0)
    st = dll.TUSBAUDIO_OpenDeviceByIndex(device_index, byref(handle))
    if st != 0:
        raise RuntimeError(f"TUSBAUDIO_OpenDeviceByIndex({device_index}) failed: {format_status(dll, st)}")

    try:
        buf = ctypes.create_unicode_buffer(512)
        ist = dll.TUSBAUDIO_GetDeviceInstanceIdString(handle.value, buf, 512)
        if ist != 0:
            raise RuntimeError(f"TUSBAUDIO_GetDeviceInstanceIdString failed: {format_status(dll, ist)}")
        inst = buf.value
        vid, pid = parse_vid_pid(inst)
        info = classify_device(vid, pid)
        if info is None:
            raise RuntimeError(
                f"Refusing to send vendor request to unrecognized device: {inst!r} "
                f"(VID={hex(vid) if vid is not None else None}, PID={hex(pid) if pid is not None else None})"
            )

        mode_val = 1 if target_mode == "multi" else 0
        rst = dll.TUSBAUDIO_ClassVendorRequestOut(
            handle.value,
            0,  # target = USB_DEVICE
            0,  # isClassRequest = 0 (Vendor)
            VENDOR_REQUEST_SWITCH_MODE,  # bRequest = 0x42
            0,  # arg5
            mode_val,  # arg6: 1 = Multi Mode, 0 = Single Mode
            0,  # dataSize
            None,  # data
            None,  # bytesTransferred
            timeout_ms,
        )
        if rst != 0:
            raise RuntimeError(f"TUSBAUDIO_ClassVendorRequestOut failed: {format_status(dll, rst)}")

        return {
            "instance_id": inst,
            "previous_vid": f"0x{vid:04X}",
            "previous_pid": f"0x{pid:04X}",
            "model": info.model,
            "previous_mode": info.mode,
            "requested_mode": target_mode,
            "vendor_request": {
                "bRequest": f"0x{VENDOR_REQUEST_SWITCH_MODE:02X}",
                "arg5": 0,
                "arg6": mode_val,
            },
            "status": format_status(dll, rst),
        }
    finally:
        dll.TUSBAUDIO_CloseDevice(handle.value)


def build_diag_report(
    dll_override: Optional[str] = None,
    pnp_scanner: Callable[[bool], list[dict[str, Any]]] = list_pnp_presonus_devices,
    trap_scanner: Callable[[], list[dict[str, Any]]] = scan_restart_traps,
    service_checker: Callable[[], dict[str, Any]] = get_service_status,
) -> dict[str, Any]:
    dll_path = find_dll_path(dll_override)
    pnp_present = pnp_scanner(True)
    traps = trap_scanner()
    service = service_checker()

    detected_devices: list[dict[str, Any]] = []
    seen_pairs: set[tuple[int, int]] = set()
    for dev in pnp_present:
        vid, pid = parse_vid_pid(dev.get("InstanceId", ""))
        info = classify_device(vid, pid)
        if info and vid is not None and pid is not None and (vid, pid) not in seen_pairs:
            seen_pairs.add((vid, pid))
            detected_devices.append(
                {
                    "vid": f"0x{vid:04X}",
                    "pid": f"0x{pid:04X}",
                    **asdict(info),
                }
            )

    warnings: list[str] = []
    if traps:
        warnings.append(
            f"Found {len(traps)} active PaeDSPUSB.sys RestartDeviceRequest trap(s). "
            "Windows will silently revert Multi Mode back to Single Mode (~1s after plug-in) "
            "until you run: python revelator_mode.py disarm --elevate"
        )
    for d in detected_devices:
        if d["mode"] == "single":
            warnings.append(
                f"{d['model']} is currently in Single Mode ({d['pid']}, {d['channels_hint']}). "
                "Android devices require Multi Mode."
            )

    return {
        "platform": sys.platform,
        "is_admin": is_windows_admin(),
        "dll_path": dll_path,
        "service": service,
        "connected_revelator_devices": detected_devices,
        "pnp_entries_count": len(pnp_present),
        "restart_device_request_traps": traps,
        "warnings": warnings,
    }


def disarm_traps(
    traps: list[dict[str, Any]],
    dry_run: bool = False,
    elevate: bool = False,
    backup_path: Optional[str] = None,
    winreg_mod: Any = None,
) -> int:
    if not traps:
        print("No active RestartDeviceRequest traps found. Nothing to disarm.")
        return 0

    if backup_path:
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(traps, f, indent=2, ensure_ascii=False)
        print(f"Backed up {len(traps)} trap record(s) to: {backup_path}")

    ps_commands = [f"Remove-Item -LiteralPath '{t['powershell_path']}' -Force" for t in traps]

    if dry_run:
        print("[DRY RUN] Would delete the following registry keys:")
        for cmd in ps_commands:
            print(" ", cmd)
        return 0

    if is_windows_admin():
        if winreg_mod is None:
            import winreg as winreg_mod  # type: ignore
        for t in traps:
            winreg_mod.DeleteKey(winreg_mod.HKEY_LOCAL_MACHINE, t["reg_path"])
            print(f"Deleted: {t['powershell_path']}")
        return 0

    joined = "; ".join(ps_commands)
    if elevate and sys.platform == "win32":
        print("Launching Windows UAC prompt to remove RestartDeviceRequest key(s)...")
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f'Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList "-NoProfile","-Command","{joined}"',
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print("UAC elevation failed or was cancelled:", proc.stderr.strip(), file=sys.stderr)
            return 1
        remaining = scan_restart_traps()
        if remaining:
            print(f"Warning: {len(remaining)} trap(s) still present after elevation.", file=sys.stderr)
            return 2
        print("Success: all RestartDeviceRequest traps removed.")
        return 0

    print("Administrator privileges are required to delete HKLM registry keys.")
    print("Either re-run with `--elevate` (opens a standard Windows UAC dialog),")
    print("or run the following in an Administrator PowerShell window:\n")
    for cmd in ps_commands:
        print(" ", cmd)
    return 1


def rearm_traps(backup_path: str, elevate: bool = False) -> int:
    with open(backup_path, "r", encoding="utf-8") as f:
        traps = json.load(f)
    if not traps:
        print("Backup file contains no traps.")
        return 0

    ps_cmds: list[str] = []
    for t in traps:
        p = t["powershell_path"]
        ps_cmds.append(f"New-Item -Path '{p}' -Force | Out-Null")
        for k, v in t.get("values", {}).items():
            ps_cmds.append(f"New-ItemProperty -Path '{p}' -Name '{k}' -Value {int(v)} -PropertyType DWord -Force | Out-Null")

    joined = "; ".join(ps_cmds)
    if is_windows_admin():
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", joined], capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stderr, file=sys.stderr)
            return 1
        print(f"Restored {len(traps)} RestartDeviceRequest key(s) from {backup_path}.")
        return 0

    if elevate and sys.platform == "win32":
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f'Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList "-NoProfile","-Command","{joined}"',
            ],
            capture_output=True,
            text=True,
        )
        return proc.returncode

    print("Run the following in an Administrator PowerShell window (or pass --elevate):\n")
    for c in ps_cmds:
        print(" ", c)
    return 1


def cmd_diag(args: argparse.Namespace) -> int:
    report = build_diag_report(dll_override=args.dll)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print("=== PreSonus Revelator Windows Diagnostic ===")
    print(f"Platform       : {report['platform']} (Admin={report['is_admin']})")
    print(f"TUSBAUDIO DLL  : {report['dll_path'] or 'NOT FOUND (install Universal Control)'}")
    svc = report["service"]
    print(f"PreSonus Svc   : {svc.get('status')} (StartType={svc.get('start_type')})")

    devs = report["connected_revelator_devices"]
    if not devs:
        print("Connected Mic  : NONE detected (plug Revelator into USB)")
    else:
        for d in devs:
            vtag = "verified" if d["verified"] else "unverified-on-hw"
            print(f"Connected Mic  : {d['model']} ({d['vid']}&{d['pid']}) -> {d['mode'].upper()} MODE ({d['channels_hint']}) [{vtag}]")

    traps = report["restart_device_request_traps"]
    print(f"Auto-Revert Key: {len(traps)} active RestartDeviceRequest trap(s)")
    for t in traps:
        print(f"  - [{t['model']} {t['pid']}] {t['powershell_path']} -> {t['values']}")

    if report["warnings"]:
        print("\nWarnings:")
        for w in report["warnings"]:
            print(f"  ! {w}")
    return 0


def cmd_disarm(args: argparse.Namespace) -> int:
    traps = scan_restart_traps()
    return disarm_traps(
        traps,
        dry_run=args.dry_run,
        elevate=args.elevate,
        backup_path=args.backup,
    )


def cmd_rearm(args: argparse.Namespace) -> int:
    return rearm_traps(args.backup, elevate=args.elevate)


def cmd_switch(args: argparse.Namespace) -> int:
    if sys.platform != "win32":
        print("Mode switching via PaeDSPUSBapi_x64.dll only runs on Windows.", file=sys.stderr)
        return 1

    dll_path = find_dll_path(args.dll)
    if not dll_path:
        print("Could not find PaeDSPUSBapi_x64.dll. Install Fender/PreSonus Universal Control or pass --dll.", file=sys.stderr)
        return 1

    if args.mode == "multi":
        traps = scan_restart_traps()
        if traps and not args.force:
            print(
                f"BLOCKED: Found {len(traps)} active RestartDeviceRequest trap(s) in Windows registry.\n"
                "If you switch to Multi Mode now, PaeDSPUSB.sys will silently revert the mic back to Single Mode in ~1 second.\n"
                "First run: python revelator_mode.py disarm --elevate\n"
                "(Or pass --force to switch anyway.)",
                file=sys.stderr,
            )
            return 3

    dll = load_tusbaudio_api(dll_path)
    result = send_mode_switch_request(dll, args.mode, device_index=args.index)
    print(
        f"Sent SwitchAudioMode ({result['previous_mode']} -> {result['requested_mode']}) "
        f"to {result['model']} ({result['previous_vid']}&{result['previous_pid']}): {result['status']}"
    )

    if args.no_wait:
        return 0

    for wait_s in (4, 6):
        time.sleep(wait_s)
        present = list_pnp_presonus_devices(present_only=True)
        modes = set()
        pids = set()
        for dev in present:
            v, p = parse_vid_pid(dev.get("InstanceId", ""))
            info = classify_device(v, p)
            if info and p is not None:
                modes.add(info.mode)
                pids.add(f"0x{p:04X}")
        print(f"[+{wait_s}s check] Present PIDs={sorted(pids)} modes={sorted(modes)}")

    if args.mode in modes:
        print(f"VERIFIED: Device re-enumerated and held steady in {args.mode.upper()} MODE ({sorted(pids)}).")
        if args.mode == "multi":
            print("Note: Windows Device Manager showing 'Revelator (unsupported mode)' for PID_0D09 is normal.")
            print("You can now unplug the Revelator from Windows and plug it straight into your Android phone!")
        return 0

    print(
        f"WARNING: Expected {args.mode.upper()} MODE after re-enumeration, but saw modes={sorted(modes)} PIDs={sorted(pids)}.\n"
        "If it reverted back to Single Mode, run `python revelator_mode.py diag` — a new USB port may have "
        "created a fresh RestartDeviceRequest key. Run `python revelator_mode.py disarm --elevate` and retry.",
        file=sys.stderr,
    )
    return 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="revelator_mode.py",
        description="Diagnose and switch PreSonus Revelator Single/Multi USB Audio Mode on Windows (Android fix).",
    )
    parser.add_argument("--dll", default=None, help="Optional custom path to PaeDSPUSBapi_x64.dll")
    sub = parser.add_subparsers(dest="command", required=True)

    p_diag = sub.add_parser("diag", help="Inspect current Revelator USB mode, traps, and service status (read-only)")
    p_diag.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_diag.set_defaults(func=cmd_diag)

    p_disarm = sub.add_parser("disarm", help="Remove Windows PaeDSPUSB.sys RestartDeviceRequest auto-revert registry trap(s)")
    p_disarm.add_argument("--dry-run", action="store_true", help="Print target keys without modifying registry")
    p_disarm.add_argument("--elevate", action="store_true", help="Trigger a standard Windows UAC prompt if not Admin")
    p_disarm.add_argument("--backup", default=None, help="Optional JSON file path to back up removed keys")
    p_disarm.set_defaults(func=cmd_disarm)

    p_rearm = sub.add_parser("rearm", help="Restore RestartDeviceRequest registry key(s) from a JSON backup")
    p_rearm.add_argument("--backup", required=True, help="JSON backup file created by `disarm --backup`")
    p_rearm.add_argument("--elevate", action="store_true", help="Trigger a standard Windows UAC prompt if not Admin")
    p_rearm.set_defaults(func=cmd_rearm)

    p_sw = sub.add_parser("switch", help="Switch Revelator between Multi Mode (Android/iOS/macOS) and Single Mode (Windows)")
    p_sw.add_argument("mode", choices=["multi", "single"], help="Target USB audio mode")
    p_sw.add_argument("--index", type=int, default=0, help="TUSBAUDIO device index (default: 0)")
    p_sw.add_argument("--force", action="store_true", help="Switch even if RestartDeviceRequest traps are still armed")
    p_sw.add_argument("--no-wait", action="store_true", help="Skip 10s post-switch stability check")
    p_sw.set_defaults(func=cmd_switch)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
