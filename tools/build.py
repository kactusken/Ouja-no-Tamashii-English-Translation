#!/usr/bin/env python3
"""Build the translated disc image.

  build.py [--name NAME] [--unlocks all|none|GROUP,...]   -> output/NAME.bin + output/NAME.cue
                                (default: "Zen Nihon Pro Wres - Ouja no Tamashii (English)")
  unlock groups: survival (Survival/Title Match), edit (Edit Wrestler), crowns (Five Crowns rosters);
  default all - or none with --no-translation, so that alone stays byte-identical to the original

Steps (default folders shown; move any of them with the folder options - see --help):
  1. copy the original BIN from original-game/ (verified by SHA-1)
  2. text: translation/text/<FILE>.csv rows with an 'english' value go into <FILE> (PROG.BIN, ...)
  3. gameplay patches picked by --unlocks (CODE_PATCHES: Survival Match, Edit Wrestler unlocks +
     hidden bodies 44-50, full Five Crowns rosters)
  4. graphics: automatic renders from translation/graphics.csv, overridden by
     translation/images-handmade/ (also applied to duplicates); imported into DATALINK.ARC.
     The final English set is also written to review/images-english/.
  5. every modified file is written back into the image (EDC/ECC regenerated)
"""
import argparse
import csv
import hashlib
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc  # noqa: E402
import disc  # noqa: E402
import gfx  # noqa: E402
import paths  # noqa: E402
import render  # noqa: E402
import staff_layout  # noqa: E402
import text  # noqa: E402
from text import OVERLAY_BASE  # noqa: E402

# Main loop at 0x800113c0 calls load_overlay(index) (0x8001127c); the first call's argument is set
# by the delay-slot instruction at 0x80011424 ("move $a0, $zero" -> PROG, the title/menus).
# Overlay table at 0x8003d7c4: 0 PROG, 1 ENTER, 2 MATCH, 3 CRW, 4 STAFF.
BOOT_PATCH_OFFSET = 0x800 + (0x80011424 - 0x80010000)
BOOT_PATCH_ORIGINAL = 0x00002021
BOOT_OVERLAYS = {'prog': 0, 'enter': 1, 'match': 2, 'crw': 3, 'staff': 4}

# Gameplay patches ("unlocks"): (group, file, RAM address, original word, new word, description).
# Groups can be picked separately with --unlocks.
# Mode select (0x8005ec8c) shows 8 modes, 9 if Title Match is unlocked (Five Crowns cleared) and 10 if
# byte 0x80048580 is set - which no normal gameplay sets (see docs/NOTES.md "Hidden modes"). Skipping
# that check always shows all 10, i.e. Survival (and Title Match, which sits before it) from the start.
CODE_PATCHES = [
    ('survival', 'PROG.BIN', 0x8005ecbc, 0x10400003, 0x00000000, 'Survival Match unlocked'),  # beqz $v0 -> nop
    # Edit Wrestler: SELECT held while confirming the Body page swaps in the hidden models 44-50.
    # Originally gated by both Five Crowns chapters cleared (flag 0x8004f560 == 3, bne at 0x8006fa14)
    # and by byte 0x80049500, which nothing sets (beqz at 0x8006fa3c) - confirmed with the debugger.
    ('edit', 'PROG.BIN', 0x8006fa14, 0x1486002c, 0x00000000, 'Edit Wrestler: SELECT swap without Five Crowns'),
    ('edit', 'PROG.BIN', 0x8006fa3c, 0x10400022, 0x00000000, 'Edit Wrestler: SELECT swap without hidden flag'),
    # Edit Wrestler menu maximums (halfwords at 0x8005d3d4: body size 11, body type 43, colour 3, ...):
    # body type 43 -> 50 puts the hidden models 44-50 at the end of the Body Type list (their
    # availability bytes, read past the 44-byte array, are 1).
    ('edit', 'PROG.BIN', 0x8005d3d4, 0x002b000b, 0x0032000b, 'Edit Wrestler: hidden bodies 44-50 in Body Type list'),
    # Path of the Five Crowns wrestler select (CRW 0x80063f60): each chapter has its own list, extended
    # while SELECT+R2 (and START+L1) are held. Skipping the button checks always gives the full lists:
    # Succession 12 (adds Fuchi, Ogawa, Tsuruta, Baba), Ascent 13 (adds Kanemaru, Kikuchi, Asako).
    ('crowns', 'CRW.BIN', 0x800640c0, 0x1462001d, 0x00000000, 'Five Crowns: full Succession roster'),
    ('crowns', 'CRW.BIN', 0x800640dc, 0x14430016, 0x00000000, None),
    ('crowns', 'CRW.BIN', 0x80064118, 0x14620006, 0x00000000, 'Five Crowns: full Ascent roster'),
    ('crowns', 'CRW.BIN', 0x80064124, 0x14620003, 0x00000000, None),
]

# Edit Wrestler availability arrays are picked by the Five Crowns chapter flags (table at 0x8008d37c,
# 4 pointers per page for levels 0-3). Point levels 0-2 at the level 3 ("both chapters cleared")
# array so all bodies, move sets, logic and entrance types are open from the start.
EDIT_AVAILABILITY = [  # page: (level 0, level 1, level 2), level 3
    ((0x8008d0c4, 0x8008d0f0, 0x8008d11c), 0x8008d148),  # body
    ((0x8008d174, 0x8008d1b0, 0x8008d1ec), 0x8008d228),  # move set
    ((0x8008d264, 0x8008d278, 0x8008d28c), 0x8008d2a0),  # logic
    ((0x8008d2b4, 0x8008d2dc, 0x8008d304), 0x8008d32c),  # entrance
]
UNLOCK_GROUPS = ('survival', 'edit', 'crowns')
for page, (locked, unlocked) in enumerate(EDIT_AVAILABILITY):
    for level, ptr in enumerate(locked):
        CODE_PATCHES.append(('edit', 'PROG.BIN', 0x8008d37c + page * 16 + level * 4, ptr, unlocked,
                             'Edit Wrestler: everything unlocked' if page == level == 0 else None))


def sha1_file(p):
    h = hashlib.sha1()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def ensure_work():
    """Extracted game files (cache/) and original images (review/images-japanese/) the tools need."""
    if not (paths.GAME_FILES / 'STAFF.BIN').exists():
        print(f'extracting disc files to {paths.show(paths.GAME_FILES)} ...')
        disc.main(['extract', str(paths.ORIGINAL_BIN), str(paths.GAME_FILES)])
    if not paths.JAPANESE_IMAGES.exists():
        print('unpacking DATALINK.ARC and exporting the original images ...')
        arc.unpack(paths.GAME_FILES / 'DATALINK.ARC', paths.UNPACKED / 'DATALINK')
        gfx.export(paths.UNPACKED / 'DATALINK', paths.JAPANESE_IMAGES)


def unlock_groups(value):
    """--unlocks: all / none / a comma-separated list of UNLOCK_GROUPS."""
    if value == 'all':
        return set(UNLOCK_GROUPS)
    if value == 'none':
        return set()
    groups = {g.strip() for g in value.split(',') if g.strip()}
    if not groups or groups - set(UNLOCK_GROUPS):
        raise argparse.ArgumentTypeError(f'expected all, none or some of {",".join(UNLOCK_GROUPS)}')
    return groups


def main(argv=None):
    ap = argparse.ArgumentParser(epilog=paths.FOLDER_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--name', default='Zen Nihon Pro Wres - Ouja no Tamashii (English)')
    ap.add_argument('--skip-verify', action='store_true', help="don't hash the original image")
    ap.add_argument('--boot', choices=sorted(BOOT_OVERLAYS), help='TEST BUILD: boot straight into this overlay '
                    '(e.g. staff = ending credits) instead of the title screen')
    ap.add_argument('--no-translation', action='store_true',
                    help='skip text and graphics (with --boot: a Japanese control build)')
    ap.add_argument('--unlocks', type=unlock_groups, metavar='all|none|GROUP,...',
                    help=f'gameplay patches to apply: all, none or some of {",".join(UNLOCK_GROUPS)} '
                    '(default: all, or none with --no-translation)')
    args = ap.parse_args(paths.configure(sys.argv[1:] if argv is None else argv))
    if args.unlocks is None:
        args.unlocks = set() if args.no_translation else set(UNLOCK_GROUPS)
    original, out_dir, work = paths.ORIGINAL_BIN, paths.OUTPUT, paths.BUILD_TMP

    if not original.exists():
        sys.exit(f'put the original disc image in {paths.show(paths.ORIGINAL_DIR)} (or pass --original): '
                 f'{original.name}')
    if not args.skip_verify:
        print('verifying original image...')
        if sha1_file(original) != paths.ORIGINAL_SHA1:
            sys.exit(f'{original.name} does not match the expected Redump SHA-1 {paths.ORIGINAL_SHA1}')
    out_dir.mkdir(parents=True, exist_ok=True)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    out_bin = out_dir / f'{args.name}.bin'
    print(f'copying -> {out_bin.name}')
    shutil.copyfile(original, out_bin)
    d = disc.Disc(out_bin, writable=True)
    patched = {}

    # text
    on_disc = {e.path.lstrip('/').upper() for e in d.files()}
    for csv_path in [] if args.no_translation else sorted(paths.TEXT_DIR.glob('*.csv')):
        iso_name = csv_path.stem if '.' in csv_path.stem else csv_path.stem + '.BIN'
        if iso_name.upper() not in on_disc:
            continue  # not a file on the disc
        e = d.find(iso_name)
        src = work / f'orig_{iso_name}'
        src.write_bytes(d.read_file(e))
        dst = work / iso_name
        if text.insert(csv_path, src, dst):
            sys.exit(f'text errors in {csv_path.name}')
        if iso_name == 'STAFF.BIN':
            laid_out, bad = staff_layout.relayout(src.read_bytes(), dst.read_bytes())
            if bad:
                sys.exit('credit lines too wide for the screen')
            dst.write_bytes(laid_out)
        if dst.read_bytes() != src.read_bytes():
            patched[iso_name] = dst

    # gameplay patches
    for group, iso_name, addr, old, new, what in CODE_PATCHES:
        if group not in args.unlocks:
            continue
        dst = patched.get(iso_name)
        if dst is None:
            dst = work / iso_name
            dst.write_bytes(d.read_file(d.find(iso_name)))
        data = bytearray(dst.read_bytes())
        off = addr - OVERLAY_BASE
        assert struct.unpack_from('<I', data, off)[0] == old, f'{iso_name} patch site mismatch at {addr:#x}'
        struct.pack_into('<I', data, off, new)
        dst.write_bytes(data)
        patched[iso_name] = dst
        if what:
            print(f'patch: {what}')

    # graphics: automatic renders, then hand-made images override (and cover their duplicates)
    pngs_by_arc = {}
    if not args.no_translation:
        ensure_work()
        final = pngs_by_arc.setdefault(paths.ARCHIVE, {})
        auto = render.run(paths.AUTO_RENDERS / paths.ARCHIVE)
        for p in sorted(auto.glob('*.png')):
            final[p.name] = p
        dups = {}
        with open(paths.GRAPHICS_CSV, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r['dup_of']:
                    dups.setdefault(r['dup_of'], []).append(r['image'])
        dupdir = work / 'handmade_dups'
        for p in sorted(paths.HANDMADE.glob('*.png')) if paths.HANDMADE.exists() else []:
            if p.stem.endswith(('_japanese', '_english', '_palette', '_check')):
                continue  # reference files written by edit.py
            if not (paths.JAPANESE_IMAGES / f'{p.stem}.json').exists():
                print(f'  ignoring {p.name}: not an image name (expected e.g. 0013_018.png)')
                continue
            if not (paths.HANDMADE / f'{p.stem}.json').exists():
                shutil.copyfile(paths.JAPANESE_IMAGES / f'{p.stem}.json', paths.HANDMADE / f'{p.stem}.json')
            final[p.name] = p
            for dup in dups.get(p.stem, []):
                if (paths.HANDMADE / f'{dup}.png').exists():
                    continue  # the duplicate has its own hand-made version
                dupdir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dupdir / f'{dup}.png')
                shutil.copyfile(paths.JAPANESE_IMAGES / f'{dup}.json', dupdir / f'{dup}.json')
                final[f'{dup}.png'] = dupdir / f'{dup}.png'
        # the final English set, for browsing
        if paths.ENGLISH_IMAGES.exists():
            shutil.rmtree(paths.ENGLISH_IMAGES)
        paths.ENGLISH_IMAGES.mkdir(parents=True)
        for name, p in final.items():
            shutil.copyfile(p, paths.ENGLISH_IMAGES / name)
    for arc_base, pngs in sorted(pngs_by_arc.items()):
        arc_name = arc_base + '.ARC'
        orig = work / f'orig_{arc_name}'
        orig.write_bytes(d.read_file(d.find(arc_name)))
        unpacked = work / arc_base
        arc.unpack(orig, unpacked)
        print(f'importing {len(pngs)} images into {arc_name}')
        for p in pngs.values():
            gfx.import_png(work, p, quiet=True)
        dst = work / arc_name
        arc.pack(unpacked, dst, orig)
        patched[arc_name] = dst

    if args.boot:
        exe_name = 'SLPS_018.49'
        exe = bytearray(d.read_file(d.find(exe_name)))
        assert struct.unpack_from('<I', exe, BOOT_PATCH_OFFSET)[0] == BOOT_PATCH_ORIGINAL, 'boot patch site mismatch'
        struct.pack_into('<I', exe, BOOT_PATCH_OFFSET, 0x24040000 | BOOT_OVERLAYS[args.boot])  # addiu $a0, $zero, N
        dst = work / exe_name
        dst.write_bytes(exe)
        patched[exe_name] = dst
        print(f'TEST BUILD: boots into {args.boot.upper()} overlay')

    # write back: files that fit in place first, so relocated ones don't steal their room
    def fits(item):
        e = d.find(item[0])
        return (item[1].stat().st_size + 2047) // 2048 <= d.allocated_sectors(e)
    for name, path in sorted(patched.items(), key=lambda kv: not fits(kv)):
        d.write_file(d.find(name), path.read_bytes(), relocate=True)
        print(f'patched {name}')
    d.f.close()
    (out_dir / f'{args.name}.cue').write_text(
        f'FILE "{out_bin.name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    print(f'done: {out_bin}  ({len(patched)} files patched)')
    return out_bin


if __name__ == '__main__':
    main()
