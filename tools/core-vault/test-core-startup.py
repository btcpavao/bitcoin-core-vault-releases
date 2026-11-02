#!/usr/bin/python3
"""Compatibility entrypoint for the current production-launcher regression.

Use: python3 tools/core-vault/test-core-startup.py --core-root ./chroot

The old direct-exec/fd9 stub no longer represented the bubblewrap launcher.
Delegate to the synthetic RAM integration fixture, which runs the actual
launcher, inner helper and official Core. Its installed-storage limitations
are printed explicitly; no host shutdown or privileged mount is performed.
"""
import os
from pathlib import Path
import sys


if __name__ == '__main__':
    harness = Path(__file__).resolve().with_name('test-core-launcher.py')
    os.execv(sys.executable, [sys.executable, str(harness), *sys.argv[1:]])
