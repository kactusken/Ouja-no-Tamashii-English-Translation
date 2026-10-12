#!/usr/bin/env python3
"""Side-by-side contact sheets: original Japanese image | English image that will ship.

  compare.py [--out review/compare] [--filter TEXT] [--category CAT] [--keep] [--scale 2]

The English side is what the build uses: a hand-made PNG in translation/images-handmade/,
else the frozen approved render, else the automatic render (cache/auto-renders, refreshed first).
Duplicates are shown once. Labels: image name, then the source of the English side
  HAND   translation/images-handmade/        APPR  translation/images-approved/
  AUTO   automatic plain-text render         KEEP  stays Japanese (only with --keep)
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import render  # noqa: E402

COLOURS = {'HAND': (120, 255, 120), 'APPR': (255, 255, 255), 'AUTO': (200, 220, 255), 'KEEP': (150, 150, 150)}


def english_side(name, status):
    for tag, d in (('HAND', paths.HANDMADE), ('APPR', paths.APPROVED), ('AUTO', paths.AUTO_RENDERS / paths.ARCHIVE)):
        if (d / f'{name}.png').exists():
            return tag, Image.open(d / f'{name}.png')
    if status == 'keep':
        return 'KEEP', Image.open(paths.JAPANESE_IMAGES / f'{name}.png')
    return None, None


def main():
    ap = argparse.ArgumentParser(epilog=paths.FOLDER_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=None, help='default review/compare (review/compare/filtered for filtered runs)')
    ap.add_argument('--filter', default='', help='only images whose name/Japanese/English contains this')
    ap.add_argument('--category', default='', help='only this graphics.csv category (menu, button, ...)')
    ap.add_argument('--keep', action='store_true', help='also show images that stay Japanese')
    ap.add_argument('--scale', type=int, default=2)
    ap.add_argument('--width', type=int, default=1600)
    ap.add_argument('--height', type=int, default=1800)
    args = ap.parse_args(paths.configure(sys.argv[1:]))

    render.run(paths.AUTO_RENDERS / paths.ARCHIVE)  # make sure the automatic renders reflect graphics.csv

    items = []
    for r in render.read_rows():
        if r['dup_of'] or (r['status'] == 'keep' and not args.keep):
            continue
        if args.category and r['category'] != args.category:
            continue
        if args.filter and args.filter.lower() not in ' '.join((r['image'], r['japanese'], r['english'])).lower():
            continue
        tag, en = english_side(r['image'], r['status'])
        if not tag:
            continue
        jp = Image.open(paths.JAPANESE_IMAGES / f"{r['image']}.png")
        items.append((r['image'], tag, jp, en))

    s = args.scale
    out = Path(args.out) if args.out else paths.COMPARE / ('filtered' if (args.filter or args.category) else '')
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob('compare_*.png'):
        old.unlink()
    tiles = []
    for name, tag, jp, en in items:
        w, h = jp.width * s, jp.height * s
        t = Image.new('RGBA', (w * 2 + 6, h + 13), (60, 60, 90, 255))
        t.alpha_composite(jp.convert('RGBA').resize((w, h), Image.NEAREST), (0, 13))
        t.alpha_composite(en.convert('RGBA').resize((w, h), Image.NEAREST), (w + 6, 13))
        d = ImageDraw.Draw(t)
        d.line([(w + 2, 13), (w + 2, 13 + h)], fill=(255, 255, 0, 255), width=2)
        d.text((1, 0), f'{name} {tag}', fill=COLOURS[tag] + (255,))
        if t.width > args.width:  # very wide images: scale the tile down to fit the page
            t = t.resize((args.width, t.height * args.width // t.width), Image.NEAREST)
        tiles.append(t)

    pages, cur, x, y, rowh = [], [], 0, 0, 0
    for t in tiles:
        if x + t.width > args.width:
            x, y, rowh = 0, y + rowh + 8, 0
        if y + t.height > args.height and cur:
            pages.append((cur, y))
            cur, x, y, rowh = [], 0, 0, 0
        cur.append((t, x, y))
        x += t.width + 10
        rowh = max(rowh, t.height)
    if cur:
        pages.append((cur, y + rowh))
    for k, (page, _) in enumerate(pages):
        h = max(y + t.height for t, x, y in page)
        c = Image.new('RGBA', (args.width, h + 4), (30, 30, 40, 255))
        for t, x, y in page:
            c.alpha_composite(t, (x, y))
        c.save(out / f'compare_{k:03d}.png')
    print(f'{len(items)} images on {len(pages)} pages -> {out}/compare_NNN.png')


if __name__ == '__main__':
    main()
