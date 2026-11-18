#!/usr/bin/python3

import pathlib
import subprocess
import sys
import tempfile

iso = pathlib.Path(sys.argv[1]).resolve()

if not iso.is_file():
    raise SystemExit("Vault ISO missing")


with tempfile.TemporaryDirectory(
    prefix="core-vault-iso-"
) as t:

    d = pathlib.Path(t)

    for src, dst in (
        (
            "/isolinux/isolinux.cfg",
            "bios.cfg",
        ),
        (
            "/boot/grub/grub.cfg",
            "uefi.cfg",
        ),
        (
            "/live/filesystem.squashfs",
            "filesystem.squashfs",
        ),
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


    for menu in (
        d / "bios.cfg",
        d / "uefi.cfg",
    ):
        text = menu.read_text()

        assert (
            "Start Bitcoin Core Vault (Live RAM)"
            in text
        )

        assert "username=vault" in text
        assert " toram" in text


    squash = d / "filesystem.squashfs"


    def exists(path):
        result = subprocess.run(
            [
                "unsquashfs",
                "-stat",
                str(squash),
                path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return result.returncode == 0


    listing = subprocess.check_output(
        [
            "unsquashfs",
            "-ll",
            str(squash),
        ],
        text=True,
        stderr=subprocess.PIPE,
    )


    assert 'usr/local/bin/core-signer-session' not in listing
    sessions = [line.split('squashfs-root/', 1)[-1] for line in listing.splitlines()
                if '/xsessions/' in line or '/wayland-sessions/' in line or '/lightdm/sessions/' in line]
    assert [entry for entry in sessions if '.desktop' in entry] == ['usr/share/xsessions/core-vault.desktop']

    for expected in (
        "usr/local/bin/core-vault-home",
        "usr/local/bin/core-vault-session",
        "usr/local/bin/core-vault-bitcoin",
        "usr/bin/keepassxc",
        "usr/bin/brasero",
        "usr/bin/thunar",
        "usr/bin/mousepad",
        "usr/bin/xfce4-terminal",
    ):
        assert expected in listing, expected


    subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name("check-core-release.py")), "--squashfs", str(squash)], check=True)

    # VAULT_ENCRYPTED_BACKUP_V2_ISO_CHECK


    subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name("check-backup-iso.py")), "--squashfs", str(squash)], check=True)
    subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name("check-shred-iso.py")), "--squashfs", str(squash)], check=True)
    print(
        "BITCOIN CORE VAULT LIVE ISO CONTENT CHECKS PASSED"
    )
