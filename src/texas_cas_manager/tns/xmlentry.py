"""Rewrite the XML of one TI-encrypted entry, keeping everything else.

Shared by script editing (lua.py) and note editing (notes.py). The new XML is
TIXC-encoded, deflated and encrypted under the entry's *own* TIEN header (same
keys and seed); the directory CRC/size keep the entry's original convention
(TI: of the XML; Luna: of the stored bytes). Verified on hardware on
2026-11-14 with an edited stopwatch.tns (docs/HARDWARE-NATIVE-TESTS.md).
"""

from __future__ import annotations

import zlib
from dataclasses import replace

from . import doccrypt, tixc, xmldoc
from .container import TnsDocument


def rewrite(doc: TnsDocument, name: str, old_xml: bytes, new_xml: bytes) -> TnsDocument:
    """Copy of ``doc`` whose entry ``name`` (decoded as ``old_xml``) now holds ``new_xml``."""
    entry = doc.entry(name)
    convention = xmldoc.metadata_convention(entry, old_xml)
    raw = doccrypt.encrypt_entry(tixc.encode(new_xml), header=entry.raw[:doccrypt.HEADER_SIZE])
    if convention == xmldoc.META_LEGACY:
        crc, size = zlib.crc32(raw), len(raw)
    else:
        crc, size = zlib.crc32(new_xml), len(new_xml)
    new = TnsDocument(version=doc.version, entries=list(doc.entries),
                      end_magic=doc.end_magic, archive_comment=doc.archive_comment)
    new.replace_entry(replace(entry, raw=raw, crc32=crc, uncompressed_size=size))
    return new
