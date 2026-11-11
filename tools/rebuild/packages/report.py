"""Record full-archive and installed executable equality independently."""
import hashlib
import json
from pathlib import Path
import sys

kind, original = sys.argv[1:]
out = Path('/evidence')

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

report = {'component': kind, 'comparison': {}}
for name, old, new in [
    ('whole_deb', original, out / f'{kind}-rebuilt.deb'),
    ('installed_elf', out / f'expected-{kind}.elf', out / f'rebuilt-{kind}.elf'),
]:
    expected = digest(old)
    actual = digest(new)
    report['comparison'][name] = {'expected': expected, 'rebuilt': actual, 'match': expected == actual}

text = json.dumps(report, indent=2) + '\n'
(out / 'historical-match.json').write_text(text)
print(text)
