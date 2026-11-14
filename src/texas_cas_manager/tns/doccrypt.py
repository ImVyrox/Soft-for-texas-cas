"""Body encryption of TI-encrypted entries (ZIP method ``0x0D``).

Layout of such an entry (Luna, Rust TNS, and real documents)::

    40-byte TIEN0100 header | crypt( raw-deflate( TIXC stream ) )

``crypt`` is a counter mode on 3DES-ECB: keystream block *i* is
``3DES(00 00 00 00 || LE32(seed + (i mod 1024)))``, XORed with the data
(encrypting and decrypting are the same operation). Keys and seed come from
the entry's own header (:mod:`tien`): every document saved by TI has its own;
Luna and this program use Luna's fixed header.
"""

from __future__ import annotations

import struct
import zlib
from functools import lru_cache

from Crypto.Cipher import DES3

from . import tien
from ._luna_data import DOCCRYPT_IVEC_BASE, DOCCRYPT_KEYS, TIEN_CRYPTED_HEADER

HEADER_SIZE = tien.SIZE
_PERIOD = tien.BLOCK_SIZE


class ProtectedEntryError(ValueError):
    """The entry's header is not a TIEN0100 header: its content cannot be read."""


UnknownKeyError = ProtectedEntryError  # name used before Phase 3


@lru_cache(maxsize=16)
def _keystream(keys: tuple[bytes, bytes, bytes], seed: int) -> bytes:
    cipher = DES3.new(b"".join(keys), DES3.MODE_ECB)
    blocks = b"".join(b"\0\0\0\0" + struct.pack("<I", (seed + i) & 0xFFFFFFFF) for i in range(_PERIOD))
    return cipher.encrypt(blocks)


def crypt(data: bytes, keys=DOCCRYPT_KEYS, seed: int = DOCCRYPT_IVEC_BASE) -> bytes:
    """XOR ``data`` with the keystream (encrypts and decrypts)."""
    ks = _keystream(tuple(keys), seed)
    stream = (ks * (len(data) // len(ks) + 1))[: len(data)]
    return (int.from_bytes(data, "little") ^ int.from_bytes(stream, "little")).to_bytes(len(data), "little")


def read_header(raw: bytes) -> tien.TienHeader:
    try:
        return tien.parse(raw[:HEADER_SIZE])
    except tien.HeaderError as exc:
        raise ProtectedEntryError(str(exc)) from exc


def has_luna_header(raw: bytes) -> bool:
    return raw[:HEADER_SIZE] == TIEN_CRYPTED_HEADER


has_known_header = has_luna_header  # name used before Phase 3


def decrypt_entry(raw: bytes) -> bytes:
    """Return the TIXC stream of an encrypted entry."""
    header = read_header(raw)
    try:
        return zlib.decompress(crypt(raw[HEADER_SIZE:], header.keys, header.seed), -15)
    except zlib.error as exc:
        raise ValueError(f"decrypted data is not valid deflate ({exc})") from exc


def encrypt_entry(tixc: bytes, header: bytes = TIEN_CRYPTED_HEADER) -> bytes:
    """Raw entry data for ``tixc``, encrypted under ``header`` (default: Luna's, byte-identical to Luna)."""
    info = read_header(header)
    comp = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15, 8, zlib.Z_DEFAULT_STRATEGY)
    deflated = comp.compress(tixc) + comp.flush()
    return header[:HEADER_SIZE] + crypt(deflated, info.keys, info.seed)
