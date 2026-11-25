#!/usr/bin/python3
"""Finish the local Vault T2 image after isolated dpkg package configuration.

Run under the clean fakeroot state reconstructed after image package configuration. This builds files
and records provenance; it never starts Vault, Calamares, GRUB or an installer.
"""
from pathlib import Path, PurePosixPath
import argparse
import datetime
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile

CALAMARES_VERSION = "3.3.14-1+corevault10localrolesfix1"
BASE_ISO_SHA256 = "cee87635f966e1cce4576abe9723ea99155da4a3f65217accf38521471a0a8b3"
PERSISTENT = [
    "usr/share/core-vault/t2-models.json",
    "usr/share/core-vault/t2-hardware-release.json",
    "etc/core-vault/kernel-profile.json",
    "usr/lib/core-vault/t2_hardware.py",
    "usr/lib/core-vault/t2_grub.py",
    "etc/grub.d/09_core_vault_auto",
    "etc/initramfs-tools/hooks/core-vault-t2",
    "usr/local/sbin/core-vault-grub-install",
]
DEVICE_SETTINGS = [
    'usr/lib/core-vault/settings/vault_device_state.py',
    'usr/local/libexec/core-vault-device-settings',
    'etc/polkit-1/rules.d/49-core-vault-device-settings.rules',
    'usr/share/polkit-1/actions/org.bitcoin-core-vault.device-settings.policy',
    'usr/local/libexec/core-vault-prepare',
    'usr/lib/core-vault/settings/vault_input.py',
    'usr/lib/core-vault/settings/vault_pointer.py',
    'usr/lib/core-vault/settings/vault_input_ui.py',
    'usr/lib/core-vault/settings/device_profiles.py',
    'usr/lib/core-vault/settings/device_profile_data.py',
    'usr/lib/core-vault/settings/vault_settings.py',
    'usr/share/core-desktop/core_display.py',
    'usr/share/core-desktop/core_display_settings.py',
    'usr/lib/core-vault/settings/vault_time.py',
    'usr/lib/core-vault/settings/vault_time_ui.py',
    'usr/local/libexec/core-vault-time',
    'usr/share/core-vault/icons/settings.svg',
    'usr/share/core-vault/icons/settings-icon.json',
    'usr/share/core-vault/licenses/elementary-xfce/SETTINGS-NOTICE.txt',
    'usr/lib/core-vault/guide_content.py',
]
PERSISTENT += DEVICE_SETTINGS
DESKTOP_TUNING = [
    'usr/local/bin/core-vault-home',
    'usr/local/bin/core-vault-taskbar',
    'usr/share/core-vault/icons/clock.svg',
]
PERSISTENT += DESKTOP_TUNING

INSTALLER = ["usr/lib/core-vault-installer/" + name for name in (
    "disk_safety.py", "install_plan.py", "boot_finalize.py", "target.py")] + [
    "usr/local/sbin/core-vault-installer",
    "usr/local/bin/core-vault-installer-session",
]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fields(text):
    result = {}
    current = None
    for line in text.splitlines():
        if line.startswith((" ", "\t")) and current:
            result[current] += "\n" + line
        elif ":" in line:
            current, value = line.split(":", 1)
            result[current] = value.lstrip(" ")
    return result


def target(root, relative, follow=True):
    path = root / relative
    resolved = path.resolve(strict=False) if follow else path.parent.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Path escapes image: " + str(relative))
    return path


def copy_overlay(root, source, relative):
    origin = source / "config/includes.chroot" / relative
    destination = target(root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ValueError("Expected a regular overlay destination: " + relative)
    destination.write_bytes(origin.read_bytes())
    mode = stat.S_IMODE(origin.stat().st_mode) & ~0o022
    if relative.startswith("etc/sudoers.d/"):
        mode = 0o440
    destination.chmod(mode)
    os.chown(destination, 0, 0)
    for parent in destination.parents:
        if parent == root:
            break
        os.chown(parent, 0, 0)


def restore_package_owners(root, package):
    # dpkg ran in a user namespace where UID 0 maps to the build user's UID.
    # Restore original archive ownership in fakeroot's persistent metadata.
    process = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", str(package)],
                               stdout=subprocess.PIPE)
    count = 0
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for item in archive:
                name = item.name.removeprefix("./")
                if name in ("", "."):
                    continue
                relative = PurePosixPath(name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe package member: " + name)
                path = target(root, str(relative), follow=False)
                if not path.exists() and not path.is_symlink():
                    raise ValueError("Installed package file missing: " + name)
                os.lchown(path, item.uid, item.gid)
                count += 1
    finally:
        process.stdout.close()
        status = process.wait()
    if status:
        raise RuntimeError("Cannot read package payload: " + str(package))
    return count


def disable_smart_monitoring(root, source):
    # Supply smartctl to the partition scanner without enabling a background
    # monitoring daemon in the offline Vault. Only package-created links are
    # removed; unknown regular overrides are not silently replaced.
    removed = []
    for pattern in ("etc/rc?.d/[SK][0-9][0-9]smartmontools",
                    "etc/systemd/system/*.wants/smartmontools.service"):
        for path in root.glob(pattern):
            if not path.is_symlink():
                raise ValueError("Unexpected monitoring enablement path: " + str(path))
            removed.append(str(path.relative_to(root)))
            path.unlink()
    masks = {}
    for name in ("smartmontools.service", "smartd.service"):
        relative = "etc/systemd/system/" + name
        origin = source / "config/includes.chroot" / relative
        if not origin.is_symlink() or str(origin.readlink()) != "/dev/null":
            raise ValueError("Expected the explicit source monitoring mask: " + relative)
        destination = target(root, relative, follow=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            destination.unlink()
        elif destination.exists():
            raise ValueError("Unexpected regular monitoring service override: " + relative)
        destination.symlink_to("/dev/null")
        os.lchown(destination, 0, 0)
        masks[relative] = "/dev/null"
    return {"source_symlinks": masks, "removed_enablement_links": sorted(removed),
            "policy": "smartctl available on demand; smartd background service masked"}


def root_owned_tree(path):
    if not path.exists():
        return
    os.lchown(path, 0, 0)
    for directory, directories, files in os.walk(path, followlinks=False):
        for name in directories + files:
            os.lchown(Path(directory) / name, 0, 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rootfs", "source", "input_manifest", "calamares_deb", "evidence"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--installer-input-manifest", type=Path, required=True)
    parser.add_argument("--candidate-metadata", type=Path)
    args = parser.parse_args()
    root = args.rootfs.resolve()
    source = args.source.resolve()
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    if root == Path("/") or 'VERSION_ID="13"' not in target(root, "etc/os-release").read_text():
        raise ValueError("Expected a separate Debian 13 image.")
    if target(root, "etc/core-vault/installation.json").exists():
        raise ValueError("Installed target marker must not be in the live image.")

    inputs = json.loads(args.input_manifest.read_text())
    installer_inputs = json.loads(args.installer_input_manifest.read_text())
    if installer_inputs.get("schema") != 1 or not installer_inputs.get("artifacts"):
        raise ValueError("Expected authenticated installer dependency inputs.")
    artifacts = [inputs["kernel"], *inputs["graphics_firmware"], *installer_inputs["artifacts"]]
    package_records = {}
    paragraphs = target(root, "var/lib/dpkg/status").read_text().strip().split("\n\n")
    installed = {entry["Package"]: entry for entry in map(fields, paragraphs)}
    for artifact in artifacts:
        package = Path(artifact["local_path"])
        if sha(package) != artifact["verified_sha256"] or package.stat().st_size != artifact["verified_bytes"]:
            raise ValueError("The authenticated package input changed: " + str(package))
        entry = installed[artifact["Package"]]
        if entry.get("Status") != "install ok installed" or entry["Version"] != artifact["Version"]:
            raise ValueError("Image package is not configured: " + artifact["Package"])
        package_records[artifact["Package"]] = {
            "version": entry["Version"], "sha256": sha(package),
            "archive_entries": restore_package_owners(root, package),
        }
    if installed["calamares"].get("Status") != "install ok installed" or installed["calamares"]["Version"] != CALAMARES_VERSION:
        raise ValueError("Expected the newly compiled native Calamares package.")
    package_records["calamares"] = {
        "version": CALAMARES_VERSION, "sha256": sha(args.calamares_deb),
        "archive_entries": restore_package_owners(root, args.calamares_deb),
    }

    # Dpkg and the three observed triggers rewrite only root-owned build data.
    for relative in ("var/lib/dpkg", "var/lib/initramfs-tools", "var/cache/ldconfig"):
        root_owned_tree(target(root, relative))
    for relative in ("etc/ld.so.cache", "var/log/dpkg.log",
                     "usr/share/applications/mimeinfo.cache",
                     "usr/share/icons/hicolor/icon-theme.cache"):
        path = target(root, relative)
        if path.exists():
            os.chown(path, 0, 0)
    for path in target(root, "boot").iterdir():
        if path.is_file():
            os.chown(path, 0, 0)
    for release in ("6.12.116+deb13-amd64", "6.18.64-1-t2-trixie"):
        root_owned_tree(target(root, "usr/lib/modules/" + release))

    monitoring = disable_smart_monitoring(root, source)
    overlays = list(INSTALLER) + list(PERSISTENT)
    # The active timezone name is mutable device configuration, not an immutable payload file.
    overlays += ["etc/timezone"]
    overlays += [str(path.relative_to(source / "config/includes.chroot"))
                 for path in (source / "config/includes.chroot/etc/calamares").rglob("*")
                 if path.is_file() and not path.is_symlink()]
    for relative in overlays:
        copy_overlay(root, source, relative)
    for directory in ("usr/lib/core-vault-installer", "usr/lib/core-vault"):
        for cache in target(root, directory).rglob("__pycache__"):
            if cache.is_dir():
                shutil.rmtree(cache)
    for name in ("core-vault-build-inputs", "core-vault-build-native", "core-vault-build-installer"):
        path = target(root, "run/" + name)
        if path.exists():
            path.rmdir()

    sources = {
        relative: sha(source / "config/includes.chroot" / relative)
        for relative in overlays
    }
    for relative in (
        "tools/local-build/write-live-boot-menu.py",
        "tools/core-vault/calamares/tests/test_raw_partition_roles.py",
        "tools/core-vault/calamares/lifecycle_patch.py",
        "tools/core-vault/calamares/advanced_patch.py",
        "tools/core-vault/calamares/patch_calamares_source.py",
        "tools/core-vault/calamares/shared/PartitionPage.h",
        "tools/core-vault/calamares/shared/PartitionPage.cpp",
        "tools/core-vault/calamares/shared/PlanMethods.cpp.inc",
        "tools/core-vault/calamares/shared/Review.cpp.inc",
        "tools/core-vault/calamares/shared/CoreOfflineGuard.h",
    ):
        sources[relative] = sha(source / relative)
    profile = json.loads(target(root, "etc/core-vault/kernel-profile.json").read_text())
    record = {
        "schema": 1, "product": "vault", "candidate": "local-t2-auto-reserve-fix-20261124",
        "fixes": [
            "new partition active flags begin empty so native jobs write reviewed BIOS/EFI/MBR flags",
            "strict installed partition role comparison retained with precise diagnostics",
            "explicit failed installation exits nonzero after closing the failure page",
        ],
        "previous_candidate_sha256": "775c1077b78d1d817bffe970dad6bf94ee121afcf14c99df60fb167f980c080a",
        "validation_at_packaging": {
            "targeted_policy_tests": 8,
            "policy_result": "pass",
            "policy_command": "python3 -B tools/core-vault/calamares/tests/test_raw_partition_roles.py",
            "vm_validation": "recorded separately against the final ISO SHA-256",
        },
        "built_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "base_source_commit": "b5ca3eaed69e9c0af47cd783ef3ae6a2d58da741",
        "base_iso_sha256": BASE_ISO_SHA256,
        "source_state": "local uncommitted changes",
        "packages": package_records, "source_files": sources,
        "disk_monitoring": monitoring,
        "kernel_profile": profile, "automatic_hardware_selection": "exact Apple vendor and T2 SMBIOS model before kernel load; live and installed",
        "architecture": "amd64", "firmware_modes": ["x86_64 UEFI", "Legacy BIOS"],
        "advanced_tables": {"efi": ["gpt"], "bios": ["gpt", "dos"]},
        "tests_run": True, "vm_installations_run": False,
        "hardware_installations_run": False, "github_push": False, "signed": False,
        "publication": "local only; manual hardware trial pending",
        "package_configuration": "dpkg in isolated user, mount and PID namespace; no host package changes",
    }
    if args.candidate_metadata is not None:
        candidate = json.loads(args.candidate_metadata.read_text())
        required = {"candidate", "fixes", "previous_candidate_sha256", "validation_at_packaging"}
        if set(candidate) != required or not isinstance(candidate["candidate"], str):
            raise ValueError("Invalid local candidate metadata.")
        if (not isinstance(candidate["fixes"], list)
                or not all(isinstance(item, str) for item in candidate["fixes"])
                or not isinstance(candidate["validation_at_packaging"], dict)):
            raise ValueError("Invalid local candidate validation metadata.")
        record.update(candidate)
        record["candidate_metadata_sha256"] = sha(args.candidate_metadata)
    marker = target(root, "etc/core-vault/local-build.json")
    marker.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    marker.chmod(0o644)
    os.chown(marker, 0, 0)
    manifest = target(root, "etc/core-vault/installer-payload.json")
    payload = json.loads(manifest.read_text())
    payload["calamares_version"] = CALAMARES_VERSION
    payload["files"].pop("etc/timezone", None)
    for relative in PERSISTENT + ["etc/core-vault/local-build.json"]:
        payload["files"][relative] = sha(target(root, relative))
    # Installer-only files disappear during target configuration and must not
    # enter the persistent payload list used by post-install verification.
    payload["files"] = dict(sorted(payload["files"].items()))
    manifest.write_text(json.dumps(payload, indent=2) + "\n")
    os.chown(manifest, 0, 0)
    (evidence / "local-build.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    shutil.copy2(args.input_manifest, evidence / "kernel-input-manifest.json")
    shutil.copy2(args.installer_input_manifest, evidence / "installer-input-manifest.json")
    (evidence / "image-packages.tsv").write_text("\n".join(sorted(
        item["Package"] + "\t" + item["Version"]
        for item in installed.values() if item.get("Status") == "install ok installed")) + "\n")
    print("Vault payload and provenance assembled; runtime validation is recorded separately.")


if __name__ == "__main__":
    main()
