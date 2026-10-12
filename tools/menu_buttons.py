#!/usr/bin/env python3
"""Main-menu buttons (0013_017-026) in the style of the hand-made 0013_018.

  menu_buttons.py [--only 0013_019,...] [--force] [--font TTF]

Style (from the hand-made 0013_018.png in translation/images-handmade/ or images-approved/):
one or two words in bold italic capitals, white fill with a 2px red outline, over the blue/red band.
The band is rebuilt from 0013_018 with its lettering painted out, so no Japanese shows through.
Letters are DejaVu Sans Bold (or --font), drawn at half size without anti-aliasing, doubled, then
slanted. Long labels get smaller letters first and are only squeezed as a last resort.

Output goes to translation/images-handmade/, so the buttons behave like hand edits; existing files
are kept unless --force. 0013_018 is the template and is never overwritten; its regenerated version
goes to review/edit/. Edit LABELS below to change the wording.
"""
import argparse
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import styled  # noqa: E402

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FILL = (255, 255, 255, 255)
EDGE = (214, 8, 0, 255)

LABELS = {
    '0013_017': 'FIVE CROWNS',    # Path of the Five Crowns
    '0013_018': 'EXHIBITION',     # Exhibition Match (hand-made template)
    '0013_019': 'CARNIVAL',       # Champion Carnival
    '0013_020': 'TAG LEAGUE',     # World's Strongest Tag Determination League
    '0013_021': 'BATTLE ROYAL',
    '0013_022': 'DATA',           # Data Management (save / load)
    '0013_023': 'EDIT',           # Edit Wrestler
    '0013_024': 'OPTIONS',
    '0013_025': 'TITLE MATCH',
    '0013_026': 'SURVIVAL',       # Survival Match
}


def template_path():
    """The hand-made 0013_018 button the others are built from (in progress or approved)."""
    return next((d / '0013_018.png' for d in (paths.HANDMADE, paths.APPROVED) if (d / '0013_018.png').exists()),
                paths.HANDMADE / '0013_018.png')


def clean_band(template):
    """The template with its lettering (white fill + red outline) painted out along each row."""
    im = Image.open(template).convert('RGBA')
    W, H = im.size
    px = im.load()
    text = {(x, y) for y in range(H) for x in range(W) if px[x, y] in (FILL, EDGE)}
    grown = set(text)
    for x, y in list(text):
        for dx, dy in styled.NEIGH8:
            if 0 <= x + dx < W and 0 <= y + dy < H:
                grown.add((x + dx, y + dy))
    styled.inpaint_rows(im, grown)
    return im


def word_mask(text, cap=13, scale=2, shear=0.22, track=1, max_w=150):
    for size in range(40, 6, -1):
        f = ImageFont.truetype(FONT, size)
        top = f.getbbox('H')
        if top[3] - top[1] <= cap:
            break
    glyphs = []
    for ch in text:
        if ch == ' ':
            glyphs.append(None)
            continue
        b = f.getbbox(ch)
        g = Image.new('L', (b[2] - b[0] + 2, cap + 6), 0)
        d = ImageDraw.Draw(g)
        d.fontmode = '1'
        d.text((-b[0] + 1, -top[1] + 1), ch, font=f, fill=255)
        glyphs.append(g.crop(g.getbbox()))
    space = max(3, cap // 3)
    width = sum(g.width if g else space for g in glyphs) + track * (len(glyphs) - 1)
    img = Image.new('L', (width + 2, cap + 8), 0)
    x = 1
    for g in glyphs:
        if g is None:
            x += space + track
            continue
        img.paste(g, (x, 1 + max(0, cap - g.height)))  # bottom-align on the baseline
        x += g.width + track
    img = img.crop(img.getbbox())
    img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    w, h = img.size
    img = img.transform((w + int(h * shear) + 2, h), Image.AFFINE, (1, shear, -h * shear, 0, 1, 0),
                        resample=Image.NEAREST)
    img = img.crop(img.getbbox())
    if img.width > max_w:
        img = img.resize((max_w, img.height), Image.NEAREST)
    return img


def fitted_mask(text, max_w=150):
    """Largest letter size (with generous spacing like the template) that fits; squeeze only if needed."""
    for cap in (13, 12, 11, 10):
        m = word_mask(text, cap=cap, track=2, max_w=10 ** 6)
        if m.width <= max_w:
            return m
    return word_mask(text, cap=10, track=2, max_w=max_w)


def compose(band, text):
    out = band.copy()
    W, H = out.size
    px = out.load()
    m = fitted_mask(text)
    ox, oy = (W - m.width) // 2, (H - m.height) // 2
    fill = {(x + ox, y + oy) for y in range(m.height) for x in range(m.width) if m.getpixel((x, y))}
    edge = {(x + dx, y + dy) for x, y in fill for dx in range(-2, 3) for dy in range(-2, 3)
            if abs(dx) + abs(dy) <= 3} - fill
    for p in edge:
        if 0 <= p[0] < W and 0 <= p[1] < H:
            px[p] = EDGE
    for p in fill:
        px[p] = FILL
    return out


def main():
    global FONT
    ap = argparse.ArgumentParser(epilog=paths.FOLDER_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--only')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--font', default=FONT, help=f'TrueType font for the labels (default {FONT})')
    args = ap.parse_args(paths.configure(sys.argv[1:]))
    FONT = args.font
    template = template_path()
    if not template.exists():
        sys.exit(f'{paths.show(template)} (the hand-made template) is missing')
    band = clean_band(template)
    names = args.only.split(',') if args.only else list(LABELS)
    out_dir = paths.EDIT_REFS
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        orig = Image.open(paths.JAPANESE_IMAGES / f'{name}.png')
        img = styled.quantize(compose(band, LABELS[name]), orig, 256)
        if name == '0013_018':
            img.save(out_dir / '0013_018_generated.png')
            print(f'{name}: template left untouched; generated version -> {paths.show(out_dir / "0013_018_generated.png")}')
            continue
        target = paths.HANDMADE / f'{name}.png'
        if target.exists() and not args.force:
            print(f'{name}: {target.name} exists, skipped (use --force to regenerate)')
            continue
        img.save(target)
        shutil.copyfile(paths.JAPANESE_IMAGES / f'{name}.json', paths.HANDMADE / f'{name}.json')
        print(f'{name}: "{LABELS[name]}" -> {paths.show(target)}')


if __name__ == '__main__':
    main()
