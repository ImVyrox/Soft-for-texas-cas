"""Images stored in documents.

TI documents store pictures as deflated ``.BMP`` entries. The one examined
(``potenciales.tns``, 2026-11-14) is a 16-bit BI_BITFIELDS bitmap whose
colour masks are written shifted left by 16 bits (0xF8000000, 0x07E00000,
0x001F0000 instead of RGB565's 0xF800, 0x07E0, 0x001F); Qt refuses it.
Decoded as RGB565, bottom-up, it renders a coherent drawing (checked
visually). Other layouts are left to Qt.
"""

from __future__ import annotations

import struct

RGB565 = (0xF800, 0x07E0, 0x001F)


class UnsupportedImage(ValueError):
    pass


def decode_bmp16(data: bytes) -> tuple[int, int, bytes]:
    """(width, height, RGB888 rows top-down) for 16-bit RGB565 BMPs, incl. TI's shifted-mask variant."""
    if len(data) < 54 or data[:2] != b"BM":
        raise UnsupportedImage("no es un BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    hsize, width, height, _planes, bpp, comp = struct.unpack_from("<IiiHHI", data, 14)
    if bpp != 16 or comp != 3 or width <= 0 or height == 0:
        raise UnsupportedImage(f"BMP de {bpp} bits, compresión {comp}: no soportado aquí")
    masks = struct.unpack_from("<III", data, 14 + 40) if hsize >= 52 else struct.unpack_from("<III", data, 14 + hsize)
    if masks != RGB565 and tuple(m >> 16 for m in masks) != RGB565:
        raise UnsupportedImage(f"máscaras de color no reconocidas: {[hex(m) for m in masks]}")
    rows = abs(height)
    stride = ((width * 16 + 31) // 32) * 4
    if offset + stride * rows > len(data):
        raise UnsupportedImage("datos de imagen truncados")
    out = bytearray()
    order = range(rows - 1, -1, -1) if height > 0 else range(rows)
    for y in order:
        row = data[offset + y * stride: offset + y * stride + width * 2]
        for (v,) in struct.iter_unpack("<H", row):
            r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
            out += bytes(((r * 255) // 31, (g * 255) // 63, (b * 255) // 31))
    return width, rows, bytes(out)
