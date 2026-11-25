#!/usr/bin/python3
"""Write the Vault live menus with automatic, model-specific T2 kernel selection.

The full binary hook stages both kernel pairs and retains the existing BIOS
choices. For a local ISO repack, --grub-output writes only the UEFI menu; the
assembler supplies the four boot files and retains the original BIOS menu.
This is a build step, not a boot or installation test.
"""
from pathlib import Path
import argparse
import importlib.util
import re
import shutil

LIVE_ARGS = (
    "boot=live components username=vault hostname=core-vault "
    "noroot nottyautologin noeject noswap quiet splash loglevel=3 "
    "systemd.show_status=false rd.systemd.show_status=false "
    "vt.global_cursor_default=0 toram"
)
INSTALL_ARGS = LIVE_ARGS.removesuffix(" toram") + " core-vault.install=1"
T2_ARGS = "intel_iommu=on iommu=pt pm_async=off core-vault.hardware=t2"
GENERIC_KERNEL = "/live/vmlinuz"
GENERIC_INITRD = "/live/initrd.img"
T2_KERNEL = "/live/t2/vmlinuz"
T2_INITRD = "/live/t2/initrd.img"


# Share exact SMBIOS detection with the persistent installed-OS renderer.
renderer_path = (
    Path(__file__).resolve().parents[2]
    / "config/includes.chroot/usr/lib/core-vault/t2_grub.py"
)
renderer_spec = importlib.util.spec_from_file_location("core_vault_t2_grub", renderer_path)
if renderer_spec is None or renderer_spec.loader is None:
    raise RuntimeError("Cannot load the shared Vault GRUB renderer.")
renderer = importlib.util.module_from_spec(renderer_spec)
renderer_spec.loader.exec_module(renderer)
load_models = renderer.load_models


def render_grub(manufacturers, models):
    menu = """# Generated from the shared Vault T2 model list.
set default=0
set timeout=-1
insmod all_video
insmod gfxterm
terminal_output gfxterm
set menu_color_normal=white/black
set menu_color_highlight=black/white

""" + renderer.render_detection(manufacturers, models)
    for title, args in (
        ("Start Bitcoin Core Vault (Live RAM)", LIVE_ARGS),
        ("Install Bitcoin Core Vault", INSTALL_ARGS),
    ):
        # Keep separate literal argument lists: no dependency on GRUB's word
        # splitting for a variable containing several kernel parameters.
        menu += f"""
menuentry '{title}' {{
    if [ "$core_vault_t2" = "1" ]; then
        linux {T2_KERNEL} {args} {T2_ARGS}
        initrd {T2_INITRD}
    else
        linux {GENERIC_KERNEL} {args}
        initrd {GENERIC_INITRD}
    fi
}}
"""
    return menu


def render_isolinux():
    # T2 Macs use EFI. Legacy BIOS retains the standard kernel and choices.
    return f"""UI vesamenu.c32
PROMPT 0
TIMEOUT 0
DEFAULT core-vault-live
MENU TITLE Bitcoin Core Vault
MENU COLOR screen 37;40 #ffffffff #ff000000 none
MENU COLOR title 37;40 #ffffffff #ff000000 none
MENU COLOR sel 30;47 #ff000000 #ffffffff none

LABEL core-vault-live
  MENU LABEL Start Bitcoin Core Vault (Live RAM)
  KERNEL {GENERIC_KERNEL}
  APPEND initrd={GENERIC_INITRD} {LIVE_ARGS}

LABEL core-vault-install
  MENU LABEL Install Bitcoin Core Vault
  KERNEL {GENERIC_KERNEL}
  APPEND initrd={GENERIC_INITRD} {INSTALL_ARGS}
"""


def is_t2_version(name):
    return re.search(r"-t2(?:-|$)", name) is not None


def require_file(path, root):
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty boot file: {path}")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Boot file points outside the binary tree: {path}")


def kernel_pair(binary, t2):
    live = binary / "live"
    candidates = sorted(
        p for p in live.glob("vmlinuz-*")
        if is_t2_version(p.name) == t2
    )
    if len(candidates) > 1:
        raise ValueError(f"Ambiguous {'T2' if t2 else 'standard'} kernels: {candidates}")
    if candidates:
        kernel = candidates[0]
        initrd = kernel.with_name(kernel.name.replace("vmlinuz-", "initrd.img-", 1))
    else:
        kernel = binary / (T2_KERNEL if t2 else GENERIC_KERNEL).lstrip("/")
        initrd = binary / (T2_INITRD if t2 else GENERIC_INITRD).lstrip("/")
        # A live-build symlink to a newer T2 kernel must never become the
        # ordinary-PC default merely because its version sorts last.
        if not t2 and is_t2_version(kernel.resolve().name):
            raise ValueError("The standard live kernel points to a T2 kernel.")
    require_file(kernel, binary)
    require_file(initrd, binary)
    return kernel, initrd


def stage_pair(binary, sources, destinations):
    for source, relative in zip(sources, destinations):
        target = binary / relative.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        if source == target:
            continue
        if target.exists() or target.is_symlink():
            # Replacing a symlink itself avoids overwriting its versioned
            # kernel target. All destinations are within this staging tree.
            target.unlink()
        shutil.copy2(source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--grub-output", type=Path)
    mode.add_argument("--binary-root", type=Path)
    args = parser.parse_args()
    manufacturers, models = load_models(args.models)
    grub_text = render_grub(manufacturers, models)
    if args.grub_output:
        args.grub_output.parent.mkdir(parents=True, exist_ok=True)
        args.grub_output.write_text(grub_text, encoding="utf-8")
        print(f"Wrote automatic T2 UEFI menu: {args.grub_output}")
        return

    binary = args.binary_root.resolve()
    if binary == Path("/") or not (binary / "live/filesystem.squashfs").is_file():
        raise ValueError("Expected a separate live-build binary staging tree.")
    for relative in (
        "isolinux/isolinux.cfg",
        "boot/grub/grub.cfg",
        "boot/grub/x86_64-efi/smbios.mod",
    ):
        require_file(binary / relative, binary)
    # Resolve and check both pairs before changing any staging files.
    generic = kernel_pair(binary, t2=False)
    t2 = kernel_pair(binary, t2=True)
    stage_pair(binary, generic, (GENERIC_KERNEL, GENERIC_INITRD))
    stage_pair(binary, t2, (T2_KERNEL, T2_INITRD))
    (binary / "isolinux/isolinux.cfg").write_text(render_isolinux(), encoding="utf-8")
    (binary / "boot/grub/grub.cfg").write_text(grub_text, encoding="utf-8")
    print("Vault BIOS/UEFI menus written; T2 selection is automatic.")


if __name__ == "__main__":
    main()
