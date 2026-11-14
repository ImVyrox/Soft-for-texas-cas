"""Reader and writer for the TI-Nspire ``.tns`` container.

A ``.tns`` document is a ZIP archive with three TI changes (verified against
Luna's modified minizip and against documents saved by a CX CAS on OS 4.5):

* the first local file header starts with ``*TIMLP`` + 4 ASCII hex digits
  (document version, e.g. ``*TIMLP0601``) instead of ``PK\\x03\\x04``;
  the following local headers use the normal ``PK\\x03\\x04``;
* the end of central directory record starts with ``TIPD`` instead of
  ``PK\\x05\\x06``;
* XML entries use the non-standard compression method ``0x0D``
  (TI encrypted, see :mod:`texas_cas_manager.tns.doccrypt`).

Central directory offsets are absolute file offsets. The writer serialises
every header field it parsed, so ``write(parse(data)) == data`` for documents
without trailing data; unknown fields and entries are kept untouched.
"""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass, field, replace

TI_MAGIC_RE = re.compile(rb"\*TIMLP[0-9A-Fa-f]{4}")
STD_LOCAL_MAGIC = b"PK\x03\x04"
CENTRAL_MAGIC = b"PK\x01\x02"
TI_END_MAGIC = b"TIPD"
STD_END_MAGIC = b"PK\x05\x06"

METHOD_STORED = 0
METHOD_DEFLATED = 8
METHOD_TI_ENCRYPTED = 0x0D

_LOCAL = struct.Struct("<HHHHHIIIHH")  # after the magic
_CENTRAL = struct.Struct("<HHHHHHIIIHHHHHII")  # after the magic
_END = struct.Struct("<HHHHIIH")  # after the magic


class TnsFormatError(ValueError):
    """The data is not a TNS container this module understands."""


@dataclass(frozen=True)
class TnsEntry:
    """One file inside the container, with its raw (still compressed) data."""

    name: str
    method: int
    raw: bytes
    crc32: int
    uncompressed_size: int
    flags: int = 0
    version_needed: int = 20
    version_made_by: int = 20
    mod_time: int = 0
    mod_date: int = 0x20
    internal_attr: int = 0
    external_attr: int = 0
    local_extra: bytes = b""
    central_extra: bytes = b""
    comment: bytes = b""
    name_bytes: bytes = b""

    @property
    def is_encrypted(self) -> bool:
        return self.method == METHOD_TI_ENCRYPTED

    def payload(self) -> bytes:
        """Decompressed content for stored/deflated entries.

        Raises :class:`TnsFormatError` for TI-encrypted entries (use
        :mod:`doccrypt`) and for unknown methods.
        """
        if self.method == METHOD_STORED:
            data = self.raw
        elif self.method == METHOD_DEFLATED:
            try:
                data = zlib.decompress(self.raw, -15)
            except zlib.error as exc:
                raise TnsFormatError(f"{self.name}: corrupt deflate data ({exc})") from exc
        else:
            raise TnsFormatError(f"{self.name}: compression method 0x{self.method:02X} is not plain ZIP")
        if zlib.crc32(data) != self.crc32:
            raise TnsFormatError(f"{self.name}: CRC mismatch")
        return data

    def with_payload(self, data: bytes) -> "TnsEntry":
        """Copy of a stored/deflated entry with new content (same method)."""
        if self.method == METHOD_STORED:
            raw = data
        elif self.method == METHOD_DEFLATED:
            comp = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
            raw = comp.compress(data) + comp.flush()
        else:
            raise TnsFormatError(f"{self.name}: cannot re-encode method 0x{self.method:02X}")
        return replace(self, raw=raw, crc32=zlib.crc32(data), uncompressed_size=len(data))


@dataclass
class TnsDocument:
    """Parsed container. ``version`` is the 4 hex digits after ``*TIMLP``."""

    version: str
    entries: list[TnsEntry] = field(default_factory=list)
    end_magic: bytes = TI_END_MAGIC
    archive_comment: bytes = b""

    def entry(self, name: str) -> TnsEntry:
        for e in self.entries:
            if e.name == name:
                return e
        raise KeyError(name)

    def names(self) -> list[str]:
        return [e.name for e in self.entries]

    def replace_entry(self, new: TnsEntry) -> None:
        for i, e in enumerate(self.entries):
            if e.name == new.name:
                self.entries[i] = new
                return
        raise KeyError(new.name)


def is_tns(data: bytes) -> bool:
    return TI_MAGIC_RE.match(data[:10]) is not None


def parse(data: bytes) -> TnsDocument:
    """Parse a ``.tns`` file. Raises :class:`TnsFormatError` on bad input."""
    m = TI_MAGIC_RE.match(data[:10])
    if not m:
        raise TnsFormatError("missing *TIMLP header: not a TI-Nspire document")
    version = data[6:10].decode("ascii")

    end = _find_end(data)
    end_magic = data[end:end + 4]
    disk, cd_disk, n_disk, n_total, cd_size, cd_offset, comment_len = _END.unpack_from(data, end + 4)
    if disk or cd_disk or n_disk != n_total:
        raise TnsFormatError("multi-disk archives are not supported")
    archive_comment = data[end + 22:end + 22 + comment_len]
    if cd_offset + cd_size > end:
        raise TnsFormatError("central directory outside the file")

    entries = []
    pos = cd_offset
    for _ in range(n_total):
        if data[pos:pos + 4] != CENTRAL_MAGIC:
            raise TnsFormatError(f"bad central directory record at offset {pos}")
        (made_by, needed, flags, method, mtime, mdate, crc, csize, usize,
         nlen, xlen, clen, _disk, iattr, eattr, local_off) = _CENTRAL.unpack_from(data, pos + 4)
        p = pos + 46
        name_bytes = data[p:p + nlen]
        central_extra = data[p + nlen:p + nlen + xlen]
        comment = data[p + nlen + xlen:p + nlen + xlen + clen]
        pos = p + nlen + xlen + clen

        magic_len = 10 if local_off == 0 else 4
        lmagic = data[local_off:local_off + magic_len]
        if (local_off == 0 and not TI_MAGIC_RE.match(lmagic)) or (local_off and lmagic != STD_LOCAL_MAGIC):
            raise TnsFormatError(f"bad local header for {name_bytes!r}")
        lfields = _LOCAL.unpack_from(data, local_off + magic_len)
        l_nlen, l_xlen = lfields[8], lfields[9]
        start = local_off + magic_len + _LOCAL.size + l_nlen
        local_extra = data[start:start + l_xlen]
        start += l_xlen
        if flags & 0x08:
            raise TnsFormatError("data descriptors are not supported")
        raw = data[start:start + csize]
        if len(raw) != csize:
            raise TnsFormatError(f"truncated data for {name_bytes!r}")

        entries.append(TnsEntry(
            name=name_bytes.decode("utf-8" if flags & 0x800 else "cp437"),
            method=method, raw=raw, crc32=crc, uncompressed_size=usize, flags=flags,
            version_needed=needed, version_made_by=made_by, mod_time=mtime, mod_date=mdate,
            internal_attr=iattr, external_attr=eattr, local_extra=local_extra,
            central_extra=central_extra, comment=comment, name_bytes=name_bytes,
        ))
    return TnsDocument(version=version, entries=entries, end_magic=end_magic,
                       archive_comment=archive_comment)


def _find_end(data: bytes) -> int:
    lo = max(0, len(data) - 22 - 0xFFFF)
    for magic in (TI_END_MAGIC, STD_END_MAGIC):
        i = data.rfind(magic, lo)
        while i >= 0:
            if i + 22 <= len(data):
                comment_len = struct.unpack_from("<H", data, i + 20)[0]
                if i + 22 + comment_len == len(data):
                    return i
            i = data.rfind(magic, lo, i)
    raise TnsFormatError("end of central directory not found")


def write(doc: TnsDocument) -> bytes:
    """Serialise a document. Entry order is kept; the first entry gets the TI header."""
    if not re.fullmatch(r"[0-9A-Fa-f]{4}", doc.version):
        raise TnsFormatError(f"invalid document version {doc.version!r}")
    if not doc.entries:
        raise TnsFormatError("a document needs at least one entry")
    out = bytearray()
    central = bytearray()
    for i, e in enumerate(doc.entries):
        name = e.name_bytes or e.name.encode("utf-8" if e.flags & 0x800 else "cp437")
        offset = len(out)
        out += (b"*TIMLP" + doc.version.encode("ascii")) if i == 0 else STD_LOCAL_MAGIC
        out += _LOCAL.pack(e.version_needed, e.flags, e.method, e.mod_time, e.mod_date,
                           e.crc32, len(e.raw), e.uncompressed_size, len(name), len(e.local_extra))
        out += name + e.local_extra + e.raw
        central += CENTRAL_MAGIC + _CENTRAL.pack(
            e.version_made_by, e.version_needed, e.flags, e.method, e.mod_time, e.mod_date,
            e.crc32, len(e.raw), e.uncompressed_size, len(name), len(e.central_extra),
            len(e.comment), 0, e.internal_attr, e.external_attr, offset)
        central += name + e.central_extra + e.comment
    cd_offset = len(out)
    out += central
    out += doc.end_magic + _END.pack(0, 0, len(doc.entries), len(doc.entries), len(central),
                                     cd_offset, len(doc.archive_comment)) + doc.archive_comment
    return bytes(out)
