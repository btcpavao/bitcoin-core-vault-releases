#!/usr/bin/python3
"""Reconstruct image fakeroot metadata after packages run in a user namespace.

A saved fakeroot database is inode-indexed. Dpkg can replace files outside that
fakeroot process and recycle an inode (for example, file -> symlink). Reusing
the old database can therefore mislabel the new type. Build a fresh database
from current filesystem types, base ownership/modes, and package archive data.
No target programs or device operations are executed.
"""
from pathlib import Path
import argparse
import json
import os
import re
import stat
import subprocess
import tarfile


def permissions(text):
    value = 0
    for index, bit in ((1,0o400),(2,0o200),(4,0o040),(5,0o020),(7,0o004),(8,0o002)):
        if text[index] != "-":
            value |= bit
    for index, bit in ((3,0o100),(6,0o010),(9,0o001)):
        if text[index] in "xst":
            value |= bit
    if text[3] in "sS": value |= 0o4000
    if text[6] in "sS": value |= 0o2000
    if text[9] in "tT": value |= 0o1000
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("rootfs", "base_listing", "input_manifest", "calamares_deb", "output_state"):
        parser.add_argument(argument, type=Path)
    parser.add_argument("--extra-package-manifest", type=Path)
    args = parser.parse_args()
    root = args.rootfs.resolve()
    if root == Path("/") or not (root / "var/lib/dpkg/status").is_file():
        raise ValueError("Expected the separate build image.")
    records = {}

    def identify(path):
        if not path.parent.resolve().is_relative_to(root) and path != root:
            raise ValueError("Image metadata path escapes root: " + str(path))
        actual = path.lstat()
        key = (actual.st_dev, actual.st_ino)
        return actual, key

    def record(path, uid=0, gid=0, mode=None, device=None):
        actual, key = identify(path)
        current_type = stat.S_IFMT(actual.st_mode)
        desired_mode = actual.st_mode if mode is None else (
            current_type | (0o777 if stat.S_ISLNK(actual.st_mode) else mode))
        if device is not None:
            desired_mode = stat.S_IFCHR | mode
        records[key] = dict(
            dev=actual.st_dev, ino=actual.st_ino, mode=desired_mode,
            uid=uid, gid=gid, nlink=actual.st_nlink,
            rdev=actual.st_rdev if device is None else device)

    def failed(error):
        raise error

    record(root)
    for directory, directories, files in os.walk(root, followlinks=False, onerror=failed):
        for name in directories + files:
            record(Path(directory) / name)

    pattern = re.compile(
        r"^(?P<mode>[bcdlps-][rwxStTs-]{9})\s+(?P<uid>\d+)/(?P<gid>\d+)\s+"
        r"(?P<size>.*?)\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+"
        r"squashfs-root(?P<path>/.*)?$")
    preserved = 0
    devices = 0
    for line in args.base_listing.read_text().splitlines():
        match = pattern.fullmatch(line)
        if not match:
            raise ValueError("Unrecognized numeric base metadata: " + line[:180])
        mode = match["mode"]
        relative = (match["path"] or "").lstrip("/")
        if mode[0] == "l":
            relative = relative.split(" -> ", 1)[0]
        path = root / relative
        if not path.exists() and not path.is_symlink():
            continue
        device = None
        if mode[0] in "bc":
            if mode[0] != "c":
                raise ValueError("Unexpected block device in base image.")
            major, minor = map(int, match["size"].split(","))
            device = os.makedev(major, minor)
            devices += 1
        record(path, int(match["uid"]), int(match["gid"]), permissions(mode), device)
        preserved += 1

    inputs = json.loads(args.input_manifest.read_text())
    packages = [Path(item["local_path"]) for item in
                [inputs["kernel"], *inputs["graphics_firmware"]]]
    packages.append(args.calamares_deb)
    if args.extra_package_manifest:
        extra = json.loads(args.extra_package_manifest.read_text())
        if extra.get("schema") != 1 or not extra.get("artifacts"):
            raise ValueError("Expected authenticated extra package metadata.")
        packages.extend(Path(item["local_path"]) for item in extra["artifacts"])
    for package in packages:
        process = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", str(package)],
                                   stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                for item in archive:
                    relative = Path(item.name.removeprefix("./"))
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError("Unsafe archive path.")
                    path = root / relative
                    if not path.exists() and not path.is_symlink():
                        raise ValueError("Installed package path missing: " + str(relative))
                    record(path, item.uid, item.gid, item.mode)
        finally:
            process.stdout.close()
            result = process.wait()
        if result:
            raise RuntimeError("Cannot read package metadata: " + str(package))

    # Root inode attributes in a Debian package's './' header are not intended
    # to change the already assembled root; preserve the base directory mode.
    record(root, 0, 0, 0o755)
    args.output_state.write_text("\n".join(
        "dev={dev:x},ino={ino:d},mode={mode:o},uid={uid:d},gid={gid:d},nlink={nlink:d},rdev={rdev:d}".format(**records[key])
        for key in sorted(records)) + "\n")
    args.output_state.chmod(0o600)
    print(json.dumps({
        "action": "reconstructed image packaging metadata",
        "inodes": len(records), "base_paths_preserved": preserved,
        "device_nodes_preserved": devices,
        "source": "current inode types plus base and authenticated package metadata",
        "tests_run": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
