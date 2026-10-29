#!/usr/bin/env python3
"""Fill the data block of the player's guide (docs/guide/index.html) from the game and the translation.

  .venv/bin/python tools/guidedata.py [--check]

Reads the original disc (PROG.BIN / CRW.BIN tables, see docs/NOTES.md) for what the game holds -
the Edit Wrestler availability arrays, the Path of the Five Crowns rosters and the costume-name table -
and takes every English name from translation/ (graphics.csv labels, text/PROG.csv), so the guide
always shows the patch's names. --check only reports whether the page is up to date (exit 1 if not).
"""
import argparse
import csv
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import disc  # noqa: E402
import pagedata  # noqa: E402
import paths  # noqa: E402

BASE = 0x8005c1c8                 # every overlay loads here
EDIT_TABLE = 0x8008d37c           # PROG: 4 availability arrays per page (levels 0-3)
EDIT_COUNTS = (44, 60, 20, 40)    # body, move set, logic, entrance
COSTUMES = 0x8008c808             # PROG: 4 name pointers per body model
CROWNS = {                        # CRW: Five Crowns wrestler lists (model ids)
    'succession': (0x8005c674, 8), 'succession_code1': (0x8005c67c, 10),
    'succession_code2': (0x8005c688, 12), 'ascent': (0x8005c694, 10), 'ascent_code2': (0x8005c6a0, 13),
}
# Clearing a chapter sets bit (chapter) of the unlock flag (PROG 0x8006b784: Succession bit 0,
# Ascent bit 1); the flag picks the availability level.
UNLOCK = {(1, 1, 1, 1): 'start', (0, 1, 1, 1): 'either', (0, 1, 0, 1): 'succession',
          (0, 0, 1, 1): 'ascent', (0, 0, 0, 1): 'both', (0, 0, 0, 0): 'never'}


def label(G, image):
    """English of a graphics.csv row, following dup_of; ' / ' line breaks joined."""
    r = G[image]
    while r['dup_of']:
        r = G[r['dup_of']]
    return r['english'].replace('- / ', '').replace(' / ', ' ').strip()


def jp(G, image):
    return G[image]['japanese'].strip()


def build():
    G = {r['image']: r for r in csv.DictReader(open(paths.GRAPHICS_CSV, encoding='utf-8'))}
    P = {int(r['ram'], 16): r for r in csv.DictReader(open(paths.TEXT_DIR / 'PROG.csv', encoding='utf-8'))}
    d = disc.Disc(paths.ORIGINAL_BIN)
    prog, crw = d.read_file(d.find('PROG.BIN')), d.read_file(d.find('CRW.BIN'))
    rd = lambda b, a, n: b[a - BASE:a - BASE + n]  # noqa: E731

    # Edit Wrestler availability per page and index
    ptrs = struct.unpack('<16I', rd(prog, EDIT_TABLE, 64))
    avail = []
    for page, n in enumerate(EDIT_COUNTS):
        levels = [rd(prog, ptrs[page * 4 + lvl], n) for lvl in range(4)]
        avail.append([UNLOCK[tuple(min(lv[i], 1) for lv in levels)] for i in range(n)])

    def costume(model):
        out = []
        for p in struct.unpack('<4I', rd(prog, COSTUMES + model * 16, 16)):
            out.append((P[p]['english'], P[p]['japanese']))
        return out

    # Wrestlers: models 0-24, full name from the name plates, short name from the type label
    plates = {jp(G, f'0015_{i:03d}').replace(' ', ''): label(G, f'0015_{i:03d}') for i in range(82, 107)}
    full = {'Y. Kanemaru': 'Yoshinobu Kanemaru', 'M. Mossman': 'Maunakea Mossman'}  # plates shortened to fit
    crowns = {k: list(rd(crw, a, n)) for k, (a, n) in CROWNS.items()}

    def crowns_of(m):
        out = []
        for ch in ('succession', 'ascent'):
            if m in crowns[ch]:
                out.append(ch)
            elif m in crowns.get(ch + '_code1', []):
                out.append(ch + '_code1')
            elif m in crowns[ch + '_code2']:
                out.append(ch + '_code2')
        return out

    roster = []
    for m in range(25):
        name_jp = jp(G, f'0027_{51 + m:03d}').removesuffix('タイプ')
        en = plates[name_jp]
        roster.append({'id': m, 'name': full.get(en, en), 'jp': name_jp, 'short': label(G, f'0027_{51 + m:03d}'),
                       'crowns': crowns_of(m), 'edit': avail[0][m]})

    fictional = []
    for m in range(25, 44):
        fictional.append({'model': m, 'names': [{'name': e, 'jp': j} for e, j in costume(m)],
                          'edit': avail[0][m]})
    hidden = [{'model': m, 'name': costume(m)[0][0], 'jp': costume(m)[0][1]} for m in range(44, 51)]

    moves = [{'id': i, 'name': label(G, f'0027_{51 + i:03d}'), 'unlock': avail[1][i]} for i in range(60)]
    logic = [{'id': i, 'name': label(G, f'0027_{145 + i:03d}'), 'desc': label(G, f'0027_{164 + i:03d}'),
              'unlock': avail[2][i]} for i in range(19)]
    logic.append({'id': 19, 'name': '', 'desc': '', 'unlock': avail[2][19]})
    entrances = {}
    for u in avail[3]:
        entrances[u] = entrances.get(u, 0) + 1

    finishes = [{'jp': jp(G, f'0707_{i:03d}'), 'name': label(G, f'0707_{i:03d}')} for i in range(35, 62)]
    tours = [{'jp': jp(G, f'0046_{i:03d}'), 'name': label(G, f'0046_{i:03d}')} for i in range(45, 54)]
    venues = [{'jp': jp(G, f'0046_{i:03d}'), 'name': label(G, f'0046_{i:03d}')} for i in range(57, 93)]

    # Search entries: every wrestler and every Edit Wrestler type
    entries = []
    for w in roster:
        entries.append({'id': f'w{w["id"]}', 'name': w['name'], 'group': 'Wrestler', 'text': w['jp']})
    for f in fictional:
        for n in f['names']:
            entries.append({'id': f'f-{n["name"]}', 'name': n['name'], 'group': 'Fictional wrestler', 'text': n['jp']})
    for mv in moves:
        if mv['unlock'] != 'never':
            entries.append({'id': f'm{mv["id"]}', 'name': mv['name'], 'group': 'Move set', 'text': mv['unlock']})
    for lg in logic:
        if lg['name']:
            entries.append({'id': f'l{lg["id"]}', 'name': lg['name'], 'group': 'Logic', 'text': lg['desc']})

    return {'entries': entries, 'roster': roster, 'fictional': fictional, 'hidden': hidden,
            'moves': moves, 'logic': logic, 'entrances': entrances, 'crowns': crowns,
            'finishes': finishes, 'tours': tours, 'venues': venues}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0], epilog=paths.FOLDER_HELP,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--page', type=Path, default=paths.PROJECT / 'docs' / 'guide' / 'index.html')
    ap.add_argument('--check', action='store_true', help='only check that the page is up to date')
    args = ap.parse_args(paths.configure(sys.argv[1:] if argv is None else argv))
    if pagedata.write(args.page, build(), args.check) and args.check:
        print(f'{paths.show(args.page)}: up to date')


if __name__ == '__main__':
    main()
