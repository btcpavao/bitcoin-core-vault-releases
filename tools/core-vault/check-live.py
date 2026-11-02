#!/usr/bin/python3

from pathlib import Path
import subprocess
import runpy

ROOT = Path(__file__).resolve().parents[2]
INC = ROOT / "config/includes.chroot"

subprocess.run(
    ["/bin/sh", "-n", str(ROOT / "auto/config")],
    check=True,
)

subprocess.run(
    [
        "/bin/sh",
        "-n",
        str(INC / "usr/local/bin/core-vault-session"),
    ],
    check=True,
)

subprocess.run(
    [
        "/usr/bin/python3",
        "-m",
        "py_compile",
        str(INC / "usr/local/bin/core-vault-home"),
    ],
    check=True,
)

auto = (ROOT / "auto/config").read_text()

assert "username=vault" in auto
assert "hostname=core-vault" in auto
assert " toram " in auto

lightdm = (
    INC
    / "etc/lightdm/lightdm.conf.d/50-core-signer.conf"
).read_text()

assert "autologin-user=vault" in lightdm
assert "autologin-session=core-vault" in lightdm

desktop = (
    INC
    / "usr/share/xsessions/core-vault.desktop"
).read_text()

assert "Exec=/usr/local/bin/core-vault-session" in desktop

packages = (
    ROOT
    / "config/package-lists/core-vault.list.chroot"
).read_text()

for package in (
    "libusb-1.0-0",
    "brasero",
    "thunar",
    "mousepad",
    "xfce4-terminal",
    "python3-pyside6.qtwidgets",
    "tint2",
):
    assert package in packages, package

for required in (
    INC / "usr/local/bin/core-vault-home",
    INC / "usr/local/bin/core-vault-session",
    INC / "usr/local/bin/core-vault-bitcoin",
    INC / "usr/local/bin/core-vault-taskbar",
    INC / "usr/local/bin/core-vault-numlock",
    INC / "etc/sudoers.d/91-core-vault-poweroff",
):
    assert required.is_file(), required

print(
    "BITCOIN CORE VAULT LIVE PROJECT CHECKS PASSED"
)
runpy.run_path(str(ROOT / 'tools/core-vault/check-numlock.py'), run_name='__main__')
