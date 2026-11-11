"""Compare two extracted, public images by path without executing a target file."""
import base64
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

def inventory(root):
    records, links = {}, {}
    def scan(directory):
        for item in sorted(os.scandir(directory), key=lambda e: e.name):
            path = Path(item.path)
            name = str(path.relative_to(root))
            info = path.lstat()
            rec = dict(mode=oct(info.st_mode), uid=info.st_uid, gid=info.st_gid, mtime=info.st_mtime_ns)
            if stat.S_ISREG(info.st_mode):
                with path.open('rb') as data:
                    rec['sha256'] = hashlib.file_digest(data, 'sha256').hexdigest()
                rec['bytes'] = info.st_size
                if info.st_nlink > 1:
                    group = links.setdefault((info.st_dev, info.st_ino), name)
                    rec['hardlink_group'] = group
            elif stat.S_ISLNK(info.st_mode):
                rec['target'] = os.readlink(path)
            elif stat.S_ISBLK(info.st_mode) or stat.S_ISCHR(info.st_mode):
                rec['rdev'] = info.st_rdev
            xattrs = os.listxattr(path, follow_symlinks=False)
            if xattrs:
                rec['xattrs'] = {a: base64.b64encode(os.getxattr(path, a, follow_symlinks=False)).decode() for a in sorted(xattrs)}
            records[name] = rec
            if stat.S_ISDIR(info.st_mode):
                scan(path)
    scan(root)
    return records

first, second = (inventory(Path(arg)) for arg in sys.argv[1:3])
count = 0
for name in sorted(first.keys() | second.keys()):
    a, b = first.get(name), second.get(name)
    if a == b:
        continue
    if a is None or b is None:
        print(json.dumps({'path': name, 'first': a, 'second': b}))
    else:
        print(json.dumps({'path': name, 'changes': {k: [a.get(k), b.get(k)] for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)}}))
    count += 1
print(f'{len(first)} versus {len(second)} paths, {count} differences', file=sys.stderr)
