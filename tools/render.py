#!/usr/bin/env python3
"""Render English into the game's text graphics, driven by translation/graphics.csv.

  render.py [--out DIR] [--only IMG,IMG...] [--sheet PREVIEW.png]

For each row with an `english` value (and status todo/done) the original indexed PNG from
review/images-japanese is redrawn and written to DIR (default cache/auto-renders/DATALINK) with
its .json sidecar, ready for `gfx.py import` / build.py. Rows marked dup_of reuse the result of
the image they duplicate. Images in translation/images-handmade/ take priority at build time.

status 'manual'/'keep' rows are skipped (hand-drawn art goes in translation/images-handmade/).
Every translated image is frozen (status 'done', file in translation/images-approved/) and copied
as-is at build time - nothing is redrawn unless asked. After changing a row's English, font, align or
boxes, re-render it with:   render.py --regen 0013_034[,0013_035...]
Rows still marked 'todo' are new: plain ones render automatically, styled ones keep the Japanese art
until approved; --preview-all renders everything for review (see `review` column).

Optional graphics.csv columns:
  font    large-bold | large | medium-bold | medium | tiny   force a font (default: first that fits)
  align   left | center | quote       override alignment (quote: left, last line flush right)
  boxes   x,y,w,h;x,y,w,h             composite images: one box per text item, english items
                                      separated by ' | ' (erased and redrawn inside each box only)
English text may contain ' / ' to force line breaks.

Styles (detected per image):
  plain   two colours, transparent background + one text colour (the bulk of the menus,
          descriptions and name plates): cleared and redrawn.
  other   not handled yet - reported and skipped.
"""
import argparse
import csv
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fonts  # noqa: E402
import paths  # noqa: E402
import styled  # noqa: E402


def transparent_indices(im):
    t = im.info.get('transparency')
    if t is None:
        return set()
    if isinstance(t, int):
        return {t}
    return {i for i, a in enumerate(t) if a == 0}


def greedy(font, part, width):
    lines, cur = [], ''
    for word in part.split():
        cand = word if not cur else cur + ' ' + word
        if font.width(cand) <= width:
            cur = cand
        elif not cur or font.width(word) > width:
            return None
        else:
            lines.append(cur)
            cur = word
    return lines + [cur]


def even(font, part, width, n):
    """Break `part` into exactly n lines: lines filled close to `width`, and a last line at least
    half as wide (no orphaned word), chosen to minimise the squared slack."""
    words = part.split()
    w = lambda i, j: font.width(' '.join(words[i:j]))
    best = {(len(words), 0): (0, None)}  # (start word, lines used) -> (cost, next break)
    for k in range(1, n + 1):
        for i in range(len(words) - 1, -1, -1):
            for j in range(i + 1, len(words) + 1):
                lw = w(i, j)
                if lw > width:
                    break
                rest = best.get((j, k - 1))
                if rest is None:
                    continue
                cost = (max(0, width // 2 - lw) * 4) ** 2 if j == len(words) else (width - lw) ** 2
                if (i, k) not in best or cost + rest[0] < best[(i, k)][0]:
                    best[(i, k)] = (cost + rest[0], j)
    lines, i, k = [], 0, n
    while i < len(words):
        j = best[(i, k)][1]
        lines.append(' '.join(words[i:j]))
        i, k = j, k - 1
    return lines


def wrap(font, text, width):
    """Word wrap; ' / ' forces a break. A part that needs several lines keeps the fewest lines but
    is laid out evenly (see even()), so it never ends on a stray word.
    Returns lines or None if a word can't fit."""
    lines = []
    for part in text.split(' / '):
        got = greedy(font, part, width)
        if got is None:
            return None
        lines += even(font, part, width, len(got)) if len(got) > 1 else got
    return lines


def layout(text, W, H, fontset, force=None, margin=1):
    for f in fontset:
        if force and f.name != force:
            continue
        lines = wrap(f, text, W - 2 * margin)
        if lines is None:
            continue
        h = len(lines) * f.line_height - f.line_gap
        if h <= H:
            return f, lines, h
    return None


def draw_lines(px, W, H, f, lines, x0, y0, align, colour, box_w):
    for k, line in enumerate(lines):
        w = f.width(line)
        if align == 'center':
            x = x0 + (box_w - w) // 2
        elif align == 'quote' and k == len(lines) - 1:  # attribution line flush right
            x = x0 + box_w - w
        else:
            x = x0
        y = y0 + k * f.line_height
        for i, ch in enumerate(line):
            if ch == ' ':
                x += f.space
                continue
            g = f.glyph(ch)
            for r, row in enumerate(g):
                for c, v in enumerate(row):
                    if v == '#' and 0 <= x + c < W and 0 <= y + r < H:
                        px[x + c, y + r] = colour
            x += len(g[0])
            if i < len(line) - 1 and line[i + 1] != ' ':
                x += f.spacing


class MaskCanvas:
    """Collects glyph pixels as a set so styled rendering can decorate them."""
    def __init__(self):
        self.pts = set()

    def __setitem__(self, xy, v):
        self.pts.add(xy)


def glyph_mask(f, lines, box, align):
    """Lay out lines centred (or left-aligned) in box=(x, y, w, h); returns (mask, top, height)."""
    bx, by, bw, bh = box
    h = len(lines) * f.line_height - f.line_gap
    top = by + (bh - h) // 2
    c = MaskCanvas()
    draw_lines(c, 10 ** 6, 10 ** 6, f, lines, bx, top, align, 1, bw)
    return c.pts, top, h


def render_styled(im, row, fontset, background, region, ncolors, box_override=None):
    """Text with outline/shadow/gradient on a known background (transparent or a set's plate)."""
    W, H = im.size
    opaque_bg = any(p[3] for p in background.get_flattened_data())
    st = styled.learn(im, region, background if opaque_bg else None)
    xs = [p[0] for p in region]
    ys = [p[1] for p in region]
    rx0, rx1, ry0, ry1 = min(xs), max(xs), min(ys), max(ys)
    m = st.margin
    # available box: the original text's band, widened to the image (minus margin) around its centre
    cx = (rx0 + rx1) // 2
    half = min(cx, W - 1 - cx) - (2 if W >= 64 else 0)  # narrow labels need every pixel
    if box_override:
        bx, by, bw, bh = box_override
    else:
        bx, bw = (cx - half, 2 * half + 1) if W >= 64 else (0, W)
        by, bh = max(0, ry0 - 2), min(H, ry1 + 3) - max(0, ry0 - 2)
        if bh < 10:
            by, bh = 0, H
    res = layout(row['english'], bw - 2 * m, bh - 2 * m, fontset, row.get('font') or None)
    if res is None:
        res = layout(row['english'], bw - 2 * m, H - 2 * m, fontset, row.get('font') or None)
        by, bh = 0, H
    if res is None and (len(st.rings) > 1 or m > 1):
        # small labels: keep a 1px outline so the text gets the room
        st.rings = st.rings[:1]
        if st.shadow:
            st.shadow = (min(st.shadow[0], 1), min(st.shadow[1], 1), st.shadow[2])
        m = st.margin = 1
        res = layout(row['english'], bw - 2 * m, H - 2 * m, fontset + [fonts.TINY], row.get('font') or None)
    if res is None:
        return None, 'does not fit'
    f, lines, _ = res
    align = row.get('align') or 'center'
    if opaque_bg:
        st = styled.ensure_legible(st, background, (bx, by, bw, bh))
    mask, top, th = glyph_mask(f, lines, (bx + m, by + m, bw - 2 * m, bh - 2 * m), align)
    canvas = background.copy()
    styled.paint(canvas, mask, st, top, th)
    return styled.quantize(canvas, im, ncolors), f'{f.name}, {len(lines)} line(s), styled {st}'


_plates = {}


def set_members(name, size):
    """Exported images of the same entry and size (sets of buttons/banners share artwork)."""
    entry = name.split('_')[0]
    return [p for p in sorted(paths.JAPANESE_IMAGES.glob(f'{entry}_*.png')) if Image.open(p).size == size]


def render_boxes(im, row, fontset, ncolors):
    """Several text items, each in its own box: `boxes` = 'x,y,w,h;...', english = 'a | b | ...'."""
    boxes = [tuple(int(v) for v in b.split(',')) for b in row['boxes'].split(';') if b.strip()]
    texts = [t.strip() for t in row['english'].split('|')]
    if len(boxes) != len(texts):
        return None, f'boxes/text count mismatch ({len(boxes)} vs {len(texts)})'
    canvas = im.convert('RGBA')
    used = []
    for (bx, by, bw, bh), t in zip(boxes, texts):
        crop = canvas.crop((bx, by, bx + bw, by + bh))
        cpx = crop.load()
        if sum(1 for p in crop.get_flattened_data() if p[3] == 0) > 0.3 * bw * bh:
            region = {p for p in ((x, y) for y in range(bh) for x in range(bw)) if cpx[p][3]}
            clean = Image.new('RGBA', crop.size, (0, 0, 0, 0))
        else:
            _, region = styled.line_background(crop, union=True)
            clean = styled.inpaint_smooth(crop, region)
        opaque_bg = any(c[3] for c in clean.get_flattened_data())
        st = styled.learn(crop, region, clean if opaque_bg else None) if region else styled.Style()
        if not st.rows:
            st.rows = [(255, 255, 255, 255)]
        else:  # small labels: one fill colour (a gradient row can read as a strikethrough)
            st.rows = [Counter(st.rows).most_common(1)[0][0]]
        if opaque_bg:
            st = styled.ensure_legible(st, clean, (0, 0, bw, bh))
        if not t:  # empty item: just erase the original text in this box
            canvas.paste(clean, (bx, by))
            used.append('erase')
            continue
        m = st.margin
        res = layout(t, bw - 2 * m, bh - 2 * m, fontset, row.get('font') or None)
        if res is None:
            return None, f'"{t}" does not fit its box'
        f, lines, _ = res
        mask, top, th = glyph_mask(f, lines, (m, m, bw - 2 * m, bh - 2 * m), row.get('align') or 'center')
        styled.paint(clean, mask, st, top, th)
        canvas.paste(clean, (bx, by))
        used.append(f.name)
    return styled.quantize(canvas, im, ncolors), f'boxes: {", ".join(used)}'


def render_other(im, row, fontset):
    name = row['image']
    meta = json.loads((paths.JAPANESE_IMAGES / f'{name}.json').read_text())
    ncolors = 1 << meta['bpp'] if meta['bpp'] <= 8 else 0
    if not ncolors:
        return None, 'unsupported'
    if row.get('boxes'):
        return render_boxes(im, row, fontset, ncolors)
    members = set_members(name, im.size)
    rgba = im.convert('RGBA')
    transparent = sum(1 for p in rgba.get_flattened_data() if p[3] == 0) / (im.width * im.height)
    plate = None
    if len(members) >= 3:
        key = tuple(sorted(str(p) for p in members))
        if key not in _plates:
            _plates[key] = styled.text_free_plate([Image.open(p) for p in members])
        plate, distinct = _plates[key]
        if distinct < 3:
            plate = None
        if plate is not None and sum(1 for p in plate.get_flattened_data() if p[3]) < 0.03 * im.width * im.height:
            plate = None  # shared background is empty: treat as transparent text
    area = im.width * im.height
    if plate is not None:
        # texture (brushed metal, scanlines) differs a little from the shared background, text a lot
        region = styled.dense_band(styled.region_vs_background(im, plate, tol=110), im.size)
        if region and len(region) <= 0.6 * area:
            return render_styled(im, row, fontset, plate, region, ncolors)
    if transparent > 0.15:
        # text (with its outline/shadow) on transparency: every opaque pixel is text
        region = styled.region_opaque(im)
        return render_styled(im, row, fontset, Image.new('RGBA', im.size, (0, 0, 0, 0)), region, ncolors)
    # opaque single image: estimate the background per row/column and paint over the text
    _, region = styled.line_background(im)
    band = styled.dense_band(region, im.size)
    if band:  # inside the text band, also catch faint glow/antialias pixels
        xs = [p[0] for p in band]
        ys = [p[1] for p in band]
        _, faint = styled.line_background(im, tol=24)
        band |= {p for p in faint if min(xs) <= p[0] <= max(xs) and min(ys) <= p[1] <= max(ys)}
    region = band
    if region and len(region) <= 0.6 * area:
        return render_styled(im, row, fontset, styled.inpaint_region(im, region), region, ncolors)
    return None, 'unsupported'


def classify(im):
    tr = transparent_indices(im)
    cnt = Counter(im.get_flattened_data())
    opaque = [k for k in cnt if k not in tr]
    if tr and len(opaque) == 1:
        return 'plain', next(iter(tr & set(cnt)), next(iter(tr))), opaque[0]
    return 'other', None, None


def render_plain(im, row, fontset, bg, fg):
    W, H = im.size
    px = im.load()
    pts = [(x, y) for y in range(H) for x in range(W) if px[x, y] == fg]
    x0o = min(p[0] for p in pts)
    x1o = max(p[0] for p in pts)
    y0o = min(p[1] for p in pts)
    y1o = max(p[1] for p in pts)
    multi = (y1o - y0o) > 20
    align = row.get('align') or ('left' if row['category'] == 'description' or (multi and x0o <= 6) else 'center')
    res = layout(row['english'], W, H, fontset, row.get('font') or None)
    if res is None:
        return None, 'does not fit'
    f, lines, h = res
    out = im.copy()
    opx = out.load()
    for y in range(H):
        for x in range(W):
            opx[x, y] = bg
    if align in ('left', 'quote'):
        widest = max(f.width(l) for l in lines)
        x0 = min(x0o, max(1, W - 1 - widest))
        y0 = y0o if y0o + h <= H else max(0, (H - h) // 2)
        # quote: the attribution ends where the Japanese one did (or under the widest line)
        box_w = W - x0 if align == 'left' else min(W - 1, max(x1o + 1, x0 + widest)) - x0
    else:
        x0, box_w = 0, W
        cy = (y0o + y1o) // 2
        y0 = min(max(0, cy - h // 2), H - h)
    draw_lines(opx, W, H, f, lines, x0, y0, align, fg, box_w)
    return out, f'{f.name}, {len(lines)} line(s), {align}'


def main():
    ap = argparse.ArgumentParser(epilog=paths.FOLDER_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', help='default cache/auto-renders/DATALINK')
    ap.add_argument('--only')
    ap.add_argument('--sheet')
    ap.add_argument('--freeze', metavar='IMG,IMG|done',
                    help='copy current renders from --out into translation/images-approved/ ("done" = all approved rows)')
    ap.add_argument('--regen', metavar='IMG,IMG',
                    help='re-render these images from graphics.csv and re-freeze them (before/after in review/edit/)')
    ap.add_argument('--preview-all', action='store_true',
                    help='also render styled images not yet approved (status done), for review')
    args = ap.parse_args(paths.configure(sys.argv[1:]))
    args.out = args.out or str(paths.AUTO_RENDERS / paths.ARCHIVE)
    if args.freeze:
        freeze(Path(args.out), args.freeze)
        return
    if args.regen:
        regen(args.regen.split(','))
        return
    run(args.out, args.only, args.sheet, args.preview_all)


def regen(names):
    """Re-render images from their graphics.csv rows, replace the frozen copies, show before/after."""
    tmp = paths.CACHE / 'regen'
    if tmp.exists():
        shutil.rmtree(tmp)
    run(tmp, ','.join(names), None, preview_all=True)
    paths.EDIT_REFS.mkdir(parents=True, exist_ok=True)
    paths.APPROVED.mkdir(parents=True, exist_ok=True)
    rows = read_rows()
    for name in names:
        new = tmp / f'{name}.png'
        if not new.exists():
            print(f'{name}: not rendered (see {tmp / "report.txt"}) - frozen copy left unchanged')
            continue
        old = paths.APPROVED / f'{name}.png'
        tiles = [('japanese', paths.JAPANESE_IMAGES / f'{name}.png'), ('before', old if old.exists() else None), ('after', new)]
        s = 3
        jp = Image.open(paths.JAPANESE_IMAGES / f'{name}.png')
        w, h = jp.width * s, jp.height * s
        sheet = Image.new('RGBA', (w, (h + 14) * 3), (40, 40, 40, 255))
        d = ImageDraw.Draw(sheet)
        for k, (label, path) in enumerate(tiles):
            d.text((2, k * (h + 14)), label, fill=(255, 255, 0, 255))
            if path:
                im = Image.open(path).convert('RGBA').resize((w, h), Image.NEAREST)
                bg = Image.new('RGBA', (w, h), (255, 0, 255, 255))
                bg.alpha_composite(im)
                sheet.paste(bg, (0, k * (h + 14) + 12))
        sheet.save(paths.EDIT_REFS / f'{name}_regen.png')
        shutil.copyfile(new, old)
        for r in rows:
            if r['image'] == name:
                r['status'] = 'done'
        print(f'{name}: re-rendered and frozen; before/after: {paths.show(paths.EDIT_REFS / (name + "_regen.png"))}')
    with open(paths.GRAPHICS_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def read_rows():
    with open(paths.GRAPHICS_CSV, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def freeze(out, which):
    rows = read_rows()
    names = [r['image'] for r in rows if r['status'] == 'done' and not r['dup_of']] if which == 'done' \
        else which.split(',')
    paths.APPROVED.mkdir(parents=True, exist_ok=True)
    n = 0
    for name in names:
        if (out / f'{name}.png').exists():
            shutil.copyfile(out / f'{name}.png', paths.APPROVED / f'{name}.png')
            n += 1
    print(f'froze {n} renders into {paths.APPROVED}')


def run(out_dir, only_list=None, sheet_path=None, preview_all=False):
    fontset = fonts.fontset((paths.GAME_FILES / 'STAFF.BIN').read_bytes())
    out = Path(out_dir)
    if out.exists() and not only_list:
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = read_rows()
    only = set(only_list.split(',')) if only_list else None
    by_img = {r['image']: r for r in rows}
    stats = Counter()
    done = {}
    report = []
    shorten = []
    candidates = [r for r in rows if not r['dup_of'] and r['english'].strip() and r['status'] not in ('manual', 'keep')]
    todo = [r for r in candidates if not only or r['image'] in only]
    # images of the same kind on the same screen (entry, size, category) share one font so a set
    # of buttons or name plates looks uniform: the group uses the largest font that 90% of its
    # members fit; the few that don't shrink individually
    best = {}
    for r in candidates:  # whole set, so a single re-render keeps the same font as its siblings
        if r.get('font'):
            continue
        W, H = int(r['width']), int(r['height'])
        res = layout(r['english'], W, H, fontset)
        k = (r['image'].split('_')[0], W, H, r['category'])
        best.setdefault(k, []).append(fontset.index(res[0]) if res else len(fontset) - 1)
    group_font = {}
    for k, idxs in best.items():
        gf = next(i for i in range(len(fontset)) if sum(x <= i for x in idxs) >= 0.9 * len(idxs))
        group_font[k] = min(gf, len(fontset) - 2)  # never force a whole group into the tiny font
    for r in todo:
        im = Image.open(paths.JAPANESE_IMAGES / f"{r['image']}.png")
        style, bg, fg = classify(im)
        k = (r['image'].split('_')[0], im.width, im.height, r['category'])
        sub = fontset[group_font.get(k, 0):] if not r.get('font') else fontset
        if r['status'] == 'done' and (paths.APPROVED / f"{r['image']}.png").exists() and not preview_all:
            done[r['image']] = Image.open(paths.APPROVED / f"{r['image']}.png")
            stats['approved (frozen)'] += 1
            continue
        if r['english'].strip() == '(hand-made)':
            # an image approved from a hand edit: only its frozen file is valid - never draw the placeholder
            stats['hand-made image missing its approved file (original kept)'] += 1
            print(f"  warning: {r['image']} is marked hand-made but {paths.APPROVED.name}/{r['image']}.png is missing"
                  f" - keeping the original (fix: edit.py reset {r['image']})")
            continue
        if style == 'plain' and not r.get('boxes'):
            res, info = render_plain(im, r, sub, bg, fg)
        else:
            if r['status'] != 'done' and not preview_all:
                stats['styled, awaiting approval (kept Japanese)'] += 1
                continue
            res, info = render_other(im, r, sub)
            if res is None and info == 'unsupported':
                stats['skipped (style not handled yet)'] += 1
                continue
        if res is None:
            stats['does not fit'] += 1
            report.append(f"{r['image']} {im.size}: does not fit: {r['english']}")
            continue
        stats['rendered'] += 1
        done[r['image']] = res
        if info.startswith('tiny') and not r.get('font'):
            shorten.append(f"{r['image']} {im.size}: {r['english']}")
        report.append(f"{r['image']} {im.size}: {info}: {r['english']}")
    for r in rows:  # duplicates reuse their original's rendering
        if r['dup_of'] in done and (not only or r['image'] in only or r['dup_of'] in only):
            done[r['image']] = done[r['dup_of']]
            stats['duplicates'] += 1
    for name, img in done.items():
        img.save(out / f'{name}.png')
        shutil.copyfile(paths.JAPANESE_IMAGES / f'{name}.json', out / f'{name}.json')
    (out / 'report.txt').write_text('\n'.join(report) + '\n', encoding='utf-8')
    (out / 'shorten.txt').write_text('Only fit in the tiny font - consider shorter English:\n'
                                     + '\n'.join(shorten) + '\n', encoding='utf-8')
    if shorten:
        print(f'{len(shorten)} images only fit the tiny font -> {out / "shorten.txt"}')
    print(', '.join(f'{v} {k}' for k, v in stats.items()), f'-> {out}')
    if sheet_path:
        sheet(done, by_img, sheet_path)
    return out


def sheet(done, by_img, path, width=1200, scale=2):
    items = []
    for name, img in done.items():
        if by_img[name]['dup_of']:
            continue
        o = Image.open(paths.JAPANESE_IMAGES / f'{name}.png').convert('RGBA')
        n = img.convert('RGBA')
        pair = Image.new('RGBA', (o.width * scale, (o.height * 2 + 3) * scale + 10), (90, 0, 90, 255))
        pair.alpha_composite(o.resize((o.width * scale, o.height * scale), Image.NEAREST), (0, 10))
        pair.alpha_composite(n.resize((n.width * scale, n.height * scale), Image.NEAREST), (0, 10 + (o.height + 3) * scale))
        ImageDraw.Draw(pair).text((1, 0), name, fill=(255, 255, 0, 255))
        items.append(pair)
    x = y = rh = 0
    pos = []
    for it in items:
        if x + it.width > width:
            x, y, rh = 0, y + rh + 6, 0
        pos.append((it, x, y))
        x += it.width + 6
        rh = max(rh, it.height)
    # paginate so each page stays readable
    pages, page_h = [], 1600
    for it, x, y in pos:
        k = y // page_h
        while len(pages) <= k:
            pages.append([])
        pages[k].append((it, x, y - k * page_h))
    base = Path(path)
    base.parent.mkdir(parents=True, exist_ok=True)
    for k, items_k in enumerate(pages):
        h = max(y + it.height for it, x, y in items_k) + 4
        c = Image.new('RGBA', (width, h), (40, 40, 40, 255))
        for it, x, y in items_k:
            c.alpha_composite(it, (x, y))
        c.save(base.with_name(f'{base.stem}_{k:02d}{base.suffix}'))
    print(f'preview: {len(pages)} pages {base.stem}_NN{base.suffix}')


if __name__ == '__main__':
    main()
