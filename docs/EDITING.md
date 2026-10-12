# Editing images by hand

Example: the main-menu button **0013_018** ("Exhibition Match"). Commands are shown run from the project
folder with the default folder layout; every tool also accepts the folder options (`--translation`,
`--review`, ... - see `--help` of `build.py`) if yours live elsewhere.

## 1. Find the image

```sh
.venv/bin/python tools/edit.py list exhibition
```
Or browse `review/compare/` (side-by-side sheets) or `review/images-japanese/`.

## 2. Set it up

```sh
.venv/bin/python tools/edit.py start 0013_018
```

Everything lands in **one folder**, `translation/images-handmade/`:

| File | What it is |
|---|---|
| `0013_018.png` | **the file you edit** (starts as the current English version) |
| `0013_018_japanese.png` | the original, same size and palette - for reference |
| `0013_018.json` | tells the build where the image goes - leave it alone |

The build ignores the `_japanese` (and later `_check`) files, so you can leave them there.
It also prints the size, colour depth (16 or 256 colours) and how many duplicates your edit covers.
(`edit.py refs 0013_018` writes reference files to `review/edit/` without starting an edit.)

## 3. Edit

Open `translation/images-handmade/0013_018.png`:

- **Aseprite**: opens in Indexed mode; save as PNG.
- **GIMP**: keep Image › Mode › *Indexed*; use File › **Export As** › PNG and overwrite the file.
- **Photoshop**: Image › Mode › *Indexed Color* with the existing palette.

Rules: keep the **same size**; prefer the image's **own colours** (RGB works too - colours get snapped
to the nearest palette colour, which matters most on 16-colour images); keep transparent areas
transparent; save over the same file name (not `0013_018-export.png`).

## 4. Check

```sh
.venv/bin/python tools/edit.py check 0013_018
```
`OK`, or a `!` line saying what to fix. `translation/images-handmade/0013_018_check.png` shows the
original above your version.

## 5. Build and test

```sh
.venv/bin/python tools/build.py
```
Load `output/Zen Nihon Pro Wres - Ouja no Tamashii (English).cue`. Your edit is also applied to every
duplicate of the image, and shows up green (**HAND**) in `tools/compare.py` sheets.

## 6. Approve (when you're happy with it)

```sh
.venv/bin/python tools/edit.py approve 0013_018
```
Checks the image one last time, converts it to the game's palette if you saved RGB, moves it to
`translation/images-approved/` (marked `done` in `graphics.csv`; images that weren't listed get a row)
and removes its files from `translation/images-handmade/` - so that folder only holds what you're
still working on. Duplicates keep using it. To rework it later, just `edit.py start 0013_018` again
(it starts from the approved version). If the check reports a problem, fix it or use `--force`.

**Several at once:** `start`, `check`, `approve` and `refs` take multiple names (spaces or commas) and ranges:

```sh
.venv/bin/python tools/edit.py start 0013_027 0013_028 0013_029
.venv/bin/python tools/edit.py check 0013_027 0013_028 0013_029   # ends with "2/3 OK - needs attention: …"
.venv/bin/python tools/edit.py approve 0013_027 0013_028 0013_029
.venv/bin/python tools/edit.py start 0017_020-0017_052      # a range (also 0017_020..0017_052 or 0017_020-052)
```
Ranges include every image between the two names; exact duplicates are left out (they follow their
original).

**Undo:** `.venv/bin/python tools/edit.py reset 0013_018` removes the hand edit - in progress or
approved - and goes back to the automatic English version (or the untouched original for images that
had no text). Use this rather than deleting files by hand: an approved edit also has a row in
`graphics.csv`, and `reset` cleans that up too. Ranges work here as well.

## Editing many similar images as one sheet

For a group of images that share artwork (e.g. the option buttons), edit them together in one file:

```sh
.venv/bin/python tools/edit.py sheet start buttons 0017_020-0017_052
```
This writes to `translation/images-handmade/sheets/`:

| File | What it is |
|---|---|
| `buttons.png` | **the sheet you edit** - each image as **Japanese \| English** side by side (like the compare sheets), at original size, name above |
| `buttons.sheet.json` | where each image sits - don't move images around on the sheet |

Edit the **English (right-hand)** image of each pair. Transparent pixels show as **magenta**
(255,0,255) - paint magenta (or erase) to make pixels transparent, and avoid pure magenta otherwise.
The sheet is full colour (each image has its own palette); only the English rectangles are read back, so
the Japanese side, label strips and gaps can be used for notes. Then:

```sh
.venv/bin/python tools/edit.py sheet check buttons     # which images changed + buttons_check.png:
                                                       #   how they'll look after palette snapping
.venv/bin/python tools/edit.py sheet split buttons     # cut changed images into translation/images-handmade/
.venv/bin/python tools/edit.py sheet approve buttons   # or: split + approve them all + remove the sheet
.venv/bin/python tools/edit.py sheet list              # existing sheets
```
Untouched images are skipped. If you edited one of the sheet's images individually after making the
sheet, `split` stops rather than overwrite it (add `--force` to overwrite).
