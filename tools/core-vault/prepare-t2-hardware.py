#!/usr/bin/python3
"""Stage the pinned T2 kernel and graphics firmware for a disposable image build.

This prepares input files only. It never installs packages, runs an installer,
changes disks, or executes tests. --input-dir reuses previously downloaded bytes.
The normal build entry point calls it before live-build assembles its local APT
repository from config/packages.chroot.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tools/core-vault/manifests/t2-hardware-release.json"
STAGING = ROOT / "config/packages.chroot"
RELEASE_PATTERN = r"[A-Za-z0-9][A-Za-z0-9.+_~-]{0,159}"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path, item):
    require(path.is_file() and not path.is_symlink(), f"Missing or unsafe pinned input: {path}")
    require(path.stat().st_size == item["size"] and file_hash(path) == item["sha256"],
            f"Pinned input differs from the recorded bytes: {path}")


def load_manifest():
    raw = MANIFEST.read_bytes()
    require(len(raw) <= 128 * 1024, "The T2 hardware manifest is too large.")
    data = json.loads(raw)
    require(data.get("schema") == 1, "Unsupported T2 hardware manifest schema.")
    release = data.get("kernel_release")
    require(isinstance(release, str) and re.fullmatch(RELEASE_PATTERN, release)
            and "-t2-" in release, "Invalid pinned T2 kernel release.")
    items = data.get("artifacts")
    require(isinstance(items, list) and len(items) == 3, "Expected exactly three pinned hardware packages.")
    expected_packages = {"linux-image-" + release, "firmware-amd-graphics", "firmware-intel-graphics"}
    require(all(isinstance(item, dict) for item in items), "Invalid hardware package record.")
    require({item.get("package") for item in items} == expected_packages,
            "The pinned hardware package set is incomplete or unexpected.")
    for item in items:
        package, version, arch = (item.get(name) for name in ("package", "version", "architecture"))
        require(isinstance(version, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+:~_-]*", version),
                "Invalid hardware package version.")
        expected_arch = "amd64" if package.startswith("linux-image-") else "all"
        require(arch == expected_arch, "Unexpected hardware package architecture.")
        require(item.get("filename") == f"{package}_{version}_{arch}.deb",
                "Unexpected hardware package filename.")
        require(type(item.get("size")) is int and 0 < item["size"] < 1024 ** 3,
                "Invalid pinned hardware package size.")
        require(isinstance(item.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), "Invalid hardware package SHA-256.")
        parsed = urlparse(item.get("url", ""))
        require(parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.fragment, "Hardware inputs must use HTTPS URLs.")
    records = data.get("signed_metadata")
    require(isinstance(records, list) and records, "Missing archived signed metadata provenance.")
    for record in records:
        relative = Path(record["path"])
        require(not relative.is_absolute() and ".." not in relative.parts
                and relative.parts[:2] == ("build-assets", "core-vault-t2-v1"),
                "Invalid signed metadata path.")
        verify_file(ROOT / relative, record)
    package_list = ROOT / "config/package-lists/core-vault-t2.list.chroot"
    wanted = {item["package"] + "=" + item["version"] for item in items}
    actual = {line.strip() for line in package_list.read_text().splitlines()
              if line.strip() and not line.lstrip().startswith("#")}
    require(actual == wanted, "The hardware package list does not match the pinned manifest.")
    return raw, data


def copy_checked(source, destination, item):
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = source.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        require(total <= item["size"], "Hardware download exceeds the pinned size: " + item["filename"])
        digest.update(chunk)
        destination.write(chunk)
    require(total == item["size"] and digest.hexdigest() == item["sha256"],
            "Hardware download differs from the pinned bytes: " + item["filename"])


def stage_package(item, input_directory):
    destination = STAGING / item["filename"]
    if destination.exists() or destination.is_symlink():
        verify_file(destination, item)
        print("Reused pinned hardware input:", destination.name)
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".hardware-", suffix=".part", dir=STAGING, delete=False) as output:
            temporary = Path(output.name)
            if input_directory is not None:
                source = input_directory / item["filename"]
                require(source.is_file() and not source.is_symlink(), f"Missing cached hardware input: {source}")
                with source.open("rb") as stream:
                    copy_checked(stream, output, item)
            else:
                request = Request(item["url"], headers={"User-Agent": "BitcoinCoreVault-PinnedHardware/1"})
                with urlopen(request, timeout=60) as stream:
                    require(urlparse(stream.geturl()).scheme == "https", "Hardware download redirected away from HTTPS.")
                    copy_checked(stream, output, item)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, destination)
        print("Staged pinned hardware input:", destination.name)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, help="Reuse the three pinned .deb files from this directory.")
    arguments = parser.parse_args()
    raw, data = load_manifest()
    STAGING.mkdir(parents=True, exist_ok=True)
    expected = {item["filename"] for item in data["artifacts"]}
    for pattern in ("linux-image-*-t2-*.deb", "firmware-amd-graphics_*.deb", "firmware-intel-graphics_*.deb"):
        for path in STAGING.glob(pattern):
            require(path.name in expected, f"Another hardware package is staged; move it aside before building: {path}")
    for item in data["artifacts"]:
        stage_package(item, arguments.input_dir)
    for base in ("config/includes.chroot", "tools/core-vault/runtime-template"):
        destination = ROOT / base / "usr/share/core-vault/t2-hardware-release.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        require(not destination.is_symlink(), f"Unsafe hardware manifest destination: {destination}")
        if not destination.exists() or destination.read_bytes() != raw:
            destination.write_bytes(raw)
            destination.chmod(0o644)
    print("Pinned T2 kernel and graphics firmware are ready for image assembly.")


if __name__ == "__main__":
    main()
