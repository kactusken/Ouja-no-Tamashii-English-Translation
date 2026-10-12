#!/usr/bin/env python3
"""TIM / IMG3 <-> PNG converter.

  gfx.py export <file|dir> <outdir>     write indexed PNGs (palette indices preserved) + <name>.json
  gfx.py import <root> <png>...         write edited PNGs back into <root>/<ARC>/<entry> (in place)
  gfx.py sheet  <dir> <outdir>          paged contact sheets of exported PNGs, for spotting text

PNG names are <source-stem>_<image#>.png; the .json sidecar records the source entry (relative,
e.g. DATALINK/0013.img3) and image record so `import` knows where the pixels go. Edit PNGs in
indexed mode (Aseprite, GIMP, ...) so palette indices survive; RGB PNGs are mapped to the nearest
palette colour on import.

IMG3 layout (custom multi-image container, sometimes wrapped in CMP1):
    "IMG3" u32 n_images u32 n_cluts u32 n_pairs u32 0
    n_pairs x { u16 clut_record (0xFFFF = chosen at runtime), u16 image_index }
    (n_cluts + n_images) x { u32 data_offset, u32 mode, u16 vram_x, u16 vram_y, u16 w, u16 h }
    data      (mode: 0 = 16bpp/CLUT, 8 = 4bpp, 9 = 8bpp; w is in 16-bit VRAM units)
"""
import json
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

BPP = {0: 16, 2: 16, 8: 4, 9: 8, 1: 8}  # IMG3 mode / TIM bpp -> bits per pixel


def ps1_rgba(c):
    r, g, b = c & 31, (c >> 5) & 31, (c >> 10) & 31
    a = 0 if c == 0 else 255
    return (r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2, a)


def rgba_ps1(p):
    r, g, b, a = p
    if a < 128:
        return 0
    c = (r >> 3) | (g >> 3) << 5 | (b >> 3) << 10
    return c or 0x8000  # opaque black must set STP, or it becomes transparent


class Img:
    """One image: pixel indices (or 16-bit colours) plus where they live in the source file."""

    def __init__(self, bpp, width, height, data_off, clut, meta):
        self.bpp, self.width, self.height, self.data_off, self.clut, self.meta = bpp, width, height, data_off, clut, meta


def parse_tim(b):
    flags = struct.unpack_from('<I', b, 4)[0]
    bpp = {0: 4, 1: 8, 2: 16, 3: 24}[flags & 3]
    pos = 8
    clut = None
    if flags & 8:
        ln, cx, cy, cw, ch = struct.unpack_from('<I4H', b, pos)
        clut = list(struct.unpack_from(f'<{cw}H', b, pos + 12))  # first palette row
        pos += ln
    ln, x, y, w, h = struct.unpack_from('<I4H', b, pos)
    width = w * 16 // bpp
    return [Img(bpp, width, h, pos + 12, clut, {'kind': 'tim', 'vram': [x, y, w, h]})]


def parse_img3(b):
    n_img, n_clut, n_pairs = struct.unpack_from('<3I', b, 4)
    pairs = [struct.unpack_from('<2H', b, 0x14 + 4 * i) for i in range(n_pairs)]
    rs = 0x14 + 4 * n_pairs
    recs = [struct.unpack_from('<2I4H', b, rs + 16 * i) for i in range(n_clut + n_img)]
    cluts = [list(struct.unpack_from(f'<{r[4] * r[5]}H', b, r[0])) for r in recs[:n_clut]]
    clut_of = {img: c for c, img in pairs}
    out = []
    last = None
    for i, (off, mode, x, y, w, h) in enumerate(recs[n_clut:]):
        bpp = BPP[mode]
        c = clut_of.get(i, 0xFFFF)
        guessed = c == 0xFFFF
        if not guessed:
            last = c
        ci = last if guessed else c
        clut = cluts[ci] if ci is not None and bpp != 16 else None
        out.append(Img(bpp, w * 16 // bpp, h, off, clut,
                       {'kind': 'img3', 'record': n_clut + i, 'vram': [x, y, w, h], 'clut_record': ci,
                        'clut_guessed': guessed}))
    return out


def parse(path):
    b = Path(path).read_bytes()
    if b[:4] == b'IMG3':
        return b, parse_img3(b)
    if b[:4] == b'\x10\0\0\0':
        return b, parse_tim(b)
    raise ValueError(f'{path}: not a TIM or IMG3')


def decode(b, im):
    n = im.width * im.height
    off = im.data_off
    if im.bpp == 4:
        idx = []
        for byte in b[off:off + n // 2]:
            idx += (byte & 15, byte >> 4)
        return idx
    if im.bpp == 8:
        return list(b[off:off + n])
    return list(struct.unpack_from(f'<{n}H', b, off))


def encode_into(buf, im, idx):
    off = im.data_off
    if im.bpp == 4:
        buf[off:off + len(idx) // 2] = bytes(idx[i] | idx[i + 1] << 4 for i in range(0, len(idx), 2))
    elif im.bpp == 8:
        buf[off:off + len(idx)] = bytes(idx)
    else:
        struct.pack_into(f'<{len(idx)}H', buf, off, *idx)


def to_png(b, im):
    px = decode(b, im)
    if im.bpp == 16:
        img = Image.new('RGBA', (im.width, im.height))
        img.putdata([ps1_rgba(c) for c in px])
        return img
    ncol = 1 << im.bpp
    clut = (im.clut or [])[:ncol]
    if not clut:  # no palette known: grey ramp
        clut = [((i * 31 // (ncol - 1)) * 0x421) | 0x8000 for i in range(ncol)]
    clut = clut + [0] * (ncol - len(clut))
    img = Image.new('P', (im.width, im.height))
    img.putpalette([v for c in clut for v in ps1_rgba(c)[:3]])
    img.putdata(px)
    img.info['transparency'] = bytes(0 if c == 0 else 255 for c in clut)
    return img


def export(src, outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in Path(src).glob('*') if p.suffix in ('.tim', '.img3')) if Path(src).is_dir() else [Path(src)]
    n = 0
    for f in files:
        try:
            b, imgs = parse(f)
        except (ValueError, KeyError, struct.error) as e:
            print(f'skipping {f.name}: {e}')
            continue
        for k, im in enumerate(imgs):
            if im.width == 0 or im.height == 0:
                continue
            name = f'{f.stem}_{k:03d}.png'
            to_png(b, im).save(outdir / name)
            meta = dict(im.meta, source=f'{f.parent.name}/{f.name}', image=k, bpp=im.bpp, width=im.width, height=im.height)
            (outdir / (name[:-4] + '.json')).write_text(json.dumps(meta))
            n += 1
    print(f'exported {n} images from {len(files)} files to {outdir}')


def import_png(root, png, quiet=False):
    png = Path(png)
    meta = json.loads(png.with_suffix('.json').read_text())
    src = Path(root) / meta['source']
    b, imgs = parse(src)
    im = imgs[meta['image']]
    img = Image.open(png)
    if img.size != (im.width, im.height):
        raise ValueError(f'{png}: size {img.size} != original {(im.width, im.height)}')
    if im.bpp == 16:
        px = [rgba_ps1(p) for p in img.convert('RGBA').get_flattened_data()]
    elif img.mode == 'P':
        px = list(img.get_flattened_data())
        if max(px) >= 1 << im.bpp:
            raise ValueError(f'{png}: palette index {max(px)} too large for {im.bpp}bpp')
    else:
        clut = im.clut or []
        cols = [ps1_rgba(c) for c in clut[:1 << im.bpp]]
        cache = {}

        def nearest(p):
            if p[3] < 128:
                return next((i for i, c in enumerate(clut) if c == 0), 0)
            if p not in cache:
                cache[p] = min(range(len(cols)), key=lambda i: (cols[i][3] == 0, sum((cols[i][j] - p[j]) ** 2 for j in range(3))))
            return cache[p]
        px = [nearest(p) for p in img.convert('RGBA').get_flattened_data()]
    buf = bytearray(b)
    encode_into(buf, im, px)
    src.write_bytes(buf)
    if not quiet:
        print(f"imported {png.name} -> {src.name} image {meta['image']}")


def sheet(d, outdir, width=1024, max_height=1400):
    """Paged contact sheets of every PNG in d, labelled with their names."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    pages = []
    cur = []
    x = y = rowh = 0

    def flush():
        if not cur:
            return
        canvas = Image.new('RGBA', (width, y + rowh + 14), (60, 60, 90, 255))
        dr = ImageDraw.Draw(canvas)
        for p, im, px, py in cur:
            canvas.alpha_composite(im, (px, py + 12))
            dr.text((px, py), p.stem, fill=(255, 255, 0, 255))
        canvas.save(outdir / f'sheet_{len(pages):03d}.png')
        pages.append(len(cur))

    for p in sorted(Path(d).glob('*.png')):
        im = Image.open(p).convert('RGBA')
        if im.width > width:
            im = im.resize((width, im.height * width // im.width))
        if x + im.width > width:
            x, y, rowh = 0, y + rowh + 14, 0
        if y + im.height > max_height:
            flush()
            cur, x, y, rowh = [], 0, 0, 0
        cur.append((p, im, x, y))
        x += im.width + 4
        rowh = max(rowh, im.height)
    flush()
    print(f'{outdir}: {len(pages)} sheets, {sum(pages)} images')


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == 'export':
        export(a[1], a[2])
    elif len(a) >= 3 and a[0] == 'import':
        for p in a[2:]:
            import_png(a[1], p)
    elif len(a) == 3 and a[0] == 'sheet':
        sheet(a[1], a[2])
    else:
        print(__doc__)
        sys.exit(1)
