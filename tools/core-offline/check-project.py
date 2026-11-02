#!/usr/bin/python3
"""Read-only checks for the Live-only Bitcoin Core Offline recipe."""

from pathlib import Path
import hashlib
import json
import subprocess

R = Path(__file__).resolve().parents[2]
I = R / "config/includes.chroot"

expected = json.loads(
    (I / "etc/core-offline/expected-preserved.json").read_text()
)

for name, wanted_hash in expected.items():
    path = I / name

    if hashlib.sha256(path.read_bytes()).hexdigest() != wanted_hash:
        raise SystemExit(
            "Original working component changed unexpectedly: " + name
        )

for path in (
    R / "auto/config",
    I / "usr/local/bin/core-signer-session",
):
    subprocess.run(
        ["/bin/sh", "-n", str(path)],
        check=True,
    )

auto_config = (R / "auto/config").read_text()

assert "--debian-installer none" in auto_config

desktop = (
    I / "usr/share/xsessions/core-signer.desktop"
).read_text()

assert "Exec=/usr/local/bin/core-signer-session" in desktop
assert "core-offline-entry" not in desktop

for forbidden in (
    I / "etc/calamares",
    I / "usr/lib/core-offline-installer",
    I / "usr/local/bin/core-offline-entry",
    I / "usr/local/sbin/core-offline-installer",
    I / "etc/sudoers.d/80-core-offline-installer",
    R / "config/package-lists/core-offline-installer.list.chroot",
):
    assert not forbidden.exists(), str(forbidden)

boot_hook = (
    R / "config/hooks/live/0990-core-offline-boot-menu.hook.binary"
).read_text()

assert "core-offline.install=1" not in boot_hook
assert "Install Bitcoin Core Offline" not in boot_hook
assert "toram" in boot_hook

print("BITCOIN CORE OFFLINE LIVE-ONLY PROJECT CHECKS PASSED")
