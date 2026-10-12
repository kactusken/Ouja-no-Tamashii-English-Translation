#!/usr/bin/env python3
"""Redraw text that has outlines, shadows, glows or gradients, or sits on artwork.

Model of a piece of game text, learned from the original image:
  region  pixels belonging to the text (fill + decoration), found by comparing the image with
          its background: transparency, or the per-pixel median of a set of same-size images
          (buttons/banners that share artwork)
  fill    the glyph body: the colours deepest inside the region
  rows    fill colour per row, relative to the text height (keeps vertical gradients)
  rings   decoration colour by distance from the fill (outline = 1 ring, glow = several), or
  shadow  a one-sided offset copy of the fill in a darker colour
New text is drawn with the same model onto the clean background, then mapped to the palette.
"""
import hashlib
from collections import Counter

from PIL import Image

NEIGH8 = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]


def median_plate(images):
    """Per-pixel most common colour across same-size images (their shared background)."""
    W, H = images[0].size
    data = [list(i.convert('RGBA').get_flattened_data()) for i in images]
    out = Image.new('RGBA', (W, H))
    out.putdata([Counter(px[k] for px in data).most_common(1)[0][0] for k in range(W * H)])
    return out


def text_free_plate(images):
    """Shared background of a set whose texts overlap: ignore text colours when voting.

    A plain median fails where most members have text at the same spot (centred labels), so
    collect the colours that make up each member's text (its differences from a first median)
    and re-vote each pixel among the remaining colours; pixels covered by text in every member
    are filled by row interpolation.
    """
    uniq = {}
    for im in images:
        uniq.setdefault(hashlib.sha1(im.tobytes()).hexdigest(), im)
    images = list(uniq.values())
    first = median_plate(images)
    text_cols = Counter()
    for im in images:
        a = im.convert('RGBA').load()
        for p in region_vs_background(im, first):
            text_cols[a[p]] += 1
    total = sum(text_cols.values())
    T, acc = set(), 0
    for c, n in text_cols.most_common():  # colours covering 90% of all text pixels
        if acc >= 0.9 * total:
            break
        if c[3] == 0:
            continue  # transparency is background, never text
        T.add(c)
        acc += n
    W, H = images[0].size
    data = [list(i.convert('RGBA').get_flattened_data()) for i in images]
    holes = set()
    vals = []
    fpx = list(first.get_flattened_data())
    for k in range(W * H):
        x, y = k % W, k // W
        if x < 3 or y < 3 or x >= W - 3 or y >= H - 3:
            vals.append(fpx[k])  # frames/bevels: text never reaches the edge, keep the plain median
            continue
        cands = Counter(px[k] for px in data if px[k] not in T)
        if cands:
            vals.append(cands.most_common(1)[0][0])
        else:
            vals.append((0, 0, 0, 0))
            holes.add((x, y))
    # holes (text in every member): blend each row between the clean side margins (median of a strip
    # at each end that text never reaches) - smooth, but no stray text colours
    def strip_median(y, xs):
        c = [fpx[y * W + x] for x in xs if 0 <= x < W]
        c = sorted(c, key=lambda q: (q[3], lum(q)))
        return c[len(c) // 2] if c else (0, 0, 0, 0)
    for y in range(H):
        row_holes = [x for x in range(W) if (x, y) in holes]
        if not row_holes:
            continue
        left = strip_median(y, range(4, 9))
        right = strip_median(y, range(W - 9, W - 4))
        for x in row_holes:
            t = (x - 6) / max(1, W - 13)
            t = min(1, max(0, t))
            vals[y * W + x] = tuple(round(left[i] * (1 - t) + right[i] * t) for i in range(4))
        holes -= {(x, y) for x in row_holes}
    out = Image.new('RGBA', (W, H))
    out.putdata(vals)
    if holes:
        inpaint_rows(out, holes)
    return out, len(images)


def differs(p, q, tol=48):
    if (p[3] == 0) != (q[3] == 0):
        return True
    if p[3] == 0:
        return False
    return abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2]) > tol


def region_vs_background(im, bg, tol=48):
    """Pixels where the image differs noticeably from its background. Members of a set carry
    their own palettes, so the shared artwork differs by a few shades: compare with a tolerance."""
    a = list(im.convert('RGBA').get_flattened_data())
    b = list(bg.get_flattened_data())
    W, H = im.size
    return {(k % W, k // W) for k in range(W * H) if differs(a[k], b[k], tol)}


def line_background(im, tol=48, union=False):
    """Background estimate for a single image: the median colour of each row (or of each column,
    whichever explains more pixels). Works for solid boxes, gradients and text on transparency;
    text rarely covers half a row."""
    rgba = im.convert('RGBA')
    W, H = im.size
    px = rgba.load()

    def med(cols):
        cols = sorted(cols, key=lambda c: (c[3], lum(c)))
        return cols[len(cols) // 2]

    best = None
    for axis in ('row', 'col'):
        bg = Image.new('RGBA', (W, H))
        b = bg.load()
        if axis == 'row':
            for y in range(H):
                m = med([px[x, y] for x in range(W)])
                for x in range(W):
                    b[x, y] = m
        else:
            for x in range(W):
                m = med([px[x, y] for y in range(H)])
                for y in range(H):
                    b[x, y] = m
        reg = region_vs_background(im, bg, tol)
        if union and best is not None:
            best = (best[0], best[1] | reg)  # rows dominated by a long stroke hide it from the row median
        elif best is None or len(reg) < len(best[1]):
            best = (bg, reg)
    return best


def dense_band(region, size, frac=0.12):
    """Keep only the part of a detected region inside the band where it is dense: the text line(s).
    Sparse differences elsewhere (emblems, frames, texture) are left alone."""
    if not region:
        return region
    W, H = size
    rows = Counter(y for _, y in region)
    cols = Counter(x for x, _ in region)
    ys = [y for y in range(H) if rows[y] >= frac * W * 0.5]
    if not ys:
        return set()
    y0, y1 = min(ys), max(ys)
    band = [(x, y) for x, y in region if y0 <= y <= y1]
    cols = Counter(x for x, _ in band)
    xs = [x for x in range(W) if cols[x] >= max(2, frac * (y1 - y0 + 1))]
    if not xs:
        return set()
    x0, x1 = min(xs), max(xs)
    return {(x, y) for x, y in band if x0 - 1 <= x <= x1 + 1}


def inpaint_smooth(im, region, halo=2):
    """inpaint_region done along rows and along columns; keep whichever result is smoother inside
    the filled area (a bright frame pixel at a row end otherwise smears into a streak)."""
    a = inpaint_region(im, region, halo)
    b = inpaint_region(im.transpose(Image.Transpose.TRANSPOSE),
                       {(y, x) for x, y in region}, halo).transpose(Image.Transpose.TRANSPOSE)

    def roughness(img):
        px = img.load()
        W, H = img.size
        tot = 0
        for x, y in region:
            if x + 1 < W and y + 1 < H:
                tot += abs(lum(px[x, y]) - lum(px[x + 1, y])) + abs(lum(px[x, y]) - lum(px[x, y + 1]))
        return tot
    src = im.convert('RGBA').load()

    def holes(img):  # transparency introduced where the original was opaque
        px = img.load()
        return sum(1 for p in region if src[p][3] and px[p][3] == 0)
    ha, hb = holes(a), holes(b)
    if ha != hb:
        return a if ha < hb else b
    return a if roughness(a) <= roughness(b) else b


def inpaint_region(im, region, halo=2):
    """The original with `region` filled in from its surroundings (row interpolation)."""
    out = im.convert('RGBA').copy()
    grown = set(region)
    for _ in range(halo):  # a halo so antialiasing/glow remnants of the old text go too
        for x, y in list(grown):
            for dx, dy in NEIGH8:
                grown.add((x + dx, y + dy))
    grown = {(x, y) for x, y in grown if 0 <= x < im.width and 0 <= y < im.height}
    inpaint_rows(out, grown)
    px = out.load()
    for p in grown:  # interpolation between transparent and opaque: snap alpha
        c = px[p]
        px[p] = c[:3] + (255,) if c[3] >= 128 else (0, 0, 0, 0)
    return out


def region_opaque(im):
    a = list(im.convert('RGBA').get_flattened_data())
    W = im.width
    return {(k % W, k // W) for k, p in enumerate(a) if p[3]}


def depth_map(region):
    """Chebyshev distance from each region pixel to the outside."""
    depth = {}
    frontier = [p for p in region if any((p[0] + dx, p[1] + dy) not in region for dx, dy in NEIGH8)]
    for p in frontier:
        depth[p] = 1
    d = 1
    while frontier:
        nxt = []
        for x, y in frontier:
            for dx, dy in NEIGH8:
                q = (x + dx, y + dy)
                if q in region and q not in depth:
                    depth[q] = d + 1
                    nxt.append(q)
        frontier = nxt
        d += 1
    return depth


def dist_from(mask, limit):
    """Chebyshev distance (1..limit) of pixels around `mask`."""
    out = {}
    frontier = list(mask)
    seen = set(mask)
    for d in range(1, limit + 1):
        nxt = []
        for x, y in frontier:
            for dx, dy in NEIGH8:
                q = (x + dx, y + dy)
                if q not in seen:
                    seen.add(q)
                    out[q] = d
                    nxt.append(q)
        frontier = nxt
    return out


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


class Style:
    def __init__(self):
        self.rows = []       # fill colours, top to bottom of the text
        self.rings = []      # colour at distance 1..n from the fill
        self.shadow = None   # (dx, dy, colour)
        self.margin = 0

    def __repr__(self):
        return f'Style(rows={len(self.rows)}, rings={len(self.rings)}, shadow={self.shadow})'


def learn(im, region, background=None):
    """Work out fill / gradient / outline / shadow from the original text pixels.

    With a known background, the fill is the colour that stands out most from it (count x contrast);
    otherwise it is the colour that least touches the edge of the text region."""
    px = im.convert('RGBA').load()
    st = Style()
    region = {p for p in region if px[p][3]}  # transparency is never part of the text
    if not region:
        return st
    colours = Counter(px[p] for p in region)
    # fill vs decoration: decoration (outline/glow/shadow) lies on the edge of the text region,
    # the glyph body mostly doesn't touch the outside
    edge = Counter()
    for p in region:
        if any((p[0] + dx, p[1] + dy) not in region for dx, dy in NEIGH8):
            edge[px[p]] += 1
    frac = {c: edge[c] / colours[c] for c in colours}
    total = len(region)
    inner = [c for c in colours if frac[c] < 0.35 and colours[c] >= max(3, 0.02 * total)]
    if background is not None:
        bpx = background.load()
        contrast = Counter()
        for p in region:
            c, b = px[p], bpx[p]
            contrast[c] += 255 * 3 if b[3] == 0 else abs(c[0] - b[0]) + abs(c[1] - b[1]) + abs(c[2] - b[2])
        main = max(colours, key=lambda c: contrast[c] * (1.15 - frac[c]))  # prefer stroke interiors
        fill_cols = {c for c in colours if abs(lum(c) - lum(main)) < 40 and colours[c] >= max(3, 0.02 * total)
                     and contrast[c] / colours[c] > 0.5 * contrast[main] / colours[main]} or {main}
    elif inner:
        # the fill family: the most common inner colour plus inner colours of similar brightness
        main = max(inner, key=lambda c: colours[c])
        fill_cols = {c for c in inner if abs(lum(c) - lum(main)) < 60}
    else:
        fill_cols = {min(colours, key=lambda c: frac[c])}
    fill = {p for p in region if px[p] in fill_cols}
    rest = region - fill
    # vertical gradient of the fill
    ys = [p[1] for p in fill]
    y0, y1 = min(ys), max(ys)
    for y in range(y0, y1 + 1):
        row = Counter(px[p] for p in fill if p[1] == y)
        st.rows.append(row.most_common(1)[0][0] if row else None)
    st.rows = _fill_gaps(st.rows) or [Counter(px[p] for p in fill).most_common(1)[0][0]]
    if not rest:
        return st
    # shadow: decoration explained by one offset copy of the fill
    best = None
    for dx, dy in [(1, 1), (2, 2), (1, 0), (0, 1), (2, 1), (1, 2), (3, 3)]:
        hit = sum(1 for (x, y) in rest if (x - dx, y - dy) in fill)
        opposite = sum(1 for (x, y) in rest if (x + dx, y + dy) in fill and (x - dx, y - dy) not in fill)
        if best is None or hit - opposite > best[0]:
            best = (hit - opposite, dx, dy, hit, opposite)
    _, dx, dy, hit, opposite = best
    if hit >= 0.8 * len(rest) and opposite <= 0.1 * len(rest):
        col = Counter(px[(x, y)] for (x, y) in rest if (x - dx, y - dy) in fill).most_common(1)[0][0]
        st.shadow = (dx, dy, col)
        st.margin = max(dx, dy)
        return st
    # rings: colour by distance from the fill. A ring is real decoration (outline/glow) only if it
    # covers most of the positions at that distance around the original fill; sparse hits are
    # background noise and would turn into a solid box around the new text.
    W, H = im.size
    d = dist_from(fill, 4)
    ring_all = Counter(k for (x, y), k in d.items() if 0 <= x < W and 0 <= y < H)
    by_d = {}
    for p in rest:
        if p in d:
            by_d.setdefault(d[p], Counter())[px[p]] += 1
    n = 0
    for k in range(1, 4):
        hits = by_d.get(k, Counter())
        if not hits or ring_all[k] == 0:
            break
        colour, cnt = hits.most_common(1)[0]
        if cnt < 0.55 * ring_all[k]:
            break
        st.rings.append(colour)
        n = k
    st.margin = n
    return st


def _fill_gaps(rows):
    if not any(rows):
        return []
    last = next(c for c in rows if c)
    out = []
    for c in rows:
        last = c or last
        out.append(last)
    return out


def ensure_legible(st, background, box, min_diff=90):
    """If the learned fill is too close to what's behind the text, use white or black with a 1px
    outline in the opposite colour - readability first."""
    bx, by, bw, bh = box
    bpx = background.load()
    W, H = background.size
    pts = [bpx[x, y] for y in range(max(0, by), min(H, by + bh)) for x in range(max(0, bx), min(W, bx + bw))]
    pts = [c for c in pts if c[3]]
    if not pts or not st.rows:
        return st
    bg_l = sorted(lum(c) for c in pts)[len(pts) // 2]
    fill_l = lum(st.rows[len(st.rows) // 2])
    if abs(fill_l - bg_l) >= min_diff:
        return st
    white, black = (255, 255, 255, 255), (16, 16, 16, 255)
    fill, edge = (white, black) if bg_l < 150 else (black, white)
    st.rows = [fill]
    st.rings = [edge]
    st.shadow = None
    st.margin = 1
    return st


def paint(base, mask, st, text_top, text_h):
    """Draw glyph mask (set of (x, y)) with style onto RGBA `base` (modified in place)."""
    W, H = base.size
    px = base.load()
    if st.shadow:
        dx, dy, col = st.shadow
        for x, y in mask:
            q = (x + dx, y + dy)
            if 0 <= q[0] < W and 0 <= q[1] < H and q not in mask:
                px[q] = col
    if st.rings:
        d = dist_from(mask, len(st.rings))
        for (x, y), k in d.items():
            if 0 <= x < W and 0 <= y < H:
                px[x, y] = st.rings[k - 1]
    n = len(st.rows)
    for x, y in mask:
        if 0 <= x < W and 0 <= y < H:
            r = min(n - 1, max(0, (y - text_top) * n // max(text_h, 1)))
            px[x, y] = st.rows[r]


def inpaint_rows(img, region):
    """Fill `region` by interpolating each row between the nearest outside pixels."""
    px = img.load()
    W, H = img.size
    pending = []
    for y in range(H):
        xs = sorted(x for x in range(W) if (x, y) in region)
        if not xs:
            continue
        x = 0
        while x < W:
            if (x, y) not in region:
                x += 1
                continue
            x0 = x
            while x < W and (x, y) in region:
                x += 1
            left = px[x0 - 1, y] if x0 > 0 else None
            right = px[x, y] if x < W else None
            for k in range(x0, x):
                if left and right:
                    t = (k - x0 + 1) / (x - x0 + 1)
                    px[k, y] = tuple(round(left[i] * (1 - t) + right[i] * t) for i in range(4))
                elif left or right:
                    px[k, y] = left or right
                else:
                    pending.append((k, y))  # whole row covered: fill from above/below afterwards
    # rows covered edge to edge: interpolate vertically between the nearest outside pixels
    outside = [px[x, y] for y in range(H) for x in range(W) if (x, y) not in region and px[x, y][3]]
    if not outside:  # nothing untouched around: use the median opaque colour of the whole area
        outside = [px[x, y] for y in range(H) for x in range(W) if px[x, y][3]]
    fallback = sorted(outside, key=lambda c: lum(c))[len(outside) // 2] if outside else (0, 0, 0, 0)
    for k, y in pending:
        up = next((y2 for y2 in range(y - 1, -1, -1) if (k, y2) not in region), None)
        dn = next((y2 for y2 in range(y + 1, H) if (k, y2) not in region), None)
        a = px[k, up] if up is not None else None
        b = px[k, dn] if dn is not None else None
        if a and b:
            t = (y - up) / (dn - up)
            px[k, y] = tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(4))
        else:
            px[k, y] = a or b or fallback


def quantize(rgba, pal_img, ncolors):
    """Map an RGBA image onto the first `ncolors` entries of the original image's palette."""
    pal = pal_img.getpalette()[:3 * ncolors]
    t = pal_img.info.get('transparency')
    if isinstance(t, int):
        alpha = [0 if i == t else 255 for i in range(ncolors)]
    elif t:
        alpha = [t[i] if i < len(t) else 255 for i in range(ncolors)]
    else:
        alpha = [255] * ncolors
    opaque = [i for i in range(len(pal) // 3) if alpha[i]]
    clear = next((i for i in range(len(pal) // 3) if not alpha[i]), None)
    cache = {}

    def nearest(c):
        if c[3] < 128 and clear is not None:
            return clear
        if c not in cache:
            cache[c] = min(opaque, key=lambda i: (pal[3 * i] - c[0]) ** 2 * 3 + (pal[3 * i + 1] - c[1]) ** 2 * 4
                           + (pal[3 * i + 2] - c[2]) ** 2 * 2)
        return cache[c]

    out = Image.new('P', rgba.size)
    out.putpalette(pal)
    out.putdata([nearest(c) for c in rgba.get_flattened_data()])
    if clear is not None:
        out.info['transparency'] = bytes(alpha)
    return out
