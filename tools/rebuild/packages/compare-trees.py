"""Compare the extracted Debian package payloads including paths, modes and link targets."""
import hashlib
import json
from pathlib import Path
import stat
import sys


def inventory(root):
    entries = {}
    for path in sorted(root.rglob('*')):
        attributes = path.lstat()
        entry = {'mode': oct(attributes.st_mode), 'uid': attributes.st_uid, 'gid': attributes.st_gid}
        if stat.S_ISLNK(attributes.st_mode):
            entry['link_target'] = str(path.readlink())
        elif stat.S_ISREG(attributes.st_mode):
            with path.open('rb') as stream:
                entry['elf'] = stream.read(4) == b'\x7fELF'
                stream.seek(0)
                entry['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        entries[str(path.relative_to(root))] = entry
    return entries


historical, rebuilt = (inventory(Path(p)) for p in sys.argv[1:3])
differences = {}
for path in sorted(historical.keys() | rebuilt.keys()):
    old, new = historical.get(path), rebuilt.get(path)
    if old != new:
        differences[path] = {'historical': old, 'rebuilt': new}
report = {'historical_paths': len(historical), 'rebuilt_paths': len(rebuilt),
          'differing_paths': len(differences), 'differences': differences}
Path(sys.argv[3]).write_text(json.dumps(report, indent=2) + '\n')
print('Extracted package payloads:', len(historical), 'historical paths,',
      len(rebuilt), 'rebuilt paths,', len(differences), 'different.')
