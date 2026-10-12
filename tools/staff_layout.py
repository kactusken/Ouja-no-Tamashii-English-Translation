#!/usr/bin/env python3
"""Re-lay out translated credit / ending lines in STAFF.BIN.

Credit records (12 bytes, found by their string pointer):
    s16 x        offset from screen centre (screen is 512 px wide), left edge of the line
    u16 prop     1 = proportional spacing (narrow glyphs advance 10 px, space 8 px, others 16 px)
                 0 = every character advances 16 px
    char *text
    u32 next     delay / gap before the next line

English in 16 px monospace is far too wide, so every translated line gets prop = 1 and a new x:
centred lines (the prose passages) are re-centred; column-aligned lines keep their indent unless
they would run past the right edge.

  staff_layout.py <original STAFF.BIN> <translated STAFF.BIN> [--report]
"""
import csv
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
from text import OVERLAY_BASE as BASE  # noqa: E402

HALF_WIDTH = 256       # screen is 512 px wide, x measured from the centre
RIGHT_LIMIT = 236      # keep a margin for overscan
NARROW = {0x140, 0x143, 0x144, 0x15b, 0x168, 0x169, 0x16a}


def is_narrow(code):
    code &= 0x7fff
    return code in NARROW or 0x24f <= code < 0x24f + 0x4c or 0x340 <= code < 0x340 + 0x57


def read_str(d, off):
    end = d.index(b'\0', off)
    while (end - off) % 2:  # the renderer reads 2-byte units; a NUL low byte can't end a char
        end = d.index(b'\0', end + 1)
    return d[off:end]


def width(sjis, prop):
    w = 0
    for i in range(0, len(sjis) - 1, 2):
        code = sjis[i] << 8 | sjis[i + 1]
        if prop and is_narrow(code):
            w += 8 if code & 0x7fff == 0x140 else 10
        else:
            w += 16
    return w


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def records(d, string_addrs):
    for i in range(4, len(d) - 7, 4):
        p = struct.unpack_from('<I', d, i)[0]
        if p in string_addrs:
            xf = struct.unpack_from('<I', d, i - 4)[0]
            if xf >> 16 in (0, 1):
                yield i - 4, s16(xf & 0xffff), xf >> 16, p


def relayout(orig, new, report=False):
    orig = bytes(orig)
    d = bytearray(new)
    # string addresses in the original, to locate records (record positions don't move)
    with open(paths.TEXT_DIR / 'STAFF.csv', encoding='utf-8') as f:
        addrs = {int(r['ram'], 16) for r in csv.DictReader(f)}
    changed = problems = 0
    for rec, x, prop, p in records(orig, addrs):
        o_text = read_str(orig, p - BASE)
        n_ptr = struct.unpack_from('<I', d, rec + 4)[0]
        n_text = read_str(d, n_ptr - BASE)
        if n_text == o_text:
            continue
        o_w = width(o_text, prop)
        # prose passages: monospace lines centred to within a char; credit columns (roles at -50/-80,
        # names at -10) keep their indent
        centred = prop == 0 and x != -10 and abs(x + o_w / 2) <= 12
        n_w = width(n_text, 1)
        if centred:
            nx = -(n_w // 2)
        else:
            nx = min(x, RIGHT_LIMIT - n_w)
        if nx < -HALF_WIDTH + 8 or nx + n_w > HALF_WIDTH - 8:
            problems += 1
            print(f'  too wide ({n_w} px): {n_text.decode("shift_jis")}')
        struct.pack_into('<I', d, rec, (nx & 0xffff) | (1 << 16))
        changed += 1
        if report:
            print(f'  {rec:#07x} x {x:5d}->{nx:5d} {"centre" if centred else "column"} w={n_w:3d} '
                  f'{n_text.decode("shift_jis")}')
    print(f'  layout: {changed} credit lines repositioned, {problems} too wide')
    return bytes(d), problems


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__)
        sys.exit(1)
    out, bad = relayout(Path(a[0]).read_bytes(), Path(a[1]).read_bytes(), '--report' in a)
    Path(a[1]).write_bytes(out)
    sys.exit(1 if bad else 0)
