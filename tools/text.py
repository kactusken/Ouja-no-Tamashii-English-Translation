#!/usr/bin/env python3
"""Shift-JIS string dumper / inserter for the overlays (PROG.BIN, STAFF.BIN, CRW.BIN, ...).

  text.py dump   <bin> <out.csv>            find null-terminated SJIS strings
  text.py insert <csv> <in.bin> <out.bin>   write the 'english' column back

CSV columns: offset, ram, refs, max_bytes, japanese, english, notes
  ram        address the string has in RAM (overlays load at 0x8005c1c8)
  refs       number of 32-bit words in the file pointing at the string
  max_bytes  space available in place (string + its null padding, minus one terminator)

Strings with refs > 0 are relocated freely within the pooled space of all such strings, so
max_bytes is only a guide for them; strings with refs == 0 are fixed and must fit max_bytes.
English is stored as full-width SJIS (put [ascii] in notes to opt out); see insert().
"""
import csv
import re
import struct
import sys
from pathlib import Path

OVERLAY_BASE = 0x8005c1c8
HEAP_START = 0x800a7b60  # overlays may extend up to here (heap base set at boot by 0x800144a0)
GROW_MARGIN = 0x100

SJIS_CHAR = rb'(?:[\x81-\x84\x88-\x9f\xe0-\xea][\x40-\x7e\x80-\xfc]|[\x20-\x7e])'
STRING = re.compile(rb'(?<=\x00)' + SJIS_CHAR + rb'+(?=\x00)')


def jp_score(s):
    """Fraction of characters that are kana / common punctuation / full-width alnum / ASCII."""
    good = sum(1 for c in s if '぀' <= c <= 'ヿ' or '＀' <= c <= '￯'
               or c in '　、。・ー「」（）！？“”『』' or c.isalnum() and c.isascii())
    return good / max(len(s), 1)


def load(path):
    d = Path(path).read_bytes()
    if d[:8] == b'PS-X EXE':
        base = struct.unpack_from('<I', d, 0x18)[0] - 0x800
    else:
        base = OVERLAY_BASE
    return d, base


def dump(path, out):
    d, base = load(path)
    ptrs = {}
    for i in range(0, len(d) - 3, 4):
        w = struct.unpack_from('<I', d, i)[0]
        ptrs[w] = ptrs.get(w, 0) + 1
    cands = []
    for m in STRING.finditer(d):
        raw = m.group()
        if not any(b >= 0x80 for b in raw):
            continue
        try:
            s = raw.decode('shift_jis')
        except UnicodeDecodeError:
            continue
        off = m.start()
        refs = ptrs.get(base + off, 0)
        plausible = (off % 4 == 0 and len(s) >= 3 and s[0] > '\x7f'
                     and not any(c.isascii() and not c.isalnum() and c != ' ' for c in s))
        if refs:
            ok = len(raw) >= 4 or any('\u3040' <= c <= '\u30ff' for c in s)  # skip lone kanji hit by chance
        else:
            ok = plausible and jp_score(s) >= 0.3
        cands.append([m, s, refs, ok, plausible])
    # second pass: accept kanji-only strings sitting right next to accepted text
    for i, c in enumerate(cands):
        if not c[3] and c[4] and not c[2]:
            near = [x for x in cands[max(0, i - 1):i + 2] if x is not c and x[3]]
            c[3] = any(abs(x[0].start() - c[0].end()) <= 16 or abs(c[0].start() - x[0].end()) <= 16 for x in near)
    rows = []
    for m, s, refs, ok, _ in cands:
        if not ok:
            continue
        off, end = m.start(), m.end()
        while end < len(d) and d[end] == 0:
            end += 1
        rows.append({'offset': f'{off:#07x}', 'ram': f'{base + off:#010x}', 'refs': refs,
                     'max_bytes': end - off - 1, 'japanese': s, 'english': '', 'notes': ''})
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ['offset'])
        w.writeheader()
        w.writerows(rows)
    print(f'{path}: {len(rows)} strings -> {out}')


FULLWIDTH = {i: i + 0xFEE0 for i in range(0x21, 0x7F)} | {
    0x20: 0x3000,                   # space -> ideographic space
    ord("'"): 0x2019, ord('"'): 0x201D,  # no full-width quote/apostrophe in SJIS: use ’ ”
    ord('-'): 0x2212, ord('~'): 0x301C}  # − 〜


def encode(s, fullwidth=False):
    return (s.translate(FULLWIDTH) if fullwidth else s).encode('shift_jis')


def _place(pooled, stable, partial=False, extra=()):
    """Return ([start offset per string], free regions) or None if it doesn't fit.

    stable: strings that fit their own slot stay there; others go into leftover space.
    otherwise: everything is re-packed largest-first, identical strings shared.
    """
    free = []
    layout = [None] * len(pooled)
    todo = list(range(len(pooled)))
    if stable:
        todo = []
        for k, (off, size, text_) in enumerate(pooled):
            if len(text_) + 1 <= size:
                layout[k] = off
                start = (off + len(text_) + 1 + 3) & ~3
                if start < off + size:
                    free.append([start, off + size])
            else:
                todo.append(k)
                free.append([off, off + size])
    else:
        free = [[off, off + size] for off, size, _ in pooled]
    free += [list(r) for r in extra]
    # slots usually sit back to back: merge touching regions so long strings fit
    merged = []
    for reg in sorted(free):
        if merged and reg[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], reg[1])
        else:
            merged.append(reg)
    free = merged
    placed = {}
    for k in sorted(todo, key=lambda k: -len(pooled[k][2])):
        text_ = pooled[k][2]
        if text_ in placed:
            layout[k] = placed[text_]
            continue
        need = len(text_) + 1
        fits = [r for r in free if r[1] - ((r[0] + 3) & ~3) >= need]
        if not fits:
            if partial:
                continue
            return None
        best = min(fits, key=lambda r: r[1] - ((r[0] + 3) & ~3))
        start = (best[0] + 3) & ~3
        best[0] = start + need
        layout[k] = placed[text_] = start
    return layout, free


def insert(csv_path, src, dst):
    """Insert translations.

    Strings referenced by data pointers (refs > 0) share one pool made of all their original slots.
    Strings that still fit stay put; the rest move into leftover space (or, if that fails, the whole
    pool is re-packed largest-first with identical strings shared) and their pointers are rewritten.
    Strings with refs == 0 are referenced from code (lui/addiu) and are only replaced in place,
    within max_bytes.
    English is stored as full-width SJIS: the game's text renderers (BIOS kanji ROM + custom glyphs for
    full-width alphanumerics, see docs/NOTES.md) draw nothing for single-byte ASCII. A notes value
    containing [ascii] stores the row as plain ASCII instead.
    If the original slots run out, strings spill into space appended to the end of the file (the
    overlay region is free up to the heap at 0x800a7b60; see tools/ramscan.py).
    """
    d = bytearray(Path(src).read_bytes())
    _, base = load(src)
    with open(csv_path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    errors = translated = 0
    pooled = []
    for row in rows:
        off, cap = int(row['offset'], 16), int(row['max_bytes'])
        orig = row['japanese'].encode('shift_jis')
        if d[off:off + len(orig)] != orig:
            print(f'  {row["offset"]}: original text not found')
            errors += 1
            continue
        new = encode(row['english'], '[ascii]' not in row['notes']) if row['english'] else orig
        translated += bool(row['english'])
        if int(row['refs']) == 0:
            if len(new) > cap:
                print(f'  {row["offset"]}: "{row["english"]}" is {len(new)} bytes, max {cap} (fixed position)')
                errors += 1
                continue
            d[off:off + cap + 1] = new.ljust(cap + 1, b'\0')
        else:
            pooled.append((off, cap + 1, new))
    if pooled:
        # pointer locations, found before the slots are overwritten
        slot_bytes = set()
        for off, size, _ in pooled:
            slot_bytes.update(range(off, off + size))
        old_addr = {base + off for off, _, _ in pooled}
        ptr_at = {}
        for i in range(0, len(d) - 3, 4):
            if i in slot_bytes:
                continue
            w = struct.unpack_from('<I', d, i)[0]
            if w in old_addr:
                ptr_at.setdefault(w, []).append(i)
        grow = []
        if base == OVERLAY_BASE:
            start = (len(d) + 3) & ~3
            grow = [(start, HEAP_START - GROW_MARGIN - base)]
        result = (_place(pooled, stable=True) or _place(pooled, stable=False)
                  or _place(pooled, stable=True, extra=grow))
        if result is None:
            print('  out of string space even after full repack')
            errors += 1
            result = _place(pooled, stable=False, partial=True)
        layout, free = result
        new_end = max((st + len(t) + 1 for (_, _, t), st in zip(pooled, layout) if st is not None), default=0)
        if new_end > len(d):
            d.extend(bytes(((new_end + 3) & ~3) - len(d)))
            print(f'  file grows to {len(d)} bytes (ends at {base + len(d):#x})')
        for off, size, _ in pooled:
            d[off:off + size] = bytes(size)
        new_addr = {}
        for (off, size, text_), start in zip(pooled, layout):
            if start is None:
                continue
            d[start:start + len(text_) + 1] = text_ + b'\0'
            new_addr[base + off] = base + start
        for old, locs in ptr_at.items():
            for i in locs:
                struct.pack_into('<I', d, i, new_addr.get(old, old))
        # sanity check: every pointer now leads to the intended text
        for (off, size, text_), start in zip(pooled, layout):
            for i in ptr_at.get(base + off, []):
                p = struct.unpack_from('<I', d, i)[0] - base
                assert start is None or d[p:p + len(text_) + 1] == text_ + b'\0', hex(off)
        left = sum(r[1] - r[0] for r in free)
        print(f'  pool: {len(pooled)} strings, {left} bytes left over')
    Path(dst).write_bytes(d)
    print(f'inserted {translated} translations into {dst} ({errors} problems)')
    return errors


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == 'dump':
        dump(a[1], a[2])
    elif len(a) == 4 and a[0] == 'insert':
        sys.exit(1 if insert(a[1], a[2], a[3]) else 0)
    else:
        print(__doc__)
        sys.exit(1)
