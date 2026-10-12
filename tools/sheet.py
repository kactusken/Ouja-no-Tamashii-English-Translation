#!/usr/bin/env python3
"""Edit several images as one sheet (used by `edit.py sheet ...`).

  edit.py sheet start   <sheet> <images/ranges...>   build translation/images-handmade/sheets/<sheet>.png
  edit.py sheet check   <sheet>                      preview the pieces after palette snapping
  edit.py sheet split   <sheet>                      write changed pieces to translation/images-handmade/
  edit.py sheet approve <sheet>                      split, approve every changed piece, remove the sheet
  edit.py sheet list                                 show existing sheets

Files in translation/images-handmade/sheets/:
  <sheet>.png            the sheet you edit (full colour): each image as [Japanese | English] at
                         original size with its name above - edit the English (right) side
  <sheet>.sheet.json     where each image sits - don't move images around on the sheet
  <sheet>_check.png      written by `check`: the pieces as they will look in-game
Only the English rectangles are read back; the Japanese side, labels and gaps can be scribbled on freely.
Transparent pixels are shown in magenta (255,0,255): paint magenta (or erase) to make pixels transparent.
"""
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import styled  # noqa: E402

GAP = 8
LABEL = 12
MID = 4         # gap between the Japanese original (left) and the English image (right)
MAX_W = 1024
BG = (40, 40, 48, 255)
KEY = (255, 0, 255, 255)  # transparent pixels are shown as magenta on the sheet, and read back as transparent


def sheets_dir():
    return paths.HANDMADE / 'sheets'


def _source(name):
    """The image the sheet starts from: the current English version, else the original."""
    for d in (paths.HANDMADE, paths.APPROVED, paths.AUTO_RENDERS / paths.ARCHIVE):
        if (d / f'{name}.png').exists():
            return d / f'{name}.png'
    return paths.JAPANESE_IMAGES / f'{name}.png'


def _layout(names):
    """Tiles of [Japanese | English] like the compare sheets; returns the English rectangles."""
    pos, x, y, rowh = {}, GAP, GAP, 0
    for n in names:
        w, h = Image.open(paths.JAPANESE_IMAGES / f'{n}.png').size
        tile = max(2 * w + MID, 60)
        if x + tile + GAP > MAX_W and x > GAP:
            x, y, rowh = GAP, y + rowh + LABEL + GAP, 0
        pos[n] = (x + w + MID, y + LABEL, w, h)
        x += tile + GAP
        rowh = max(rowh, h)
    width = max(p[0] + p[2] for p in pos.values()) + GAP
    height = max(p[1] + p[3] for p in pos.values()) + GAP
    return pos, width, height


def _compose(pos, size, pick, labels=True):
    sheet = Image.new('RGBA', size, BG)
    d = ImageDraw.Draw(sheet)
    for n, (x, y, w, h) in pos.items():
        jx = x - w - MID
        if labels:
            d.text((jx, y - LABEL + 1), n, fill=(255, 255, 0, 255))
        for px, img in ((jx, Image.open(paths.JAPANESE_IMAGES / f'{n}.png')), (x, pick(n))):
            sheet.paste(Image.new('RGBA', (w, h), KEY), (px, y))  # transparency shows as magenta
            sheet.alpha_composite(img.convert('RGBA'), (px, y))
        d.line([(x - MID // 2 - 1, y), (x - MID // 2 - 1, y + h - 1)], fill=(255, 255, 0, 255))
    return sheet


def files(sheet):
    return (sheets_dir() / f'{sheet}.png', sheets_dir() / f'{sheet}_japanese.png',
            sheets_dir() / f'{sheet}.sheet.json', sheets_dir() / f'{sheet}_check.png')


def start(sheet, names):
    edit_png, ja_png, manifest, _ = files(sheet)
    if manifest.exists():
        sys.exit(f'sheet "{sheet}" already exists ({paths.show(manifest)}) - pick another name')
    missing = [n for n in names if not (paths.JAPANESE_IMAGES / f'{n}.png').exists()]
    if missing:
        sys.exit(f'unknown image(s): {", ".join(missing)}')
    pos, w, h = _layout(names)
    sheets_dir().mkdir(parents=True, exist_ok=True)
    sources = {n: _source(n) for n in names}
    _compose(pos, (w, h), lambda n: Image.open(sources[n])).save(edit_png)
    hand = {n: hashlib.sha1((paths.HANDMADE / f'{n}.png').read_bytes()).hexdigest()
            for n in names if (paths.HANDMADE / f'{n}.png').exists()}
    manifest.write_text(json.dumps({'images': {n: list(p) for n, p in pos.items()},
                                    'started_from': {n: str(sources[n].resolve()) for n in names},
                                    'handmade_at_start': hand}, indent=1))
    print(f'sheet "{sheet}": {len(names)} images, {w}x{h}')
    print(f'  edit:      {paths.show(edit_png)}  (Japanese left, English right - edit the right side)')
    print(f'  then:      edit.py sheet check {sheet}   /   edit.py sheet split {sheet}   /   edit.py sheet approve {sheet}')


def _pieces(sheet):
    """(name, rgba piece, rgba source it started from) for every image on the sheet."""
    edit_png, _, manifest, _ = files(sheet)
    if not manifest.exists():
        sys.exit(f'no sheet "{sheet}" (see: edit.py sheet list)')
    m = json.loads(manifest.read_text())
    img = Image.open(edit_png).convert('RGBA')
    out = []
    for n, (x, y, w, h) in m['images'].items():
        piece = img.crop((x, y, x + w, y + h))
        piece.putdata([(0, 0, 0, 0) if p[:3] == KEY[:3] or p[3] == 0 else p[:3] + (255,)
                       for p in piece.get_flattened_data()])  # magenta (and erased) -> transparent
        start_src = paths.ROOT / m['started_from'][n]
        before = Image.open(start_src).convert('RGBA') if start_src.exists() else None
        out.append((n, piece, before))
    return out


def _snap(name, piece):
    orig = Image.open(paths.JAPANESE_IMAGES / f'{name}.png')
    bpp = json.loads((paths.JAPANESE_IMAGES / f'{name}.json').read_text())['bpp']
    return styled.quantize(piece, orig, 1 << bpp)


def _norm(img):
    """RGBA with every fully transparent pixel made identical (editors rewrite their hidden colour)."""
    return [(0, 0, 0, 0) if p[3] == 0 else p for p in img.get_flattened_data()]


def _changed(piece, before):
    return before is None or _norm(piece) != _norm(before)


def check(sheet):
    _, _, manifest, check_png = files(sheet)
    pieces = _pieces(sheet)
    m = json.loads(manifest.read_text())
    edit_size = Image.open(files(sheet)[0]).size
    snapped = {}
    changed = []
    for n, piece, before in pieces:
        if _changed(piece, before):
            changed.append(n)
            snapped[n] = _snap(n, piece)
    pos = {n: tuple(p) for n, p in m['images'].items()}
    _compose(pos, edit_size, lambda n: snapped[n] if n in snapped else Image.open(paths.ROOT / m['started_from'][n])).save(check_png)
    print(f'sheet "{sheet}": {len(changed)} of {len(pieces)} images changed'
          + (f' ({", ".join(changed[:8])}{"..." if len(changed) > 8 else ""})' if changed else ''))
    print(f'  preview after palette snapping: {paths.show(check_png)}')
    return changed


def split(sheet, force=False):
    m = json.loads(files(sheet)[2].read_text())
    at_start = m.get('handmade_at_start', {})
    pieces = _pieces(sheet)
    clash = []
    for n, piece, before in pieces:
        f = paths.HANDMADE / f'{n}.png'
        if _changed(piece, before) and f.exists():
            now = hashlib.sha1(f.read_bytes()).hexdigest()
            if at_start.get(n) != now:
                clash.append(n)
    if clash and not force:
        print(f'sheet "{sheet}": not split - these were edited individually after the sheet was made, and '
              f'splitting would overwrite them: {", ".join(clash)}\n  (re-run with --force to overwrite)')
        return None
    written = []
    for n, piece, before in pieces:
        if not _changed(piece, before):
            continue
        _snap(n, piece).save(paths.HANDMADE / f'{n}.png')
        meta = paths.JAPANESE_IMAGES / f'{n}.json'
        (paths.HANDMADE / f'{n}.json').write_bytes(meta.read_bytes())
        written.append(n)
    print(f'sheet "{sheet}": wrote {len(written)} changed image(s) to {paths.show(paths.HANDMADE)}'
          + (f': {", ".join(written[:8])}{"..." if len(written) > 8 else ""}' if written else ' (nothing changed)'))
    return written


def remove(sheet):
    for f in files(sheet):
        if f.exists():
            f.unlink()


def list_sheets():
    if not sheets_dir().exists() or not list(sheets_dir().glob('*.sheet.json')):
        print('no sheets')
        return
    for mf in sorted(sheets_dir().glob('*.sheet.json')):
        m = json.loads(mf.read_text())
        names = list(m['images'])
        print(f'{mf.name[:-11]}: {len(names)} images ({names[0]} ... {names[-1]})')
