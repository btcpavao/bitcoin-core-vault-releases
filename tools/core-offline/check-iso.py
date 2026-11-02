#!/usr/bin/python3
"""Inspect the completed Live-only ISO. No mount or disk write."""

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile

iso = pathlib.Path(sys.argv[1]).resolve()

if not iso.is_file():
    raise SystemExit("ISO missing")

with tempfile.TemporaryDirectory(
    prefix="core-offline-iso-check-"
) as t:

    d = pathlib.Path(t)

    for src, dst in (
        ("/isolinux/isolinux.cfg", "bios.cfg"),
        ("/boot/grub/grub.cfg", "uefi.cfg"),
        ("/live/filesystem.squashfs", "filesystem.squashfs"),
    ):
        subprocess.run(
            [
                "xorriso",
                "-osirrox",
                "on",
                "-indev",
                str(iso),
                "-extract",
                src,
                str(d / dst),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    for name in ("bios.cfg", "uefi.cfg"):
        text = (d / name).read_text()

        assert "Start Bitcoin Core Offline (Live RAM)" in text
        assert "Install Bitcoin Core Offline" not in text
        assert "core-offline.install=1" not in text
        assert " toram" in text

    squashfs = d / "filesystem.squashfs"

    def get(name):
        return subprocess.check_output(
            [
                "unsquashfs",
                "-cat",
                str(squashfs),
                name,
            ],
            stderr=subprocess.PIPE,
        )

    desktop = get(
        "usr/share/xsessions/core-signer.desktop"
    )

    assert b"Exec=/usr/local/bin/core-signer-session" in desktop
    assert b"core-offline-entry" not in desktop

    manifest = json.loads(
        get("etc/core-offline/expected-preserved.json")
    )

    for name, wanted_hash in manifest.items():
        assert hashlib.sha256(get(name)).hexdigest() == wanted_hash, name

    assert (
        b"CORE_OFFLINE_INTEGRATION"
        not in get("usr/local/bin/core-signer-session")
    )

    listing = subprocess.check_output(
        [
            "unsquashfs",
            "-ll",
            str(squashfs),
        ],
        text=True,
        stderr=subprocess.PIPE,
    )

    for forbidden in (
        "/etc/calamares/",
        "/usr/lib/core-offline-installer/",
        "/usr/bin/calamares",
        "/usr/local/bin/core-offline-entry",
        "/usr/local/sbin/core-offline-installer",
    ):
        assert forbidden not in listing, forbidden

    print("BITCOIN CORE OFFLINE LIVE-ONLY ISO CONTENT CHECKS PASSED")
