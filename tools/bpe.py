#!/usr/bin/env python3
"""Byte-pair-encoding codec used by the game (decoder at 0x80013c44 in SLPS_018.49).

CMP1 container: "CMP1" + u32 decompressed size + BPE stream.
BPE stream: repeated blocks of
    pair table   (runs: count byte; >=0x80 skips (count-0x7f) codes, else count+1 entries
                  of left[,right] - right omitted when left == code)
    u16 BE       number of data bytes in this block
    data         bytes, each expanded recursively through the pair table
until the requested number of output bytes has been produced.

  bpe.py d <in> <out>        decompress a CMP1 file
  bpe.py c <in> <out>        compress to a CMP1 file
"""
import struct
import sys
from collections import Counter

BLOCK_SIZE = 5000  # Gage's defaults, which match the game's original data
MAX_CHARS = 200    # end a block early once this many distinct byte values are in it
THRESHOLD = 3      # minimum pair frequency worth a code


def decompress(src, out_size, pos=0):
    out = bytearray()
    while len(out) < out_size:
        left = list(range(256))
        right = [0] * 256
        c = 0
        while True:
            count = src[pos]; pos += 1
            if count >= 0x80:
                c += count - 0x7f
                count = 0
                if c == 256:
                    break
            for _ in range(count + 1):
                b = src[pos]; pos += 1
                left[c] = b
                if b != c:
                    right[c] = src[pos]; pos += 1
                c += 1
            if c == 256:
                break
        size = (src[pos] << 8) | src[pos + 1]
        pos += 2
        stack = []
        for _ in range(size):
            stack.append(src[pos]); pos += 1
            while stack:
                c = stack.pop()
                if left[c] == c:
                    out.append(c)
                else:
                    stack.append(right[c])
                    stack.append(left[c])
    return bytes(out[:out_size]), pos


def _compress_block(buf):
    """Philip Gage's BPE: replace the most frequent pair with an unused code, highest code first."""
    buf = bytes(buf)
    left = list(range(256))
    right = [0] * 256
    used = set(buf)
    code = 256
    while True:
        code -= 1
        while code >= 0 and (code in used or left[code] != code):
            code -= 1
        if code < 0:
            break
        counts = Counter(zip(buf, buf[1:]))
        if not counts:
            break
        (a, b), n = counts.most_common(1)[0]
        if n < THRESHOLD:
            break
        buf = buf.replace(bytes((a, b)), bytes((code,)))
        left[code], right[code] = a, b
        used.add(code)
    # encode pair table; a skip byte (>=0x80) is always followed by exactly one entry
    tab = bytearray()
    c = 0
    while c < 256:
        if left[c] == c:
            n = 0
            while c < 256 and left[c] == c and n < 128:
                n += 1
                c += 1
            tab.append(0x7f + n)
            if c == 256:
                break
            cnt = 0
        else:
            n = 1
            while c + n < 256 and n < 128 and (left[c + n] != c + n or
                                               (c + n + 1 < 256 and left[c + n + 1] != c + n + 1)):
                n += 1
            tab.append(n - 1)
            cnt = n - 1
        for _ in range(cnt + 1):
            tab.append(left[c])
            if left[c] != c:
                tab.append(right[c])
            c += 1
    assert len(buf) < 0x10000
    return bytes(tab) + struct.pack('>H', len(buf)) + bytes(buf)


def compress(data, block_size=BLOCK_SIZE, max_chars=MAX_CHARS):
    out = bytearray()
    i = 0
    while i < len(data):
        seen = set()
        j = i
        while j < len(data) and j - i < block_size and len(seen) < max_chars:
            seen.add(data[j])
            j += 1
        out += _compress_block(data[i:j])
        i = j
    return bytes(out)


def unpack_cmp1(blob):
    assert blob[:4] == b'CMP1', 'not CMP1'
    size = struct.unpack_from('<I', blob, 4)[0]
    return decompress(blob, size, 8)[0]


def pack_cmp1(data, limit=None):
    """Compress to CMP1. With a size limit, retry other block settings until it fits (or keep the smallest)."""
    best = None
    for bs, mc in ((BLOCK_SIZE, MAX_CHARS), (4000, 200), (6000, 200), (5000, 220), (3000, 200), (8000, 230)):
        blob = b'CMP1' + struct.pack('<I', len(data)) + compress(data, bs, mc)
        if best is None or len(blob) < len(best):
            best = blob
        if limit is None or len(best) <= limit:
            break
    return best


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) != 3 or a[0] not in 'dc':
        print(__doc__); sys.exit(1)
    src = open(a[1], 'rb').read()
    res = unpack_cmp1(src) if a[0] == 'd' else pack_cmp1(src)
    open(a[2], 'wb').write(res)
    print(f'{len(src)} -> {len(res)} bytes')
