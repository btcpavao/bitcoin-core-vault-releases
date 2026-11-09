#!/usr/bin/python3
"""Optical diagnostics regression fixtures; never open a physical drive."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "config/includes.chroot/usr/local/bin/core-vault-optical-diagnostics"
MODULE = runpy.run_path(str(SCRIPT), run_name="optical_diagnostics_test")


class OpticalDiagnosticsTests(unittest.TestCase):
    def fixture(self, root, name, peripheral_type, usb=False):
        target = root / ("devices/pci0000/usb2/2-1/host2" if usb else "devices/pci0000/host0") / name
        (target / "device").mkdir(parents=True)
        (target / "device/type").write_text(str(peripheral_type))
        (target / "device/model").write_text("SYNTHETIC OPTICAL\n")
        (target / "device/vendor").write_text("TEST\n")
        sys_class = root / "class/block"
        sys_class.mkdir(parents=True, exist_ok=True)
        (sys_class / name).symlink_to(target, target_is_directory=True)
        return sys_class, root / "dev"

    def test_empty_hotplug_usb_optical_and_internal_optical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sys_class, dev = self.fixture(root, "sr0", 5)
            self.fixture(root, "sr1", 5, usb=True)
            self.fixture(root, "sda", 0, usb=True)
            # No partition, mounted filesystem, or inserted media is required.
            devices = MODULE["optical_devices"](sys_class, dev)
            self.assertEqual([Path(d["device"]).name for d in devices], ["sr0", "sr1"])
            self.assertFalse(devices[0]["usb_transport"])
            self.assertTrue(devices[1]["usb_transport"])
            self.assertTrue(all("device_error" in d for d in devices))

    def test_access_failure_is_visible_and_no_device_is_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sys_class, dev = self.fixture(root, "sr0", 5, usb=True)
            dev.mkdir()
            (dev / "sr0").touch()  # Synthetic regular file, never a block device.
            with mock.patch("os.access", return_value=False), mock.patch("os.open", side_effect=AssertionError("device open")):
                devices = MODULE["optical_devices"](sys_class, dev)
            self.assertFalse(devices[0]["readable"])
            self.assertFalse(devices[0]["writable"])
            self.assertFalse(devices[0]["block_device"])

    def test_removal_during_enumeration_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sys_class, dev = self.fixture(root, "sr0", 5, usb=True)
            (sys_class / "sr0/device/type").unlink()
            self.assertEqual(MODULE["optical_devices"](sys_class, dev), [])

    def test_dbus_or_command_failure_is_reported_without_hanging(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("probe", 8)):
            result = MODULE["command"](["probe"])
        self.assertIn("error", result)
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("missing tool")):
            self.assertIn("error", MODULE["command"](["missing"]))

    def test_missing_desktop_bus_keeps_hardware_report(self):
        main_globals = MODULE["main"].__globals__
        with mock.patch.dict(main_globals, {
            "optical_devices": lambda: [],
            "command": lambda argv, timeout=8: {"error": "No desktop bus"},
        }), mock.patch("sys.argv", [str(SCRIPT)]), contextlib.redirect_stdout(io.StringIO()) as out:
            MODULE["main"]()
        report = json.loads(out.getvalue())
        self.assertEqual(report["optical_devices"], [])
        self.assertIn("desktop_probe_error", report["desktop"])
        self.assertIn("does not establish", report["note"])


if __name__ == "__main__":
    unittest.main()
