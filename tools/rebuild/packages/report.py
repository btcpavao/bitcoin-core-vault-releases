"""Record full-archive and installed executable equality independently."""
import hashlib
import json
import re
import struct
from pathlib import Path
import subprocess
import sys
import tempfile

kind, original = sys.argv[1:3]
out = Path(sys.argv[3]) if len(sys.argv) == 4 else Path('/evidence')

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

# These section hashes help locate a mismatch. The complete ELF comparison above remains authoritative.
report['selected_elf_sections'] = {}
with tempfile.TemporaryDirectory() as directory:
    tmp = Path(directory)
    sections = ('.text', '.rodata', '.data', '.note.gnu.build-id')
    for side in ('expected', 'rebuilt'):
        args = ['objcopy']
        for section in sections:
            args += ['--dump-section', f'{section}={tmp / (side + section)}']
        subprocess.run([*args, out / f'{side}-{kind}.elf', tmp / 'discard.elf'], check=True)
    for section in sections:
        original_section = tmp / ('expected' + section)
        rebuilt_section = tmp / ('rebuilt' + section)
        if original_section.exists() and rebuilt_section.exists():
            old_hash, new_hash = digest(original_section), digest(rebuilt_section)
            report['selected_elf_sections'][section] = {
                'expected': old_hash, 'rebuilt': new_hash, 'match': old_hash == new_hash}
def build_id_descriptor(path, binary):
    # Check the GNU note structure before classifying any differing bytes as a build ID.
    headers = subprocess.check_output(['readelf', '--wide', '--sections', path], text=True)
    note = re.search(r'^\s*\[\s*\d+\]\s+\.note\.gnu\.build-id\s+NOTE\s+\S+\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s', headers, re.MULTILINE)
    if not note or binary[:6] != b'\x7fELF\x02\x01':
        return None
    offset, section_length = (int(v, 16) for v in note.groups())
    name_size, digest_size, note_type = struct.unpack_from('<III', binary, offset)
    if name_size != 4 or note_type != 3 or binary[offset + 12:offset + 16] != b'GNU\x00':
        return None
    start, end = offset + 16, offset + 16 + digest_size
    return (start, end) if end <= offset + section_length <= len(binary) else None

expected_elf = out / f'expected-{kind}.elf'
rebuilt_elf = out / f'rebuilt-{kind}.elf'
left, right = expected_elf.read_bytes(), rebuilt_elf.read_bytes()
descriptor = build_id_descriptor(expected_elf, left)
other_descriptor = build_id_descriptor(rebuilt_elf, right)
result = {
    'expected_length': len(left),
    'rebuilt_length': len(right),
    'differing_bytes': sum(a != b for a, b in zip(left, right)) + abs(len(left) - len(right)),
}
if descriptor and descriptor == other_descriptor:
    start, end = descriptor
    result.update({
        'gnu_build_id_offset': start,
        'gnu_build_id_length': end - start,
        'expected_gnu_build_id': left[start:end].hex(),
        'rebuilt_gnu_build_id': right[start:end].hex(),
        'all_bytes_outside_gnu_build_id_match': left[:start] == right[:start] and left[end:] == right[end:],
    })
report['full_installed_elf_byte_comparison'] = result

text = json.dumps(report, indent=2) + '\n'
(out / 'historical-match.json').write_text(text)
print(text)
