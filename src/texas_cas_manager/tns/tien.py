# The contents of this file are subject to the Mozilla Public License
# Version 1.1 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Based on crates/tns-core/src/method13.rs from Rust TNS
# (https://github.com/dev1837457/rust-tns, commit 48a6f5e, MPL 1.1,
# "TNS modernization contributors", 2026): HEADER_KEY and the packed-key
# layout come from there. Ported for Texas CAS Manager (MIT elsewhere).
"""TIEN0100 header of TI-encrypted (ZIP method 0x0D) entries.

Each encrypted entry starts with a 40-byte header encrypted with 3DES-ECB
under a fixed key. Decrypted it holds::

    0  "TIEN0100"
    8  LE32 block size (0x400: the counter wraps every 1024 blocks)
    12 LE32 counter seed
    16 21 bytes: the three 3DES body keys, 7 bytes each without parity bits
    37 3 reserved zero bytes

The body is the counter-mode keystream of :mod:`doccrypt` with those keys and
seed. Verified on 2026-11-13: Luna's fixed header decrypts to exactly Luna's
hard-coded keys and seed 0x6FE21307, and the entries of documents saved by a
CX CAS (OS 4.5 / TI-Nspire software 5.0 and 6.3) decrypt and inflate to TIXC
streams whose decoded XML matches the CRC-32 stored by TI.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from Crypto.Cipher import DES3

MAGIC = b"TIEN0100"
SIZE = 40
BLOCK_SIZE = 0x400

HEADER_KEY = bytes([
    0x79, 0xC4, 0xE0, 0xF4, 0x5E, 0xEF, 0x7A, 0x5B, 0x70, 0x13, 0x7A, 0x57,
    0xC2, 0xFD, 0x3D, 0x2C, 0xC2, 0x70, 0x7C, 0xC1, 0xAD, 0x2F, 0x15, 0x75,
])


class HeaderError(ValueError):
    """The 40 bytes are not a TIEN0100 header this module understands."""


@dataclass(frozen=True)
class TienHeader:
    block_size: int
    seed: int
    key_material: bytes  # 21 packed bytes, as stored

    @property
    def keys(self) -> tuple[bytes, bytes, bytes]:
        k = self.key_material
        return tuple(_unpack_key(k[i * 7:i * 7 + 7]) for i in range(3))  # type: ignore[return-value]


def _odd_parity(b: int) -> int:
    b &= 0xFE
    return b | (1 ^ (bin(b).count("1") & 1))


def _unpack_key(b: bytes) -> bytes:
    raw = (
        b[0] & 0xFE,
        ((b[1] >> 1) & 0x7E) | (b[0] << 7),
        ((b[2] >> 2) & 0x3E) | (b[1] << 6),
        ((b[3] >> 3) & 0x1E) | (b[2] << 5),
        ((b[4] >> 4) & 0x0E) | (b[3] << 4),
        ((b[5] >> 5) & 0x06) | (b[4] << 3),
        ((b[6] >> 6) & 0x02) | (b[5] << 2),
        b[6] << 1,
    )
    return bytes(_odd_parity(x & 0xFF) for x in raw)


def parse(header: bytes) -> TienHeader:
    if len(header) < SIZE:
        raise HeaderError("entry shorter than the 40-byte TIEN0100 header")
    plain = DES3.new(HEADER_KEY, DES3.MODE_ECB).decrypt(header[:SIZE])
    if plain[:8] != MAGIC:
        raise HeaderError("header does not decrypt to TIEN0100 (unknown protection)")
    block_size, seed = struct.unpack_from("<II", plain, 8)
    if block_size != BLOCK_SIZE:
        raise HeaderError(f"unsupported block size 0x{block_size:x}")
    if any(plain[37:40]):
        raise HeaderError("non-zero reserved bytes in TIEN0100 header")
    return TienHeader(block_size, seed, plain[16:37])


def build(header: TienHeader) -> bytes:
    plain = MAGIC + struct.pack("<II", header.block_size, header.seed) + header.key_material + bytes(3)
    return DES3.new(HEADER_KEY, DES3.MODE_ECB).encrypt(plain)
