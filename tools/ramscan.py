#!/usr/bin/env python3
"""Report which RAM addresses an overlay touches beyond the end of its file (its BSS),
so we know how much of the overlay region (0x8005c1c8 .. heap at 0x800a7b60) is free.

  ramscan.py <overlay.bin>...
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mips import disasm_all  # noqa: E402
from text import HEAP_START, OVERLAY_BASE  # noqa: E402

MEM_OPS = {'lw', 'sw', 'lh', 'lhu', 'sh', 'lb', 'lbu', 'sb', 'lwl', 'lwr', 'swl', 'swr'}


def num(s):
    return 0 if s == '' else int(s, 0)


def refs_beyond(path):
    d = Path(path).read_bytes()
    end = OVERLAY_BASE + len(d)
    ins = disasm_all(d, OVERLAY_BASE)
    out = set()
    for i, x in enumerate(ins):
        if x.mnemonic != 'lui':
            continue
        rt, hi = x.op_str.split(', ')
        hi = int(hi, 16)
        for y in ins[i + 1:i + 12]:
            ops = y.op_str.replace('(', ', ').replace(')', '').split(', ')
            if y.mnemonic in ('addiu', 'ori') and len(ops) == 3 and ops[1] == rt:
                lo = num(ops[2])
                out.add(((hi << 16) + (lo - 0x10000 if y.mnemonic == 'addiu' and lo >= 0x8000 else lo)) & 0xffffffff)
                if ops[0] == rt:
                    break
                continue
            if y.mnemonic in MEM_OPS and len(ops) == 3 and ops[2] == rt:
                out.add(((hi << 16) + num(ops[1])) & 0xffffffff)
                if y.mnemonic.startswith('l') and ops[0] == rt:
                    break
                continue
            if ops and ops[0] == rt and y.mnemonic not in MEM_OPS - {'lw', 'lh', 'lhu', 'lb', 'lbu', 'lwl', 'lwr'}:
                break  # register redefined
    return end, sorted(a for a in out if end <= a < HEAP_START)


if __name__ == '__main__':
    for p in sys.argv[1:]:
        end, beyond = refs_beyond(p)
        top = max(beyond) if beyond else None
        print(f'{Path(p).name}: file ends {end:#x}, highest BSS ref {top:#x} ' if top else
              f'{Path(p).name}: file ends {end:#x}, no BSS refs ', end='')
        free_from = ((top or end) + 0x1000) & ~0xfff  # leave room for the last BSS object
        print(f'-> assume free from {free_from:#x}: {HEAP_START - free_from} bytes')
