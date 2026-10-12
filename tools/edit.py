#!/usr/bin/env python3
"""Hand-edit game graphics.

  edit.py start <image>... put <image>.png (the current English version - edit this) and
                           <image>_japanese.png (the original) in translation/images-handmade/
  edit.py refs <image>...  only write the references to review/edit/: <image>_japanese.png and
                           <image>_english.png at original size (same palette, ready to pixel-edit / copy from), plus
                           the palette as a swatch strip
  edit.py check <image>... validate your edited PNG; writes <image>_check.png (before/after) next to it
  edit.py approve <image>... [--force]
                           your edit is final: check it, convert it to the game's palette, move it to
                           translation/images-approved/ (marked done in graphics.csv) and clear its
                           files out of translation/images-handmade/
  edit.py reset <image>...  undo: remove the image's hand edit (in progress or approved) and go back to
                           the automatic English version, or the untouched original
  edit.py sheet ...         edit several images as one sheet - see `edit.py sheet` for help
  edit.py list [text]       find images in graphics.csv (by name, Japanese or English)

Several images at once: separate names with spaces or commas, or give a range, e.g.
  edit.py start 0013_027 0013_028 0013_029      edit.py check 0013_027,0013_028,0013_029
  edit.py start 0017_020-0017_052               (also 0017_020..0017_052 or 0017_020-052)

Rules for an edited PNG:
  * same width and height as the original
  * ideally indexed colour ("P" mode) with the original palette (4bpp images have 16 colours,
    8bpp 256); RGB also works and is snapped to the palette on approve
  * transparent areas stay transparent
  * keep the matching .json file next to it (start copies it for you)
Hand-made PNGs override the automatic renders, and are applied to every duplicate of the image.
Reference files (<image>_japanese.png, _english.png, _palette.png, _check.png) are ignored by the build.
"""
import csv
import json
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import render  # noqa: E402
import sheet  # noqa: E402
import styled  # noqa: E402

REF_SUFFIXES = ('_japanese', '_english', '_palette', '_check')


def rows():
    with open(paths.GRAPHICS_CSV, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def write_rows(table):
    with open(paths.GRAPHICS_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(table[0].keys()))
        w.writeheader()
        w.writerows(table)


def remove_handmade(name):
    """Delete the image's work-in-progress files from images-handmade/; returns their names."""
    removed = []
    for f in [paths.HANDMADE / f'{name}.json'] + [paths.HANDMADE / f'{name}{s}.png' for s in ('',) + REF_SUFFIXES]:
        if f.exists():
            f.unlink()
            removed.append(f.name)
    return removed


def dups_of(name):
    return [r['image'] for r in rows() if r['dup_of'] == name]


def current_english(name):
    """Path of the English version the build would use right now (hand-made > approved > automatic)."""
    for cand in (paths.HANDMADE / f'{name}.png', paths.APPROVED / f'{name}.png',
                 paths.AUTO_RENDERS / paths.ARCHIVE / f'{name}.png'):
        if cand.exists():
            return cand
    return None


def refs(name):
    src = paths.JAPANESE_IMAGES / f'{name}.png'
    if not src.exists():
        sys.exit(f'{src} not found (run a build once so {paths.show(paths.JAPANESE_IMAGES)} is populated)')
    paths.EDIT_REFS.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, paths.EDIT_REFS / f'{name}_japanese.png')
    en = current_english(name)
    if en:
        shutil.copyfile(en, paths.EDIT_REFS / f'{name}_english.png')
    meta = json.loads((paths.JAPANESE_IMAGES / f'{name}.json').read_text())
    im = Image.open(src)
    pal = im.getpalette()[:3 * (1 << meta['bpp'])]
    sw = Image.new('RGB', (len(pal) // 3 * 12, 12))
    for i in range(len(pal) // 3):
        sw.paste(tuple(pal[3 * i:3 * i + 3]), (i * 12, 0, i * 12 + 12, 12))
    sw.save(paths.EDIT_REFS / f'{name}_palette.png')
    print(f'  references in {paths.show(paths.EDIT_REFS)}: {name}_japanese.png'
          + (f', {name}_english.png (from {paths.show(en.parent)})' if en else ' (no English version yet)')
          + f', {name}_palette.png')


def start(name):
    src = paths.JAPANESE_IMAGES / f'{name}.png'
    if not src.exists():
        sys.exit(f'{src} not found (run a build once so {paths.show(paths.JAPANESE_IMAGES)} is populated)')
    paths.HANDMADE.mkdir(parents=True, exist_ok=True)
    paths.EDIT_REFS.mkdir(parents=True, exist_ok=True)
    target = paths.HANDMADE / f'{name}.png'
    if target.exists():
        print(f'{paths.show(target)} already exists - not overwriting')
    else:
        cand = current_english(name) or src
        shutil.copyfile(cand, target)
        print(f'copied {paths.show(cand)} -> {paths.show(target)}')
    shutil.copyfile(paths.JAPANESE_IMAGES / f'{name}.json', paths.HANDMADE / f'{name}.json')
    im = Image.open(src)
    meta = json.loads((paths.JAPANESE_IMAGES / f'{name}.json').read_text())
    r = next((x for x in rows() if x['image'] == name), None)
    print(f'{name}: {im.width}x{im.height}, {meta["bpp"]}bpp ({1 << meta["bpp"]} colours)')
    if r:
        print(f'  japanese: {r["japanese"]}\n  english:  {r["english"]}\n  notes:    {r["notes"]}')
    d = dups_of(name)
    if d:
        print(f'  your edit will also be used for {len(d)} duplicate(s): {", ".join(d[:8])}{"..." if len(d) > 8 else ""}')
    shutil.copyfile(src, paths.HANDMADE / f'{name}_japanese.png')
    print(f'  in {paths.show(paths.HANDMADE)}: {name}.png  <- edit this one')
    print(f'                                   {name}_japanese.png  (the original, for reference - ignored by the build)')
    print(f'  when done: .venv/bin/python tools/edit.py check {name}')


def check(name):
    print(f'{name}:')
    if not (paths.HANDMADE / f'{name}.png').exists():
        print(f'  ! {paths.show(paths.HANDMADE / (name + ".png"))} not found (run: edit.py start {name})')
        return ['missing']
    orig = Image.open(paths.JAPANESE_IMAGES / f'{name}.png')
    meta = json.loads((paths.JAPANESE_IMAGES / f'{name}.json').read_text())
    new = Image.open(paths.HANDMADE / f'{name}.png')
    problems = []
    if new.size != orig.size:
        problems.append(f'size {new.size} != original {orig.size}')
    notes = []
    if new.mode != 'P':
        notes.append(f'saved as {new.mode} (not indexed): fine - colours are snapped to the palette on build/approve')
    else:
        n = 1 << meta['bpp']
        hi = max(new.get_flattened_data())
        if hi >= n:
            problems.append(f'uses palette index {hi}, but this image only has {n} colours')
        if new.getpalette()[:3 * n] != orig.getpalette()[:3 * n]:
            problems.append('palette differs from the original (pixels map by index, so colours may come out wrong)')
    paths.EDIT_REFS.mkdir(parents=True, exist_ok=True)
    s = 3
    a = orig.convert('RGBA').resize((orig.width * s, orig.height * s), Image.NEAREST)
    b = new.convert('RGBA').resize((new.width * s, new.height * s), Image.NEAREST)
    prev = Image.new('RGBA', (a.width, a.height + b.height + 6), (255, 0, 255, 255))
    prev.alpha_composite(a, (0, 0))
    prev.alpha_composite(b, (0, a.height + 6))
    prev.save(paths.HANDMADE / f'{name}_check.png')
    for n in notes:
        print(f'  note: {n}')
    print('\n'.join(f'  ! {p}' for p in problems) or '  OK')
    print(f'  preview (original above, yours below): {paths.show(paths.HANDMADE / (name + "_check.png"))}')
    return problems


def find(text=''):
    for r in rows():
        if r['dup_of']:
            continue
        hay = ' '.join((r['image'], r['japanese'], r['english'])).lower()
        if text.lower() in hay:
            print(f'{r["image"]} {r["width"]}x{r["height"]} [{r["status"]}] {r["japanese"][:30]} | {r["english"][:50]}')


def approve(name, force=False):
    """Move a finished hand edit into translation/images-approved/ (indexed, original palette),
    mark it done in graphics.csv (adding a row if the image wasn't listed) and clean up its files."""
    problems = check(name)
    if 'missing' in problems:
        return False
    if problems and not force:
        print('  not approved - fix the problems above, or approve anyway with --force')
        return False
    meta = json.loads((paths.JAPANESE_IMAGES / f'{name}.json').read_text())
    ncol = 1 << meta['bpp']
    orig = Image.open(paths.JAPANESE_IMAGES / f'{name}.png')
    new = Image.open(paths.HANDMADE / f'{name}.png')
    if new.mode == 'P' and new.getpalette()[:3 * ncol] == orig.getpalette()[:3 * ncol]:
        final = new  # already indexed with the game's palette: keep it exactly
    else:
        final = styled.quantize(new.convert('RGBA'), orig, ncol)
        print(f'  converted to the image\'s {ncol}-colour palette')
    paths.APPROVED.mkdir(parents=True, exist_ok=True)
    final.save(paths.APPROVED / f'{name}.png')
    # graphics.csv: mark done (or add the image if it had no row)
    table = rows()
    fields = list(table[0].keys())
    row = next((r for r in table if r['image'] == name), None)
    if row is None:
        row = {k: '' for k in fields}
        row.update(image=name, width=str(orig.width), height=str(orig.height), bpp=str(meta['bpp']),
                   category='other', notes='hand-made image (no Japanese text originally listed)')
        table.append(row)
        table.sort(key=lambda r: r['image'])
    row['status'] = 'done'
    if not row['english'].strip():
        row['english'] = '(hand-made)'
    if 'hand-made' not in row['notes']:
        row['notes'] = (row['notes'] + '; ' if row['notes'] else '') + 'hand-made'
    row['review'] = ''
    write_rows(table)
    remove_handmade(name)
    d = dups_of(name)
    print(f'  approved -> {paths.show(paths.APPROVED / (name + ".png"))}'
          + (f' (also used for {len(d)} duplicate(s))' if d else '') + '; removed from images-handmade/')
    return True


def reset(name):
    """Undo hand edits: remove the work-in-progress files and, if the image was approved from a hand edit,
    its approved file - restoring the automatic English version (or the untouched original)."""
    removed = remove_handmade(name)
    table = rows()
    row = next((r for r in table if r['image'] == name), None)
    approved = paths.APPROVED / f'{name}.png'
    if row is not None and row['english'].strip() == '(hand-made)':
        # a row that only exists because of a hand edit: drop it -> untouched original
        table.remove(row)
        if approved.exists():
            approved.unlink()
        result = 'back to the untouched original'
    elif row is not None and 'hand-made' in row['notes']:
        # a translated image whose approved file came from a hand edit: re-render it from the CSV
        if approved.exists():
            approved.unlink()
        row['notes'] = '; '.join(n for n in row['notes'].split('; ') if n != 'hand-made')
        row['status'] = 'todo'
        result = None
    else:
        result = 'no approved hand edit - automatic version unchanged'
    write_rows(table)
    if result is None:
        render.regen([name])
        result = ('back to the automatic English version' if approved.exists()
                  else 'automatic version could not be rendered - the Japanese original is used')
    print(f'{name}: {result}' + (f' (removed {", ".join(removed)})' if removed else ''))


def names_from(args):
    """Image names from the command line: separated by spaces and/or commas, with ranges
    0017_020-0017_052, 0017_020..0017_052 or 0017_020-052 (all existing images in between;
    exact duplicates are left out because they follow their original)."""
    existing = sorted(p.stem for p in paths.JAPANESE_IMAGES.glob('*.png'))
    dup = {r['image']: r['dup_of'] for r in rows() if r['dup_of']}
    out, skipped = [], []
    for token in (t for a in args for t in a.replace(',', ' ').split() if t):
        m = re.fullmatch(r'(\d{4}_\d{3})(?:-|\.\.)(\d{4}_\d{3}|\d{3})', token)
        if not m:
            out.append(token)
            continue
        lo, hi = m.group(1), m.group(2)
        if '_' not in hi:
            hi = lo[:5] + hi
        if hi < lo:
            lo, hi = hi, lo
        for n in existing:
            if lo <= n <= hi:
                (skipped if n in dup else out).append(n)
    if skipped:
        print(f'(range: left out {len(skipped)} duplicate(s) that follow their original: {", ".join(skipped[:6])}'
              f'{"..." if len(skipped) > 6 else ""})\n')
    seen = set()
    return [n for n in out if not (n in seen or seen.add(n))]


if __name__ == '__main__':
    a = paths.configure(sys.argv[1:])
    cmd, names = (a[0], names_from(a[1:])) if a else (None, [])
    if cmd == 'start' and names:
        for i, n in enumerate(names):
            if i:
                print()
            start(n)
    elif cmd == 'refs' and names:
        for n in names:
            print(f'{n}:')
            refs(n)
    elif cmd == 'check' and names:
        results = {}
        for i, n in enumerate(names):
            if i:
                print()
            results[n] = check(n)
        if len(names) > 1:
            bad = [n for n, p in results.items() if p]
            print(f'\n{len(names) - len(bad)}/{len(names)} OK' + (f' - needs attention: {", ".join(bad)}' if bad else ''))
    elif cmd == 'approve' and names:
        force = '--force' in a
        names = [n for n in names if n != '--force']
        ok = []
        for i, n in enumerate(names):
            if i:
                print()
            if approve(n, force):
                ok.append(n)
        if len(names) > 1:
            print(f'\napproved {len(ok)}/{len(names)}' + (f' - not approved: {", ".join(n for n in names if n not in ok)}'
                                                         if len(ok) < len(names) else ''))
    elif cmd == 'sheet':
        sub = a[1] if len(a) > 1 else ''
        if sub == 'start' and len(a) >= 4:
            sheet.start(a[2], names_from(a[3:]))
        elif sub == 'check' and len(a) == 3:
            sheet.check(a[2])
        elif sub == 'split' and len(a) >= 3:
            sheet.split(a[2], '--force' in a)
        elif sub == 'approve' and len(a) >= 3:
            written = sheet.split(a[2], '--force' in a)
            if written is None:
                sys.exit(1)
            ok = [n for n in written if approve(n, '--force' in a)]
            if len(ok) == len(written):
                sheet.remove(a[2])
                print(f'sheet "{a[2]}": {len(ok)} image(s) approved; sheet removed')
            else:
                print(f'sheet "{a[2]}": approved {len(ok)}/{len(written)} - sheet kept so you can fix the rest')
        elif sub == 'list':
            sheet.list_sheets()
        else:
            print(sheet.__doc__)
    elif cmd == 'reset' and names:
        for n in names:
            reset(n)
    elif cmd == 'list':
        find(' '.join(a[1:]))
    else:
        print(__doc__)
