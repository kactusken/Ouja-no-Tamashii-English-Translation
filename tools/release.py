#!/usr/bin/env python3
"""Build the release patches.

  release.py [--version VERSION] [--keep]   -> output/release/Zen-Translation-VERSION/ (+ .zip)

Every variant in VARIANTS is built with build.py and turned into an xdelta3 patch against the clean
original image - patches are never meant to be stacked: the translation relocates PROG.BIN and
regenerates EDC/ECC, so an unlock patch made for one image would land on the wrong bytes of another.
Each patch is then applied back to the original and checked against the built image.

Needs the xdelta3 command (Debian/Ubuntu: apt install xdelta3). Built images are deleted once their
patch is verified (they live in cache/release-stage/); --keep leaves them there.
Takes the same folder options as build.py; the release folder goes under <output>/release/.
"""
import argparse
import hashlib
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402
import paths  # noqa: E402

TITLE = 'Zen Nihon Pro Wres - Ouja no Tamashii'
RELEASE_NAME = 'Zen-Translation'

# (label in the file names, build.py options, one line for the README)
VARIANTS = [
    ('English', ['--unlocks', 'none'], 'the translation only'),
    ('English + Unlocks', ['--unlocks', 'all'], 'the translation with every unlock below'),
    ('Japan + Unlocks', ['--no-translation', '--unlocks', 'all'], 'the original Japanese game with every unlock below'),
]

# -S none: no secondary compression, which some patchers (Rom Patcher JS) can't decode.
# -A=: no application header (it would record local file paths).
XDELTA_ENCODE = ['xdelta3', '-e', '-9', '-S', 'none', '-A=', '-f']

README = '''\
{title} - English translation {version}
{rule}

PATCHES

Each patch is applied to the original Japanese disc image on its own (do not apply one on top of
another). Pick one:

{variants}

Unlocks:
  * Survival Match (and Title Match) on the mode select from the start - normally impossible to unlock.
  * Edit Wrestler: every body, move set, logic and entrance type open from the start (normally
    gated by clearing Path of the Five Crowns chapters), and the hidden bodies 44-50 at the end of
    the Body Type list.
  * Path of the Five Crowns: the full wrestler lists in both chapters (normally a button code).

ORIGINAL IMAGE

The patches need the Redump dump of the Japanese release, as a single-track BIN/CUE:

  {original}
  size   {size} bytes
  CRC32  {crc32}
  SHA-1  {sha1}

If your copy is a CHD, convert it back first with MAME's chdman:
  chdman extractcd -i "game.chd" -o "game.cue"

HOW TO PATCH

  Windows      Delta Patcher: Original file = the Japanese .bin, XDelta patch = the .xdelta file.
  Android      UniPatcher.
  Any browser  Rom Patcher JS (www.marcrobledo.com/RomPatcher.js).
  Command line xdelta3 -d -s "<Japanese .bin>" "<patch>.xdelta" "<output>.bin"

Save the patched image under the patch's name with .bin instead of .xdelta (as listed below) and
put the matching .cue file from this folder next to it - the .cue refers to the .bin by name.
Open the .cue in your emulator.

CHECKSUMS OF THE PATCHED IMAGES

{checksums}
'''


def hashes(path):
    """(SHA-1, CRC32) of a file in one pass."""
    sha1, crc = hashlib.sha1(), 0
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            sha1.update(chunk)
            crc = zlib.crc32(chunk, crc)
    return sha1.hexdigest(), f'{crc:08x}'


def run(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f'{cmd[0]} failed:\n{r.stderr.strip()}')


def main():
    ap = argparse.ArgumentParser(epilog=paths.FOLDER_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--version', default='dev', help='release version for the folder name and README (default: dev)')
    ap.add_argument('--keep', action='store_true', help='keep the built images in cache/release-stage/')
    args, folder_args = ap.parse_known_args()
    unknown = paths.configure(folder_args)
    if unknown:
        ap.error(f'unrecognized arguments: {" ".join(unknown)}')
    if not shutil.which('xdelta3'):
        sys.exit('xdelta3 not found (Debian/Ubuntu: apt install xdelta3)')
    original = paths.ORIGINAL_BIN
    if not original.exists():
        sys.exit(f'put the original disc image in {paths.show(paths.ORIGINAL_DIR)} (or pass --original)')

    print('verifying original image...')
    orig_sha1, orig_crc = hashes(original)
    if orig_sha1 != paths.ORIGINAL_SHA1:
        sys.exit(f'{original.name} does not match the expected Redump SHA-1 {paths.ORIGINAL_SHA1}')

    out = paths.OUTPUT / 'release' / f'{RELEASE_NAME}-{args.version}'
    stage = paths.CACHE / 'release-stage'
    for d in (out, stage):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    sums = []
    for label, options, _ in VARIANTS:
        name = f'{TITLE} ({label})'
        print(f'\n=== {name}')
        # build.main re-applies the folder options; --output only redirects the image to the stage
        built = build.main(folder_args + options + ['--output', str(stage), '--name', name, '--skip-verify'])
        shutil.move(stage / f'{name}.cue', out / f'{name}.cue')
        patch = out / f'{name}.xdelta'
        print(f'making {patch.name}')
        run(XDELTA_ENCODE + ['-s', original, built, patch])

        print('checking the patch against the original...')
        check = stage / 'check.bin'
        run(['xdelta3', '-d', '-f', '-s', original, patch, check])
        built_sha1, built_crc = hashes(built)
        if hashes(check) != (built_sha1, built_crc):
            sys.exit(f'{patch.name} does not reproduce {built.name}')
        check.unlink()
        sums.append((built.name, built_crc, built_sha1))
        if not args.keep:
            built.unlink()
        print(f'ok: {patch.name} ({patch.stat().st_size:,} bytes)')

    width = max(len(n) for n, *_ in sums)
    (out / 'checksums.txt').write_text(
        ''.join(f'{sha1}  {n}\n' for n, _, sha1 in sums), encoding='utf-8')
    (out / 'README.txt').write_text(README.format(
        title=TITLE, version=args.version, rule='=' * (len(TITLE) + len(args.version) + 25),
        variants='\n'.join(f'  {TITLE} ({label}).xdelta\n      {what}' for label, _, what in VARIANTS),
        original=paths.ORIGINAL_NAME, size=f'{original.stat().st_size:,}', crc32=orig_crc, sha1=orig_sha1,
        checksums='\n'.join(f'  {n:<{width}}  CRC32 {crc}  SHA-1 {sha1}' for n, crc, sha1 in sums),
    ), encoding='utf-8')
    archive = shutil.make_archive(str(out), 'zip', out.parent, out.name)
    if not args.keep:
        shutil.rmtree(stage)
    print(f'\ndone: {paths.show(out)}\n      {paths.show(archive)}')


if __name__ == '__main__':
    main()
