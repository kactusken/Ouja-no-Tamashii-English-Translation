# Technical notes - Zen Nihon Pro Wres: Ouja no Tamashii (SLPS-01849)

Redump image: `Zen Nihon Pro Wres - Ouja no Tamashii (Japan).bin`, single MODE2/2352 data track,
SHA-1 `1bc41b753496de3487538a68bbf49714001d7f03`.

## Disc layout

| LBA | File | Contents |
|---|---|---|
| 24 | `SLPS_018.49` | Main EXE, loads at `0x80010000` (text at file `0x800`), entry `0x80012a9c` |
| 141 / 270 / 390 / 462 / 31789 | `PROG.BIN`, `CRW.BIN`, `ENTER.BIN`, `MATCH.BIN`, `STAFF.BIN` | Code overlays, all load at **`0x8005c1c8`** |
| 138 | `HUROGO.BIN` | CMP1-compressed 16bpp TIM (160×84) |
| 614 | `DATALINK.ARC` | Menus/2D graphics, sound (SEQ/VAB), animation data. Only ~3 KB slack on disc. |
| 26374 | `DATAMATC.ARC` | 3D models (`M4`), no slack, STAFF.BIN follows directly |
| 31789 | `STAFF.BIN` | Followed by ~16 MB of unused sectors (free space if needed) |
| 40001+ | `A_D/ E_EA/ EB_G/ BGM/ *.XA` | XA audio (commentary/voice/music), not referenced by name in the EXE, may be addressed by LBA: **keep at original LBAs** |
| 198404 | `DUMMY.BIN` | 27 MB padding |

Filenames used by the EXE (at `0x80010000`): `\STAFF.BIN;1 \CRW.BIN;1 \MATCH.BIN;1 \ENTER.BIN;1 \PROG.BIN;1 \DATALINK.ARC;1 \DATAMATC.ARC;1 \HUROGO.BIN;1`.

## ARC1 archives

Opened by `0x80019d94(handle, name)`; handles at `0x8004f510` (DATALINK) and `0x8004f8f0` (DATAMATC).
Entry loader `0x80019efc`.

```
"ARC1" u32 count
count × { u32 offset, u32 size, u32 flags }     ; offset relative to end of table (8 + count*12)
data
```

DATALINK has 1659 entries: 262 TIM, 96 IMG3, 35 CMP1 (all wrap IMG3), 129 `pQES` (SEQ), 74 `pBAV` (VAB header) + 74 VAB bodies, ~987 entries with a `0x50` header (animation/motion?), 2 `M4`.
DATAMATC: 164 entries, mostly `M4` models; textures may be embedded (not yet investigated).

Flags: values 1, 2, 3, 6, 10, 35, 36, 112 seen; passed to `0x8001a804` as a halfword. Meaning unknown, preserved as-is.

## CMP1 compression (BPE)

`"CMP1" u32 decompressed_size` + Philip Gage byte-pair-encoding stream. Decoder at `0x80013c44`
(`decompress(size, src+8, dst)`), CMP1 check at `0x80013e04`. Original encoder parameters match Gage's
reference: block size 5000, MAX_CHARS 200, threshold 3, codes assigned from 255 downward.
`tools/bpe.py` reproduces this (≈1% smaller than the original on average) and retries other block
settings when a result must fit a fixed slot.

## IMG3 image container

```
"IMG3" u32 n_images  u32 n_cluts  u32 n_pairs  u32 0
n_pairs × { u16 clut_record (0xFFFF = chosen at runtime), u16 image_index }
(n_cluts + n_images) × { u32 data_offset, u32 mode, u16 vram_x, u16 vram_y, u16 w, u16 h }
data
```
CLUT records first, then image records. Mode: 0 = 16-bit (CLUTs), 8 = 4bpp, 9 = 8bpp. `w` is in 16-bit
VRAM units. Images with clut `0xFFFF` (e.g. the small glyph-like sprites at VRAM x 576–640 in entry 707)
get their palette from code; the exporter borrows the previous explicit palette for display only.

## Text

* **Most visible text is graphics**: menu buttons, mode descriptions, option labels, name plates
  (e.g. DATALINK entries 13, 28, 29). Edit via `gfx.py`.
* **Shift-JIS strings** in overlays: `PROG.BIN` (costume names, memory-card titles), `STAFF.BIN`
  (credits + Giant Baba tribute text), `CRW.BIN` (memory-card titles, chapter names, dates).
  Pointers are absolute RAM addresses (`0x8005c1c8 + offset`).
* Main EXE has a full-width ASCII table at file `0x38800` (`　！”＃…`), probably used to convert
  ASCII to full-width for runtime-rendered text. Not yet traced.
* Memory card save titles are shown by the BIOS (full-width SJIS, max 64 bytes, prefixed by
  `BISLPS-01849 …` product codes).

## Text rendering (verified in-game 2026-10-08)

* **ASCII is not drawn.** The credits renderer (STAFF.BIN string loop 0x800622e0 → char renderer
  0x800625bc) always steps 2 bytes per character and draws each 16-bit code: custom 16×16 glyphs in
  STAFF.BIN for full-width digits/A–Z/a–z (codes 0x824F–0x829A), katakana and a few punctuation marks;
  everything else via the BIOS kanji ROM (`Krom2RawAdd` stub 0x800355d4, wrapper 0x800349b4), which
  turns non-SJIS codes into 0x8140 (blank). → `text.py` stores English as **full-width SJIS** by default.
* Spacing is proportional: the loop clears bit 15 of "narrow" characters in place (full-width
  alphanumerics, katakana, 、。ー”（）space) and advances 10 px for them, 8 px for space, 16 px for kanji.
* Credit records are `{s32 x, char *text, s32 y?}` (12 bytes); x offsets were laid out for the Japanese.
* Memory-card titles (BIOS-displayed) work as full-width SJIS ("ＡＪＰＷ　Ｓｙｓｔｅｍ" confirmed).

## Memory layout

* Overlays load at 0x8005c1c8; heap starts at **0x800a7b60** (= end of MATCH.BIN, the largest overlay;
  set by 0x800144a0 → heap init 0x80035ab4). No overlay references RAM past its own file end
  (`tools/ramscan.py`), so PROG/STAFF/CRW can grow up to the heap. `text.py` appends overflow strings.
* Overlay table at 0x8003d7c4: {name, entry} × 5: 0 PROG (title/menus), 1 ENTER, 2 MATCH, 3 CRW, 4 STAFF.
  Main loop 0x800113c0 calls load_overlay(index) at 0x8001127c; the first index comes from the delay
  slot at 0x80011424 (`build.py --boot` patches it for test builds).
* Files are found by name (CdSearchFile-style table filled at boot), so `disc.py` may relocate a file
  that outgrows its slot into free sectors (LBA 31815–39999 after STAFF.BIN is empty) and update its
  directory record.

## Hidden modes (mode select)

Mode select (PROG, loads DATALINK group 13 at 0x8005ebec) sets its button count at 0x8005ec8c:
8 normally, 9 if byte **0x8004f560** ≠ 0 (adds Title Match), 10 if byte **0x80048580** ≠ 0 (adds
Survival). Buttons/descriptions/icons are images 17+i / 27+i / 37+i of group 13.

* 0x8004f560 is a bitfield: 0x8006b784 sets bit 0 or bit 1 depending on which Five Crowns chapter was
  cleared (0x174 in the career struct) - clearing either chapter unlocks Title Match. CRW.BIN 0x8005e8b0
  also stores 1.
* 0x80048580 (Survival) is only written by: boot init (EXE 0x800119a8, cleared), System-data load
  (0x8006c850, from save offset 0x1639) and an uncalled developer debug handler (0x8007e940,
  Square bit 0x80). No normal gameplay path sets it in this build.
* Both are saved in the System data (save 0x8006e8d4).
* **Our patch** (`build.py` CODE_PATCHES): the `beqz` at 0x8005ecbc becomes `nop`, so the menu always
  shows 10 modes (Title Match included). The flags themselves and save data are untouched.

### Other saved flags (System data offsets 0x1638-0x163c, loaded at 0x8006c80c)

| RAM | save | set by | used by |
|---|---|---|---|
| 0x80049500 | 0x163c | load only (cleared at boot) | Edit Wrestler (screen 0x8006eb6c): SELECT held + flag → body model swap at 0x8006fa1c |
| 0x80049501 | 0x1638 | load, debug handler (Triangle); cleared at boot (EXE 0x800113cc) | ENTER.BIN developer entrance editor, see below |
| 0x8004f508 | 0x163b | many PROG writes | memory-card / edit data, not an unlock |

**Entrance editor (0x80049501 ≠ 0), ENTER.BIN:** 0x8005cad8 skips the normal entrance setup for a fixed
4-wrestler scene and enables the debug button masks (0x8007eb8c = 0xffcc, 0x8007eb90 = 0x8033);
0x8005d0a0 runs 0x700 instead of 0x500 frames; 0x8005ded8 loops the entrance instead of going on to the
match (normal path sets next overlay 3 = MATCH). Hold **R1** (0x8005d930) → FntPrint overlay 0x80066c30
("BASE/FOCUS X Y Z", "ROLL", "WORLD/WRESTLER", "%dP X Y Z Direct Motion Frame", "Wrestler%1d[%02d] Color",
"COL SPD NOW END", "Now Task", "Test/Test2", "Quick/Slow"). Hold **L1** + pad (0x8005d510) → one of
4 edit pages (0x80063798 / 63d84 / 6405c / 64478, page in 0x8007eca8). Strings at 0x8005c710-0x8005c8b4.

Model/costume-name table at 0x8008c808 (4 names per model) - only read by the edit-wrestler save code
(0x8006e0f8): memory-card title = slot number ("１　".."１５　", table 0x8008cb74) + costume name for the
edit wrestler's body model (edit struct +0x140) and colour (+0x141). So these names are only visible in the
BIOS / emulator memory-card manager. Models: 0-24 roster (Baba first), 25-43 generic
models with 4 named variants each (76 fictional wrestlers), 44-50 specials: Inoue / Asako / Shiga /
Kanemaru in track suits, Takeshi Morishima, Mossman track suit, referee Kyohei Wada.
Swap table 0x8005d434 (index = model id < 23): Baba→50 Wada, Taue→48 Morishima, Inoue→44,
Asako→45, Shiga→46, Kanemaru→47, Mossman→49. Pad bits are libetc PadRead (0x100 = SELECT).

### Edit Wrestler unlocks

Left/Right in the edit pages (0x8006f5c0 / 0x8006f6c0) skip values whose byte in an availability array
is not 1. Array = *(0x8008d37c + (page-1)*16 + A*4), A = Title Match flag 0x8004f560 (Five Crowns
chapter bits). Pages: 1 body model (44: models 0-43), 2 move-set type (60, labels 0027_051-110),
3 logic (20, labels 0027_145-163), 4 entrance (40). A=0: bodies 0-22 + 24 only; chapter bit 0 adds
Tsuruta + 11 fictional bodies, bit 1 adds Tsuruta + the other 8; both = all 44. Bit 0 = Succession, bit 1 = Ascent
(PROG 0x8006b784 ors in 1 when career byte +0x174 is 0, else 2; *from the code*). Never available even
with A=3: move sets 58-59, logic 19, entrances 37-39 (page 4 uses array 0x8008d354 instead when
0x8009351e is set - move set 0x24 with logic 0/2, see 0x8006f924). Models 44-50 are not in the list
at all - only the SELECT swap (0x8006fa1c) reaches them.
Menu maximums: halfwords at 0x8005d3d4, (page-1)*3 + row: body (11, 43, 3), moves (57, 0, 0), logic
(18, 5, 2), entrance (36, 43, 0) - the "never available" entries are simply past these maximums.
Body Type labels are images 0027_051 + body (0027_094 = body 43).
**Our patches:** body-type maximum 43 → 50 (hidden models in the list); all 16 table pointers → the A=3 arrays. SELECT swap: also gated by `bne` at 0x8006fa14 (requires 0x8004f560 == 3, both Five
Crowns chapters) before the 0x80049500 check - found with the DuckStation GDB server; both → `nop`. Options that stay locked even at A=3 remain locked.

### Wrestler body textures

MATCH.BIN loads DATALINK entry **0x30b + model*8 + slot** (0x80096c20; model/colour from bytes +0x18/+0x19).
Entries 779-1186 = 51 models x 8 slots (slots 0-3 = the 4 colours; 4-7 unknown, often copies). Format in
`tools/bodytex.py` (records of VRAM rects, 8bpp pixels, 256-colour CLUTs; CLUT row 496 = first CLUT).
DATAMATC.ARC 0003-0060 are the M4 meshes (geometry only), 0062-0119 per-model offset tables.
DATALINK 0531-0706 (4 per model 0-43) are the brush-lettered name banners, not textures.
A few tiles decode with odd colours - CLUT selection is not fully understood yet.

## Move sets (work in progress)

*From the code* (MATCH.BIN loader 0x80096dec-0x80096fb0). Match wrestler slots at 0x8004f920, 4 x 0xf0 bytes:
+0x18 body model, +0x19 colour, +0x1e in use, +0x2b move set (0-57; 58 and up fall back to 1), +0x29 / +0x2c
logic (0xff at +0x29: CPU logic +0x2c). Per slot the match loads:

| Source | Entry | What |
|---|---|---|
| DATALINK | 0x4c3 + model*8 + colour | body mesh |
| DATALINK | 0x30b + model*8 + colour | body textures (see above) |
| DATAMATC | 3 + move set | the move set's animation bank (M4: "M4" u16 count, u32 offsets, records) |
| DATAMATC | 0x3e + move set | the move set's command table (26-31 KB; u32 id, 16 sub-table offsets, file-relative pointers) |
| DATAMATC | 0x78 / 0x91 + logic | 1 KB CPU logic tables |

DATAMATC 0-2 are shared M4 banks (188, 740 and 2975 records). The 58 move-set banks hold 14,948 records but
only 2,838 distinct ones, 2,781 of them also in banks 0-2: a move set is a selection from one master animation
library. No move names exist as text anywhere on the disc (only the 27 finish labels 0707_035-061); the
play-by-play commentary (XA files A_D/ E_EA/ EB_G/) is the only place the game names moves.

## Path of the Five Crowns chapters

Chapter select (PROG, DATALINK group 31, cursor 0x8009351a) stores the choice in byte **0x8004f824** on
confirm (0x8005f8c0): 0 = 王道継承編 Succession (top button), 1 = 王道飛躍編 Ascent. The career struct
keeps a copy at +0x174 (save title 0x8008f588, chapter tag sprite, clear bit at 0x8006b784). CRW.BIN
reads 0x8004f824 in 16 places; the chapters differ in:

* **Wrestler list** (0x80063f60, called when wrestler select is set up; list -> 0x80095918, count
  0x80095925). Ids are the model / Body Type ids:

  | Chapter | Normally | Hold SELECT+R2 | Hold SELECT+R2+START+L1 |
  |---|---|---|---|
  | Succession | 8 @ 0x8005c674: Misawa, Kawada, Taue, Kobashi, Akiyama, Hase, Hansen, Vader | 10 @ 0x8005c67c: + Fuchi, Ogawa | 12 @ 0x8005c688: + Tsuruta, Baba |
  | Ascent | 10 @ 0x8005c694: Omori, Honda, Izumida, Inoue, Shiga, Albright, Johnny Ace, Johnny Smith, Kimala, Mossman | 10 | 13 @ 0x8005c6a0: + Kanemaru, Kikuchi, Asako |

  Buttons are the held mask at *(0x8003ee8c)+2 (the game's pad state: +2 held, +4 pressed, +6 repeat;
  standard libetc bits, e.g. 0x20 circle = confirm, 0x40 cross = cancel). Button combos read from the
  code, not yet tried on a real pad. **Our patch** (`build.py` CODE_PATCHES): the four `bne`s at
  0x800640c0 / 0x800640dc / 0x80064118 / 0x80064124 -> `nop`, so both chapters always offer the full list.
* **Length**: Succession ends after 1 year, Ascent after 2 (end checks e.g. 0x8006b57c, 0x8006806c on
  bytes 0x80095182 / 0x80095183, apparently year and month).
* **Schedule**: career setup (0x80060e08) copies per-week tables (12 months x 4 weeks, one byte per
  week) into the live schedule. Succession reads one year from 0x800908a0, 0x80090900, 0x80090b10 /
  0x80090b40 (alternating), 0x80090bd0, 0x80090c60, 0x80090cf0, 0x80090a20; Ascent two years from
  0x80090960, 0x800909c0, 0x80090b70, 0x80090c00, 0x80090c90, 0x80090d20, 0x80090a50; 0x80090ab0 is
  shared. The id sets barely overlap (cards, opponents, venues - which table is which is not mapped).
  0x800648ec also patches six specific weeks per chapter.
* The in-game descriptions (0031_012 / 0031_013) only differ in the time limit; the English names the
  roster difference too.

## Open questions

- Which PROG strings (costume names, fictional roster) are displayed, and by which renderer?
- Is any text in DATAMATC model textures (ring aprons, banners, entrance screens)?
- Meaning of ARC flags; whether any code hard-codes ARC offsets (repacking keeps unchanged offsets, so
  this only matters for entries that grow and get appended).
- Are XA files addressed by LBA? (Matters only if we ever need to relocate files.)
