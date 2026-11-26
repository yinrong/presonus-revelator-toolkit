import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import revelator_mode as rm  # noqa: E402


class FakeWinreg:
    HKEY_LOCAL_MACHINE = object()
    KEY_READ = 1

    def __init__(self, tree: dict[str, dict[str, int]]):
        # tree maps full rel path -> dict of values (or {} for parent key)
        self.tree = tree
        self.deleted: list[str] = []

    def OpenKey(self, root, path, reserved, access):
        if path in self.tree:
            return path
        # allow opening parent prefix if any child starts with path + "\\"
        prefix = path + "\\"
        if any(k.startswith(prefix) for k in self.tree):
            return path
        raise FileNotFoundError(path)

    def EnumKey(self, key_path, idx):
        prefix = key_path + "\\"
        children = sorted(
            {
                k[len(prefix) :].split("\\", 1)[0]
                for k in self.tree
                if k.startswith(prefix)
            }
        )
        if idx >= len(children):
            raise OSError("No more keys")
        return children[idx]

    def EnumValue(self, key_path, idx):
        vals = list(self.tree.get(key_path, {}).items())
        if idx >= len(vals):
            raise OSError("No more values")
        name, val = vals[idx]
        return name, val, 4

    def CloseKey(self, key_path):
        pass

    def DeleteKey(self, root, path):
        self.deleted.append(path)
        self.tree.pop(path, None)


class FakeTusbDll:
    def __init__(self, instance_id: str, count: int = 1, vendor_rc: int = 0):
        self.instance_id = instance_id
        self.count = count
        self.vendor_rc = vendor_rc
        self.vendor_calls: list[tuple] = []
        self.closed_handles: list[int] = []

    def TUSBAUDIO_EnumerateDevices(self):
        return 0

    def TUSBAUDIO_GetDeviceCount(self):
        return self.count

    def TUSBAUDIO_OpenDeviceByIndex(self, idx, out_handle_ptr):
        out_handle_ptr._obj.value = 65536 + idx
        return 0

    def TUSBAUDIO_GetDeviceInstanceIdString(self, handle, buf, size):
        buf.value = self.instance_id
        return 0

    def TUSBAUDIO_ClassVendorRequestOut(self, *args):
        self.vendor_calls.append(args)
        return self.vendor_rc

    def TUSBAUDIO_CloseDevice(self, handle):
        self.closed_handles.append(handle)
        return 0

    def TUSBAUDIO_StatusCodeStringA(self, code):
        return b"TSTATUS_SUCCESS" if code == 0 else b"TSTATUS_ERROR"


class RevelatorModeTests(unittest.TestCase):
    def test_parse_vid_pid(self):
        self.assertEqual(
            rm.parse_vid_pid(r"USB\VID_194F&PID_0D08&MI_00\7&2048EE69&0&0000"),
            (0x194F, 0x0D08),
        )
        self.assertEqual(
            rm.parse_vid_pid(r"USB\VID_194F&PID_0D09\SERIAL123456"),
            (0x194F, 0x0D09),
        )
        self.assertEqual(rm.parse_vid_pid("unrelated"), (None, None))

    def test_classify_device(self):
        single = rm.classify_device(0x194F, 0x0D08)
        self.assertIsNotNone(single)
        self.assertEqual(single.mode, "single")
        self.assertTrue(single.verified)

        multi = rm.classify_device(0x194F, 0x0D09)
        self.assertIsNotNone(multi)
        self.assertEqual(multi.mode, "multi")
        self.assertTrue(multi.verified)

        io24 = rm.classify_device(0x194F, 0x0423)
        self.assertIsNotNone(io24)
        self.assertEqual(io24.model, "Revelator io24")
        self.assertEqual(io24.mode, "multi")
        self.assertFalse(io24.verified)

        self.assertIsNone(rm.classify_device(0x1234, 0x0D08))

    def test_scan_restart_traps(self):
        trap_path = (
            r"SYSTEM\CurrentControlSet\Enum\USB\VID_194F&PID_0D09&MI_00"
            r"\7&2ec1ab92&0&0000\Device Parameters\Config\RestartDeviceRequest"
        )
        fake = FakeWinreg(
            {
                trap_path: {
                    "RequestCode": 66,
                    "RequestIndex": 0,
                    "RequestType": 64,
                    "RequestValue": 0,
                }
            }
        )
        traps = rm.scan_restart_traps(winreg_mod=fake)
        self.assertEqual(len(traps), 1)
        self.assertEqual(traps[0]["pid"], "0x0D09")
        self.assertEqual(traps[0]["values"]["RequestCode"], 66)
        self.assertEqual(traps[0]["powershell_path"], "HKLM:\\" + trap_path)

    def test_send_mode_switch_exact_vendor_request_multi(self):
        dll = FakeTusbDll(r"USB\VID_194F&PID_0D08&MI_00\7&2048EE69&0&0000")
        res = rm.send_mode_switch_request(dll, "multi")
        self.assertEqual(res["previous_mode"], "single")
        self.assertEqual(res["requested_mode"], "multi")
        self.assertEqual(len(dll.vendor_calls), 1)
        # Exact disassembled SwitchAudioMode(this, 2) call:
        # (handle, target=0, isClass=0, bRequest=0x42, arg5=0, arg6=1, dataSize=0, None, None, 5000)
        self.assertEqual(dll.vendor_calls[0], (65536, 0, 0, 0x42, 0, 1, 0, None, None, 5000))
        self.assertEqual(dll.closed_handles, [65536])

    def test_send_mode_switch_exact_vendor_request_single(self):
        dll = FakeTusbDll(r"USB\VID_194F&PID_0D09&MI_00\7&2EC1AB92&0&0000")
        res = rm.send_mode_switch_request(dll, "single")
        self.assertEqual(res["previous_mode"], "multi")
        self.assertEqual(res["requested_mode"], "single")
        self.assertEqual(dll.vendor_calls[0], (65536, 0, 0, 0x42, 0, 0, 0, None, None, 5000))

    def test_refuses_unknown_usb_device(self):
        dll = FakeTusbDll(r"USB\VID_046D&PID_C52B&MI_00\1234")
        with self.assertRaises(RuntimeError) as ctx:
            rm.send_mode_switch_request(dll, "multi")
        self.assertIn("Refusing to send vendor request", str(ctx.exception))
        self.assertEqual(dll.vendor_calls, [])
        self.assertEqual(dll.closed_handles, [65536])

    def test_build_diag_report_flags_traps_and_single_mode(self):
        report = rm.build_diag_report(
            dll_override=None,
            pnp_scanner=lambda present_only=True: [
                {"InstanceId": r"USB\VID_194F&PID_0D08&MI_00\7&2048EE69&0&0000"}
            ],
            trap_scanner=lambda: [
                {
                    "pid": "0x0D09",
                    "model": "Revelator",
                    "instance": "7&2ec1ab92&0&0000",
                    "reg_path": "x",
                    "powershell_path": "HKLM:\\x",
                    "values": {"RequestCode": 66},
                }
            ],
            service_checker=lambda: {"present": True, "status": "Stopped", "start_type": "Manual"},
        )
        self.assertEqual(len(report["connected_revelator_devices"]), 1)
        self.assertEqual(report["connected_revelator_devices"][0]["mode"], "single")
        self.assertEqual(len(report["warnings"]), 2)

    def test_disarm_dry_run_and_backup(self):
        traps = [
            {
                "pid": "0x0D09",
                "model": "Revelator",
                "instance": "7&2ec1ab92&0&0000",
                "reg_path": "SYSTEM\\test",
                "powershell_path": "HKLM:\\SYSTEM\\test",
                "values": {"RequestCode": 66, "RequestType": 64, "RequestIndex": 0, "RequestValue": 0},
            }
        ]
        with tempfile.TemporaryDirectory() as td:
            backup = os.path.join(td, "backup.json")
            rc = rm.disarm_traps(traps, dry_run=True, backup_path=backup)
            self.assertEqual(rc, 0)
            with open(backup, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["values"]["RequestCode"], 66)


if __name__ == "__main__":
    unittest.main()
