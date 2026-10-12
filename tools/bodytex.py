#!/usr/bin/env python3
"""Export wrestler body textures (DATALINK entries 779 + 8*model + slot) as PNG.

  bodytex.py [model ...]       -> review/body-textures/m<model>_s<slot>_<entry>.png

File layout (entries with a 0x50 header): u32 0x50 ... +0x20 u32 0x80000000|word offset of the pixel
data, +0x24 u32 0x80000000|word offset of the CLUTs; records from 0x3c, 0x18 bytes each:
{u16 vram_x, u16 vram_y, u16 w (16-bit units), u16 h, u32 data offset, u16 0, u16 clut_row, u32 flags};
pixels are 8bpp; CLUTs are 256 colours each, CLUT row 496 = first CLUT in the file.
MATCH.BIN loads entry 0x30b + model*8 + colour (0x80096c20).
"""
import struct
import sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

FIRST = 0x30b


def entry(n):
    return next((paths.UNPACKED / paths.ARCHIVE).glob(f'{n:04d}.*')).read_bytes()


def decode(d, clut_base_row=496):
    pix = (struct.unpack_from('<I', d, 0x20)[0] & 0x7fffffff) * 4
    clt = (struct.unpack_from('<I', d, 0x24)[0] & 0x7fffffff) * 4
    recs, o = [], 0x3c
    while o + 0x18 <= pix:
        x, y, w, h, off, cl = struct.unpack_from('<4HII', d, o)
        if not (w and h):
            break
        recs.append((x, y, w, h, off, cl >> 16))
        o += 0x18
    ncl = (len(d) - clt) // 512
    pals = []
    for k in range(ncl):
        cols = struct.unpack_from('<256H', d, clt + k * 512)
        pals.append([(((c & 31) * 255) // 31, (((c >> 5) & 31) * 255) // 31, (((c >> 10) & 31) * 255) // 31,
                      0 if c == 0 else 255) for c in cols])
    x0 = min(r[0] for r in recs); y0 = min(r[1] for r in recs)
    x1 = max(r[0] + r[2] for r in recs); y1 = max(r[1] + r[3] for r in recs)
    img = Image.new('RGBA', ((x1 - x0) * 2, y1 - y0), (0, 0, 0, 0))
    for x, y, w, h, off, row in recs:
        pal = pals[(row - clut_base_row) % ncl]
        px = d[pix + off:pix + off + w * 2 * h]
        tile = Image.new('RGBA', (w * 2, h))
        tile.putdata([pal[v] for v in px])
        img.paste(tile, ((x - x0) * 2, y - y0))
    return img


def main(argv):
    models = [int(a) for a in argv] or list(range(51))
    out = paths.REVIEW / 'body-textures'
    out.mkdir(parents=True, exist_ok=True)
    for m in models:
        for s in range(8):
            n = FIRST + 8 * m + s
            try:
                img = decode(entry(n))
            except (StopIteration, ValueError, struct.error) as e:
                print(f'model {m} slot {s} ({n}): {e}')
                continue
            img.save(out / f'm{m:02d}_s{s}_{n:04d}.png')
    print(f'wrote {paths.show(out)}')


if __name__ == '__main__':
    main(paths.configure(sys.argv[1:]))
