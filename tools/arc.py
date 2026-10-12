#!/usr/bin/env python3
"""ARC1 archive tool (DATALINK.ARC / DATAMATC.ARC).

Format (loader at 0x80019d94 / 0x80019efc in SLPS_018.49):
    "ARC1"  u32 count
    count x { u32 offset, u32 size, u32 flags }   offsets relative to the end of this table
    data

  arc.py unpack <arc> <outdir>     entries -> NNNN.<ext>; CMP1 entries are stored decompressed
  arc.py pack   <dir> <out.arc> <original.arc>   rebuild; unchanged entries are copied byte-for-byte

Repacking keeps every untouched entry at its original offset. A changed entry is written
in place if it fits in its original slot, otherwise appended at the end of the archive.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bpe  # noqa: E402


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def kind(b):
    m = b[:4]
    if m == b'\x10\0\0\0':
        return 'tim'
    if m == b'IMG3':
        return 'img3'
    if m == b'pQES':
        return 'seq'
    if m == b'pBAV':
        return 'vh'
    if m[:2] == b'M4':
        return 'm4'
    if m == b'\0\0\0\0':
        return 'vb'
    return 'bin'


def read_arc(data):
    assert data[:4] == b'ARC1', 'not an ARC1 archive'
    count = struct.unpack_from('<I', data, 4)[0]
    base = 8 + count * 12
    ents = [struct.unpack_from('<3I', data, 8 + 12 * i) for i in range(count)]
    return base, ents


def unpack(arc_path, out):
    data = Path(arc_path).read_bytes()
    base, ents = read_arc(data)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {'source': Path(arc_path).name, 'count': len(ents), 'size': len(data), 'entries': []}
    for i, (off, size, flags) in enumerate(ents):
        raw = data[base + off:base + off + size]
        cmp1 = raw[:4] == b'CMP1'
        body = bpe.unpack_cmp1(raw) if cmp1 else raw
        name = f'{i:04d}.{kind(body)}'
        (out / name).write_bytes(body)
        manifest['entries'].append({'index': i, 'file': name, 'offset': off, 'size': size, 'flags': flags,
                                    'cmp1': cmp1, 'sha1': sha1(body)})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1))
    print(f'unpacked {len(ents)} entries to {out}')


def pack(src, arc_path, original):
    src = Path(src)
    m = json.loads((src / 'manifest.json').read_text())
    orig = Path(original).read_bytes()
    obase, oents = read_arc(orig)
    count = m['count']
    base = 8 + count * 12
    out = bytearray(orig[:obase + max(o + s for o, s, _ in oents)])  # start from the original image
    table = []
    changed = 0
    end = len(out) - base
    for e in m['entries']:
        i = e['index']
        off, size, flags = oents[i]
        body = (src / e['file']).read_bytes()
        if sha1(body) == e['sha1']:
            table.append((off, size, flags))
            continue
        changed += 1
        blob = bpe.pack_cmp1(body, limit=size) if e['cmp1'] else body
        if len(blob) <= size:
            out[base + off:base + off + size] = blob.ljust(size, b'\0')
            table.append((off, len(blob), flags))
            print(f'  {e["file"]}: in place ({len(blob)}/{size} bytes)')
        else:
            end = (end + 3) & ~3
            out.extend(b'\0' * (base + end - len(out)))
            out += blob
            table.append((end, len(blob), flags))
            print(f'  {e["file"]}: appended at {end:#x} ({len(blob)} > {size} bytes)')
            end += len(blob)
    for i, (off, size, flags) in enumerate(table):
        struct.pack_into('<3I', out, 8 + 12 * i, off, size, flags)
    Path(arc_path).write_bytes(out)
    print(f'packed {count} entries ({changed} changed) -> {arc_path} ({len(out)} bytes, original {len(orig)})')


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == 'unpack':
        unpack(a[1], a[2])
    elif len(a) == 4 and a[0] == 'pack':
        pack(a[1], a[2], a[3])
    else:
        print(__doc__)
        sys.exit(1)
