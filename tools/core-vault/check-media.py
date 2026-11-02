#!/usr/bin/python3

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

pkg = (
    ROOT
    / "config/package-lists/core-vault.list.chroot"
).read_text().splitlines()

for required in (
    "udisks2",
    "udiskie",
    "brasero",
    "brasero-cdrkit",
    "eject",
):
    assert required in pkg, required

floppy = (
    ROOT
    / "config/includes.chroot/etc/modprobe.d/core-vault-no-floppy.conf"
).read_text()

assert "blacklist floppy" in floppy
assert "install floppy /bin/false" in floppy

print("VAULT MEDIA POLICY CHECK PASSED")
