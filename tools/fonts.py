#!/usr/bin/env python3
"""Pixel fonts for redrawing the game's text graphics.

LARGE  - the game's own Latin glyphs (the 16x16 full-width set the credits use, stored in STAFF.BIN),
         cap height 11. Loaded from the disc at runtime, so no game data lives in the repo.
         Punctuation the game lacks is drawn here in the same 1-pixel-stroke style.
MEDIUM - condensed companion with cap height 7, for small labels.
TINY   - 3x5 capitals for the tightest spots (prefecture tiles, finish labels).

A font is {char: Glyph}; glyph rows are strings of '#'/'.', all the same height per font, with the
baseline at `font.baseline`. Widths are taken from the rows (proportional).
"""
from dataclasses import dataclass, field

from text import OVERLAY_BASE

STAFF_GLYPHS = [(0x80066724, '0123456789'),
                (0x80066864, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),
                (0x80066ba4, 'abcdefghijklmnopqrstuvwxyz')]


@dataclass
class Font:
    name: str
    height: int          # rows per glyph
    baseline: int        # row index of the baseline (last row of capitals)
    space: int           # advance of ' '
    spacing: int = 1     # gap between glyphs
    line_gap: int = 2    # extra pixels between lines
    upper_only: bool = False
    glyphs: dict = field(default_factory=dict)

    def glyph(self, ch):
        if self.upper_only:
            ch = ch.upper()
        return self.glyphs.get(ch) or self.glyphs.get(FALLBACK.get(ch, '?'))

    def width(self, text):
        w = 0
        for i, ch in enumerate(text):
            w += self.space if ch == ' ' else len(self.glyph(ch)[0])
            if i < len(text) - 1 and ch != ' ' and text[i + 1] != ' ':
                w += self.spacing
        return w

    @property
    def line_height(self):
        return self.height + self.line_gap


FALLBACK = {'’': "'", '‘': "'", '“': '"', '”': '"', '…': '.', '−': '-', '–': '-', '—': '-',
            '〜': '~', '・': '.', '･': '.', '·': '.', '•': '.', '×': 'x', '　': ' ', '!': '!', '？': '?', '！': '!'}


def _parse(src, height, pad_top=0):
    """'X' line followed by rows; glyph rows padded to `height`."""
    out = {}
    for block in src.strip('\n').split('\n\n'):
        lines = block.split('\n')
        ch = lines[0][0] if lines[0] != 'SPACE' else ' '
        rows = [''] * pad_top + lines[1:]
        w = max(len(r) for r in rows)
        rows = [r.ljust(w, '.') for r in rows]
        rows += ['.' * w] * (height - len(rows))
        out[ch] = rows
    return out


# ------------------------------------------------------------------ MEDIUM (cap 7, desc 2)

MEDIUM_SRC = r'''
A
.###.
#...#
#...#
#####
#...#
#...#
#...#

B
####.
#...#
#...#
####.
#...#
#...#
####.

C
.###.
#...#
#....
#....
#....
#...#
.###.

D
####.
#...#
#...#
#...#
#...#
#...#
####.

E
####
#...
#...
###.
#...
#...
####

F
####
#...
#...
###.
#...
#...
#...

G
.###.
#...#
#....
#.###
#...#
#...#
.####

H
#...#
#...#
#...#
#####
#...#
#...#
#...#

I
###
.#.
.#.
.#.
.#.
.#.
###

J
..###
...#.
...#.
...#.
...#.
#..#.
.##..

K
#...#
#..#.
#.#..
##...
#.#..
#..#.
#...#

L
#...
#...
#...
#...
#...
#...
####

M
#...#
##.##
#.#.#
#.#.#
#...#
#...#
#...#

N
#...#
##..#
#.#.#
#..##
#...#
#...#
#...#

O
.###.
#...#
#...#
#...#
#...#
#...#
.###.

P
####.
#...#
#...#
####.
#....
#....
#....

Q
.###.
#...#
#...#
#...#
#.#.#
#..#.
.##.#

R
####.
#...#
#...#
####.
#.#..
#..#.
#...#

S
.###.
#...#
#....
.###.
....#
#...#
.###.

T
#####
..#..
..#..
..#..
..#..
..#..
..#..

U
#...#
#...#
#...#
#...#
#...#
#...#
.###.

V
#...#
#...#
#...#
#...#
#...#
.#.#.
..#..

W
#...#
#...#
#...#
#.#.#
#.#.#
#.#.#
.#.#.

X
#...#
#...#
.#.#.
..#..
.#.#.
#...#
#...#

Y
#...#
#...#
.#.#.
..#..
..#..
..#..
..#..

Z
#####
....#
...#.
..#..
.#...
#....
#####

0
.###.
#...#
#..##
#.#.#
##..#
#...#
.###.

1
.#.
##.
.#.
.#.
.#.
.#.
###

2
.###.
#...#
....#
...#.
..#..
.#...
#####

3
####.
....#
....#
.###.
....#
....#
####.

4
...#.
..##.
.#.#.
#..#.
#####
...#.
...#.

5
#####
#....
####.
....#
....#
#...#
.###.

6
.###.
#....
#....
####.
#...#
#...#
.###.

7
#####
....#
...#.
..#..
..#..
..#..
..#..

8
.###.
#...#
#...#
.###.
#...#
#...#
.###.

9
.###.
#...#
#...#
.####
....#
....#
.###.

a
....
....
.##.
...#
.###
#..#
.###

b
#...
#...
###.
#..#
#..#
#..#
###.

c
...
...
.##
#..
#..
#..
.##

d
...#
...#
.###
#..#
#..#
#..#
.###

e
....
....
.##.
#..#
####
#...
.###

f
..#
.#.
###
.#.
.#.
.#.
.#.

g
....
....
.###
#..#
#..#
#..#
.###
...#
.##.

h
#...
#...
###.
#..#
#..#
#..#
#..#

i
#
.
#
#
#
#
#

j
..#
...
..#
..#
..#
..#
..#
..#
##.

k
#...
#...
#..#
#.#.
##..
#.#.
#..#

l
#
#
#
#
#
#
#

m
.....
.....
####.
#.#.#
#.#.#
#.#.#
#.#.#

n
....
....
###.
#..#
#..#
#..#
#..#

o
....
....
.##.
#..#
#..#
#..#
.##.

p
....
....
###.
#..#
#..#
#..#
###.
#...
#...

q
....
....
.###
#..#
#..#
#..#
.###
...#
...#

r
...
...
#.#
##.
#..
#..
#..

s
....
....
.###
#...
.##.
...#
###.

t
.#.
.#.
###
.#.
.#.
.#.
..#

u
....
....
#..#
#..#
#..#
#..#
.###

v
.....
.....
#...#
#...#
#...#
.#.#.
..#..

w
.....
.....
#...#
#...#
#.#.#
#.#.#
.#.#.

x
....
....
#..#
#..#
.##.
#..#
#..#

y
....
....
#..#
#..#
#..#
#..#
.###
...#
.##.

z
....
....
####
...#
.##.
#...
####

.
.
.
.
.
.
.
#

,
..
..
..
..
..
..
.#
#.

!
#
#
#
#
#
.
#

?
.###.
#...#
....#
...#.
..#..
.....
..#..

'
#
#
.

"
#.#
#.#
...

-
...
...
...
###

:
.
.
#
.
.
.
#

;
..
..
.#
..
..
..
.#
#.

/
....#
...#.
...#.
..#..
.#...
.#...
#....

(
.#
#.
#.
#.
#.
#.
.#

)
#.
.#
.#
.#
.#
.#
#.

&
.##..
#..#.
#.#..
.#...
#.#.#
#..#.
.##.#

+
.....
..#..
..#..
#####
..#..
..#..

%
##..#
##.#.
...#.
..#..
.#...
.#.##
#..##

#
.#.#.
.#.#.
#####
.#.#.
#####
.#.#.
.#.#.

=
....
....
####
....
####

*
.....
#.#.#
.###.
#.#.#

~
.....
.....
.#..#
#.##.

<
...#
..#.
.#..
#...
.#..
..#.
...#

>
#...
.#..
..#.
...#
..#.
.#..
#...

[
##
#.
#.
#.
#.
#.
##

]
##
.#
.#
.#
.#
.#
##

_
....
....
....
....
....
....
####

$
..#..
.####
#.#..
.###.
..#.#
####.
..#..

@
.###.
#...#
#.###
#.#.#
#.###
#....
.###.
'''

# ------------------------------------------------------------------ TINY (3x5 capitals)

TINY_SRC = r'''
A
.#.
#.#
###
#.#
#.#

B
##.
#.#
##.
#.#
##.

C
.##
#..
#..
#..
.##

D
##.
#.#
#.#
#.#
##.

E
###
#..
##.
#..
###

F
###
#..
##.
#..
#..

G
.##
#..
#.#
#.#
.##

H
#.#
#.#
###
#.#
#.#

I
###
.#.
.#.
.#.
###

J
..#
..#
..#
#.#
.#.

K
#.#
#.#
##.
#.#
#.#

L
#..
#..
#..
#..
###

M
#...#
##.##
#.#.#
#...#
#...#

N
#..#
##.#
#.##
#..#
#..#

O
.#.
#.#
#.#
#.#
.#.

P
##.
#.#
##.
#..
#..

Q
.#.
#.#
#.#
##.
.##

R
##.
#.#
##.
#.#
#.#

S
.##
#..
.#.
..#
##.

T
###
.#.
.#.
.#.
.#.

U
#.#
#.#
#.#
#.#
###

V
#.#
#.#
#.#
#.#
.#.

W
#...#
#...#
#.#.#
##.##
#...#

X
#.#
#.#
.#.
#.#
#.#

Y
#.#
#.#
.#.
.#.
.#.

Z
###
..#
.#.
#..
###

0
###
#.#
#.#
#.#
###

1
.#.
##.
.#.
.#.
###

2
##.
..#
.#.
#..
###

3
##.
..#
.#.
..#
##.

4
#.#
#.#
###
..#
..#

5
###
#..
##.
..#
##.

6
.##
#..
###
#.#
###

7
###
..#
.#.
.#.
.#.

8
###
#.#
###
#.#
###

9
###
#.#
###
..#
##.

.
.
.
.
.
#

,
.
.
.
#
#

!
#
#
#
.
#

?
##.
..#
.#.
...
.#.

'
#
#
.

"
#.#
#.#
...

-
...
...
###

:
.
#
.
#
.

/
..#
..#
.#.
#..
#..

(
.#
#.
#.
#.
.#

)
#.
.#
.#
.#
#.

&
.#.
#.#
.#.
#.#
.##

+
...
.#.
###
.#.

%
#.#
..#
.#.
#..
#.#
'''

# ------------------------------------------------------------------ LARGE punctuation (cap 11)

LARGE_PUNCT_SRC = r'''
.
.
.
.
.
.
.
.
.
.
.
#

,
.
.
.
.
.
.
.
.
.
.
#
#

!
#
#
#
#
#
#
#
#
.
.
#

?
.###.
#...#
....#
....#
...#.
..#..
..#..
..#..
.....
.....
..#..

'
#
#
#

"
#.#
#.#
#.#

-
....
....
....
....
....
####

:
.
.
.
#
.
.
.
.
.
.
#

;
.
.
.
#
.
.
.
.
.
.
#
#

/
.....#
.....#
....#.
....#.
...#..
...#..
..#...
.#....
.#....
#.....
#.....

(
..#
.#.
#..
#..
#..
#..
#..
#..
#..
.#.
..#

)
#..
.#.
..#
..#
..#
..#
..#
..#
..#
.#.
#..

&
.##...
#..#..
#..#..
.##...
.#....
#.#..#
#..#.#
#...#.
#...#.
#..#.#
.##...#

+
.....
.....
.....
..#..
..#..
#####
..#..
..#..

%
.#....#
#.#..#.
.#...#.
....#..
...#...
...#...
..#....
.#..#..
.#.#.#.
#...#..
'''


def _from_staff(staff):
    """The game's own glyphs: 16x16 1bpp; capitals occupy rows 3..13, descenders reach row 14."""
    out = {}
    for addr, chars in STAFF_GLYPHS:
        off = addr - OVERLAY_BASE
        for k, ch in enumerate(chars):
            g = staff[off + 32 * k: off + 32 * k + 32]
            rows = [g[2 * y] << 8 | g[2 * y + 1] for y in range(3, 15)]
            cols = [x for x in range(16) if any(r & (0x8000 >> x) for r in rows)]
            x0, x1 = min(cols), max(cols)
            out[ch] = [''.join('#' if r & (0x8000 >> x) else '.' for x in range(x0, x1 + 1)) for r in rows]
    return out


def large(staff_bytes):
    f = Font('large', height=12, baseline=10, space=4, line_gap=3)
    f.glyphs.update(_parse(LARGE_PUNCT_SRC, 12))
    f.glyphs.update(_from_staff(staff_bytes))
    for ch, rows in MEDIUM.glyphs.items():  # anything still missing: scale the medium glyph up
        if ch not in f.glyphs:
            f.glyphs[ch] = _scale_rows(rows[:7], 11) + ['.' * len(rows[0])]
    return f


def _scale_rows(rows, h):
    return [rows[min(len(rows) - 1, int(y * len(rows) / h))] for y in range(h)]


MEDIUM = Font('medium', height=9, baseline=6, space=3, line_gap=2)
MEDIUM.glyphs.update(_parse(MEDIUM_SRC, 9))
TINY = Font('tiny', height=5, baseline=4, space=3, line_gap=2, upper_only=True)
TINY.glyphs.update(_parse(TINY_SRC, 5))


def bold(font):
    """Faux bold: every glyph OR-ed with itself shifted one pixel right (glyphs get 1 px wider)."""
    b = Font(font.name + '-bold', font.height, font.baseline, font.space + 1, font.spacing, font.line_gap,
             font.upper_only)
    for ch, rows in font.glyphs.items():
        b.glyphs[ch] = [''.join('#' if (r + '.')[i] == '#' or ('.' + r)[i] == '#' else '.'
                                for i in range(len(r) + 1)) for r in rows]
    return b


def fontset(staff_bytes):
    """Fonts in order of preference: biggest/boldest first."""
    lg = large(staff_bytes)
    return [bold(lg), lg, bold(MEDIUM), MEDIUM, TINY]
