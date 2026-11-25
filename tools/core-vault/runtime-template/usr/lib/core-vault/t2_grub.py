#!/usr/bin/python3
"""Render the installed Vault GRUB entry and shared boot-time T2 detection.

09_core_vault_auto calls this through grub-mkconfig. Selection happens in GRUB
on every boot, not on the machine that built or installed the image.
"""
from pathlib import Path
import json
import os
import re
import shlex
import subprocess
import sys

MODELS = Path("/usr/share/core-vault/t2-models.json")
PROFILE = Path("/etc/core-vault/kernel-profile.json")
INSTALLATION = Path("/etc/core-vault/installation.json")
ENTRY_ID = "core-vault-auto"
SAFE_ARGUMENT = re.compile(r"[A-Za-z0-9_.,:/=@%+!\[\]-]+")
VERSION = re.compile(r"[0-9][A-Za-z0-9.+_-]*")
UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

# grub-mkconfig exports its configured command line. Never copy /proc/cmdline:
# during installation it belongs to the live USB, even from inside chroot.
LIVE_KEYS = frozenset({
    "boot", "components", "username", "hostname", "noroot", "nottyautologin",
    "noeject", "toram", "todisk", "findiso", "fromiso", "fetch", "httpfs",
    "netboot", "nfsroot", "config", "live-config", "union",
})
OWNED_KEYS = frozenset({
    "root", "rootfstype", "initrd", "BOOT_IMAGE", "ro", "rw",
    "resume", "resume_offset", "intel_iommu", "iommu", "pm_async",
})
OTHER_BOOT_KEYS = frozenset({
    "init", "rdinit", "single", "rescue", "emergency", "break",
    "systemd.unit", "rd.systemd.unit",
})


class GrubConfigError(RuntimeError):
    pass


def load_models(path=MODELS):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise GrubConfigError(f"Unsupported T2 model-list schema in {path}.")
    manufacturers = data["manufacturers"]
    models = data["models"]
    for name, values, pattern in (
        ("manufacturers", manufacturers, r"[A-Za-z0-9 .,()-]+"),
        ("models", models, r"[A-Za-z][A-Za-z0-9]*[0-9]+,[0-9]+"),
    ):
        if not isinstance(values, list) or not values:
            raise GrubConfigError(f"Expected a nonempty {name} list in {path}.")
        if any(not isinstance(value, str) or re.fullmatch(pattern, value) is None
               for value in values):
            raise GrubConfigError(f"Invalid GRUB-safe {name} entry in {path}.")
        if len(set(values)) != len(values):
            raise GrubConfigError(f"Duplicate {name} entry in {path}.")
    return manufacturers, models


def render_detection(manufacturers, models):
    # SMBIOS type 1: Manufacturer string index at byte 4, Product Name at 5.
    # Exact vendor AND model matches avoid classifying all Intel Macs as T2.
    # https://www.gnu.org/software/grub/manual/grub/html_node/smbios.html
    vendor_words = " ".join("'" + value + "'" for value in manufacturers)
    model_words = " ".join("'" + value + "'" for value in models)
    return f"""set core_vault_t2=0
if [ "$grub_platform" = "efi" ]; then
    if insmod smbios; then
        if smbios --type 1 --get-string 4 --set core_vault_vendor; then
            if smbios --type 1 --get-string 5 --set core_vault_model; then
                for core_vault_t2_vendor in {vendor_words}; do
                    if [ "$core_vault_vendor" = "$core_vault_t2_vendor" ]; then
                        for core_vault_t2_model in {model_words}; do
                            if [ "$core_vault_model" = "$core_vault_t2_model" ]; then
                                set core_vault_t2=1
                            fi
                        done
                    fi
                done
            fi
        fi
    fi
fi
export core_vault_t2
"""


def argument_key(value):
    return value.partition("=")[0]


def live_argument(key):
    return key in LIVE_KEYS or key.startswith((
        "live-", "live.", "persistence", "nopersistence",
        "core-vault.", "core-offline.",
    ))


def safe_argument(value):
    if not isinstance(value, str) or SAFE_ARGUMENT.fullmatch(value) is None:
        raise GrubConfigError(f"Unsupported or unsafe GRUB argument: {value!r}")
    return value


def load_profile(path=PROFILE):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise GrubConfigError(f"Unsupported kernel-profile schema in {path}.")
    generic = data["generic_release"]
    t2 = data["t2_release"]
    if any(not isinstance(value, str) or VERSION.fullmatch(value) is None
           for value in (generic, t2)):
        raise GrubConfigError("Invalid pinned kernel release.")
    if "-t2-" in generic or "-t2-" not in t2 or generic == t2:
        raise GrubConfigError("Standard and T2 kernel releases are not distinct.")
    parameters = data["t2_parameters"]
    if not isinstance(parameters, list) or not parameters:
        raise GrubConfigError("Expected nonempty T2 kernel parameters.")
    for value in parameters:
        safe_argument(value)
        key = argument_key(value)
        if live_argument(key) or key in (
            OWNED_KEYS - {"intel_iommu", "iommu", "pm_async"}
        ) or key in OTHER_BOOT_KEYS or key in {"efi", "noresume"}:
            raise GrubConfigError(f"Invalid T2 hardware parameter: {value!r}")
    if len(set(parameters)) != len(parameters):
        raise GrubConfigError("Duplicate T2 kernel parameters.")
    return generic, t2, parameters


def configured_arguments(t2_parameters):
    owned = OWNED_KEYS | {argument_key(value) for value in t2_parameters}
    result = []
    for name in ("GRUB_CMDLINE_LINUX", "GRUB_CMDLINE_LINUX_DEFAULT"):
        for value in shlex.split(os.environ.get(name, ""), posix=True):
            key = argument_key(value)
            if live_argument(key) or key in owned or key in OTHER_BOOT_KEYS:
                continue
            if key == "efi" and "noruntime" in value.partition("=")[2].split(","):
                continue
            safe_argument(value)
            if value not in result:
                result.append(value)
    if "noresume" not in result:
        result.insert(0, "noresume")
    return result


def probe(target, path):
    process = subprocess.run(
        ["/usr/sbin/grub-probe", "--target=" + target, path],
        text=True, capture_output=True, timeout=30, check=False,
    )
    if process.returncode:
        raise GrubConfigError(
            f"Cannot probe installed {path} ({target}): {process.stderr.strip()}"
        )
    value = process.stdout.strip()
    if not value or "\n" in value:
        raise GrubConfigError(f"Ambiguous installed {path} ({target}).")
    return value


def root_uuid():
    entries = [
        line.split() for line in Path("/etc/fstab").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    root_entries = [row for row in entries if len(row) >= 3 and row[1] == "/"]
    if len(root_entries) != 1 or root_entries[0][2] != "ext4":
        raise GrubConfigError("Automatic Vault boot requires one ext4 root in fstab.")
    if any(len(row) >= 2 and row[1] == "/boot" for row in entries):
        raise GrubConfigError("Separate /boot is not supported by this Vault layout.")
    if Path("/").stat().st_dev != Path("/boot").stat().st_dev:
        raise GrubConfigError("/boot must be on the Vault root filesystem.")
    value = probe("fs_uuid", "/")
    if UUID.fullmatch(value) is None:
        raise GrubConfigError("The installed ext4 root has an invalid UUID.")
    if probe("fs_uuid", "/boot").lower() != value.lower():
        raise GrubConfigError("/boot and / have different filesystem UUIDs.")
    # GRUB's ext2 module handles ext2, ext3 and ext4; fstab above requires ext4.
    if probe("fs", "/") != "ext2":
        raise GrubConfigError("The installed root is not readable by GRUB ext2.")
    source = root_entries[0][0]
    if source.startswith("UUID=") and source[5:].lower() != value.lower():
        raise GrubConfigError("The fstab root UUID differs from the installed root.")
    return value.lower()


def require_boot_pair(release):
    for prefix in ("vmlinuz-", "initrd.img-"):
        path = Path("/boot") / (prefix + release)
        if not path.is_file() or path.stat().st_size == 0:
            raise GrubConfigError(f"Required installed boot file is missing: {path}")
    if not (Path("/usr/lib/modules") / release).is_dir():
        raise GrubConfigError(f"Required installed kernel modules are missing: {release}")


def quote_arguments(values):
    # Validation excludes GRUB metacharacters and quote delimiters. Each
    # argument remains literal; no shell, GRUB or command substitution occurs.
    return " ".join("'" + safe_argument(value) + "'" for value in values)


def render_installed(manufacturers, models, generic, t2, parameters, uuid, args):
    common = quote_arguments(["root=UUID=" + uuid, "ro", "rootfstype=ext4", *args])
    t2_args = quote_arguments(parameters)
    return (
        "# Vault automatic hardware selection; generated by 09_core_vault_auto.\n"
        + render_detection(manufacturers, models)
        + f"""
menuentry 'Bitcoin Core Vault' --class gnu-linux --class gnu --class os --id '{ENTRY_ID}' {{
    insmod part_gpt
    insmod part_msdos
    insmod ext2
    insmod search_fs_uuid
    insmod gzio
    insmod all_video
    set gfxpayload=keep
    search --no-floppy --fs-uuid --set=root '{uuid}'
    if [ "$core_vault_t2" = "1" ]; then
        linux '/boot/vmlinuz-{t2}' {common} {t2_args}
        initrd '/boot/initrd.img-{t2}'
    else
        linux '/boot/vmlinuz-{generic}' {common}
        initrd '/boot/initrd.img-{generic}'
    fi
}}
"""
    )


def main():
    if not INSTALLATION.is_file():
        if os.environ.get("GRUB_DEFAULT") == ENTRY_ID:
            raise GrubConfigError(
                "core-vault-auto is the default, but the installed Vault report "
                "is missing; refusing to omit the required boot entry."
            )
        print("Vault automatic entry skipped: no installed target report.", file=sys.stderr)
        return
    installation = json.loads(INSTALLATION.read_text(encoding="utf-8"))
    if not isinstance(installation, dict) or installation.get("schema") != 1:
        raise GrubConfigError("Invalid installed Vault report.")
    manufacturers, models = load_models()
    generic, t2, parameters = load_profile()
    require_boot_pair(generic)
    require_boot_pair(t2)
    uuid = root_uuid()
    args = configured_arguments(parameters)
    # Only write stdout after every required installed-root input is ready.
    sys.stdout.write(render_installed(
        manufacturers, models, generic, t2, parameters, uuid, args
    ))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, GrubConfigError,
            subprocess.SubprocessError) as error:
        print(f"Vault automatic GRUB entry failed: {error}", file=sys.stderr)
        raise SystemExit(1)
