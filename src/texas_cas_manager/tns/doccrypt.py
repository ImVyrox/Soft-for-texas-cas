"""TI document encryption for entries stored with ZIP method ``0x0D``.

Layout of such an entry (from Luna, checked against real documents):

    40-byte header | encrypted( raw-deflate( TIXC XML-compressed data ) )

The cipher is a counter mode built on 3DES-ECB: block *i* of the keystream is
``3DES_encrypt(00 00 00 00 || LE32(ivec_base + (i mod 1024)))`` and is XORed
with the data. Encryption and decryption are the same operation.

Only the keys of Luna's fixed header (``TIEN_CRYPTED_HEADER``) are known.
Documents saved by the calculator or by TI's software use other headers whose
key derivation is not documented in the sources reviewed (see
docs/TNS-FORMAT.md); :func:`decrypt_entry` raises :class:`UnknownKeyError`
for them instead of guessing.
"""

from __future__ import annotations

import struct
import zlib
from functools import lru_cache

from Crypto.Cipher import DES3

from ._luna_data import DOCCRYPT_IVEC_BASE, DOCCRYPT_KEYS, TIEN_CRYPTED_HEADER

HEADER_SIZE = 40
_PERIOD = 1024  # counter wraps after 1024 blocks, so the keystream repeats every 8 KiB


class UnknownKeyError(ValueError):
    """The entry was encrypted with a header whose keys are unknown."""


@lru_cache(maxsize=4)
def _keystream(keys: tuple[bytes, bytes, bytes], ivec_base: int) -> bytes:
    cipher = DES3.new(b"".join(keys), DES3.MODE_ECB)
    blocks = b"".join(
        b"\0\0\0\0" + struct.pack("<I", (ivec_base + i) & 0xFFFFFFFF) for i in range(_PERIOD)
    )
    return cipher.encrypt(blocks)


def crypt(data: bytes, keys=DOCCRYPT_KEYS, ivec_base: int = DOCCRYPT_IVEC_BASE) -> bytes:
    """XOR ``data`` with the keystream (encrypts and decrypts)."""
    ks = _keystream(tuple(keys), ivec_base)
    reps = len(data) // len(ks) + 1
    stream = (ks * reps)[: len(data)]
    return (int.from_bytes(data, "little") ^ int.from_bytes(stream, "little")).to_bytes(len(data), "little")


def has_known_header(raw: bytes) -> bool:
    return raw[:HEADER_SIZE] == TIEN_CRYPTED_HEADER


def decrypt_entry(raw: bytes) -> bytes:
    """Return the XML-compressed (TIXC) data of an encrypted entry."""
    if len(raw) < HEADER_SIZE:
        raise ValueError("encrypted entry shorter than its header")
    if not has_known_header(raw):
        raise UnknownKeyError("entry encrypted with an unknown key (document not created by Luna or this program)")
    try:
        return zlib.decompress(crypt(raw[HEADER_SIZE:]), -15)
    except zlib.error as exc:
        raise ValueError(f"decrypted data is not valid deflate ({exc})") from exc


def encrypt_entry(tixc: bytes) -> bytes:
    """Build the raw data of an encrypted entry, exactly as Luna does."""
    comp = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15, 8, zlib.Z_DEFAULT_STRATEGY)
    deflated = comp.compress(tixc) + comp.flush()
    return TIEN_CRYPTED_HEADER + crypt(deflated)
