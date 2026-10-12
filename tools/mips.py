#!/usr/bin/env python3
"""Tiny MIPS disassembly helper for the main EXE and overlays.

  mips.py dis   <file> <addr> [count]     disassemble at a RAM address
  mips.py imm   <file> <hex-imm>...       find instructions using an immediate
  mips.py xref  <file> <addr>             find lui/addiu|ori|lw pairs building an address, and jal targets
"""
import struct
import sys

from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN

from text import OVERLAY_BASE


def load(path):
    d = open(path, 'rb').read()
    if d[:8] == b'PS-X EXE':
        addr = struct.unpack_from('<I', d, 0x18)[0]
        return addr, d[0x800:]
    return OVERLAY_BASE, d


def md():
    m = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 + CS_MODE_LITTLE_ENDIAN)
    m.detail = False
    return m


def dis(base, code, addr, count):
    m = md()
    off = addr - base
    for i in m.disasm(code[off:off + count * 4], addr):
        print(f'{i.address:08x}: {i.bytes.hex()}  {i.mnemonic:8s} {i.op_str}')


def disasm_all(code, base):
    """Disassemble every word, skipping ones capstone can't decode (data)."""
    m = md()
    out = []
    for off in range(0, len(code) - 3, 4):
        out.extend(m.disasm(code[off:off + 4], base + off))
    return out


def words(base, code):
    for off in range(0, len(code) - 3, 4):
        yield base + off, struct.unpack_from('<I', code, off)[0]


def main(a):
    base, code = load(a[1])
    if a[0] == 'dis':
        dis(base, code, int(a[2], 16), int(a[3]) if len(a) > 3 else 40)
    elif a[0] == 'imm':
        targets = {int(x, 16) for x in a[2:]}
        for addr, w in words(base, code):
            op = w >> 26
            if op in (0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f, 0x23, 0x2b, 0x21, 0x25, 0x20, 0x24, 0x29, 0x28) and (w & 0xffff) in targets:
                dis(base, code, addr, 1)
    elif a[0] == 'xref':
        t = int(a[2], 16)
        hi = (t + 0x8000) >> 16
        lo = t & 0xffff
        for addr, w in words(base, code):
            if w >> 26 == 0x03 and ((w & 0x3ffffff) << 2) | (addr & 0xf0000000) == t:
                print('jal from', hex(addr))
            if (w & 0xffff) == lo and w >> 26 in (0x09, 0x0d, 0x23, 0x21, 0x25, 0x20, 0x24, 0x2b, 0x29, 0x28):
                for back in range(1, 12):  # look back for the matching lui
                    pa = addr - back * 4
                    if pa < base:
                        break
                    pw = struct.unpack_from('<I', code, pa - base)[0]
                    if pw >> 26 == 0x0f and (pw & 0xffff) == hi:
                        print('ref at', hex(addr))
                        break


if __name__ == '__main__':
    main(sys.argv[1:])
