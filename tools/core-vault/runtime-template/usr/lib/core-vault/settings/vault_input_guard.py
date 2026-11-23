"""Fail closed before saving Vault device preferences outside the private RAM home."""
import os
from pathlib import Path
import subprocess


def require_ram_home():
    home = Path.home()
    expected = Path('/home/vault')
    ram = Path('/run/core-vault/home')
    try:
        if home != expected or expected.is_symlink() or ram.is_symlink():
            raise ValueError()
        if os.stat(expected).st_dev != os.stat(ram).st_dev:
            raise ValueError()
        result = subprocess.run(
            ['/usr/bin/findmnt', '--noheadings', '--output', 'FSTYPE', '--target', str(expected)],
            capture_output=True, text=True, timeout=5, check=True)
        if result.stdout.strip() != 'tmpfs':
            raise ValueError()
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ValueError('Vault device settings require the active private RAM session.') from None


def require_ram_path(path):
    require_ram_home()
    path = Path(path)
    home = Path('/home/vault')
    try:
        if not path.is_relative_to(home) or '..' in path.parts:
            raise ValueError()
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError()
        existing = path.parent
        while not existing.exists():
            existing = existing.parent
        if os.stat(existing).st_dev != os.stat(home).st_dev:
            raise ValueError()
    except (OSError, ValueError):
        raise ValueError('Vault device preferences must stay in the private RAM home.') from None
