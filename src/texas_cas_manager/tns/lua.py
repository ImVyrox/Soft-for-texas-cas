"""Lua documents: build them like Luna does, read and replace their script.

A Lua document is ``Document.xml`` + ``Problem1.xml`` where Problem1 holds one
``TI.ScriptApp`` widget whose ``sc:script`` element contains the Lua source
in CDATA. Luna splits any ``]]>`` in the source into two CDATA sections; the
reader undoes that.

Only scripts inside entries encrypted with Luna's known header can be read or
replaced (documents produced by Luna or by this program). Documents saved by
the calculator itself use unknown keys: they can be inspected and their
entries preserved, but their script is not readable here.
"""

from __future__ import annotations

import zlib
from dataclasses import replace

from . import doccrypt
from ._luna_data import DEFAULT_PROCESSED_DOCUMENT_XML, LUA_FOOTER, LUA_HEADER
from .container import METHOD_TI_ENCRYPTED, TnsDocument, TnsEntry, parse, write

PROBLEM = "Problem1.xml"
_CDATA_RESTART = b"]]><![CDATA["
DEFAULT_VERSION = "0500"  # Luna's default; 0700 only when BMP resources are added


class NotLuaDocumentError(ValueError):
    """The document has no Lua script this module can read."""


def _encode_script(lua_source: str) -> bytes:
    data = lua_source.encode("utf-8")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    # Same as Luna fix_cdata_end_seq(): "]]>" -> "]]" + "]]><![CDATA[" + ">"
    return data.replace(b"]]>", b"]]" + _CDATA_RESTART + b">")


def _problem_entry(lua_source: str, template: TnsEntry | None = None) -> TnsEntry:
    raw = doccrypt.encrypt_entry(LUA_HEADER + _encode_script(lua_source) + LUA_FOOTER)
    # Luna (minizip, method 0x0D treated as stored) writes CRC and both sizes of
    # the bytes actually stored; keep that convention for generated entries.
    fields = dict(name=PROBLEM, method=METHOD_TI_ENCRYPTED, raw=raw,
                  crc32=zlib.crc32(raw), uncompressed_size=len(raw))
    if template is None:
        return TnsEntry(version_made_by=0, name_bytes=PROBLEM.encode(), **fields)
    return replace(template, **fields)


def build_lua_document(lua_source: str) -> bytes:
    """Create a ``.tns`` holding ``lua_source`` (byte-identical to Luna 2.1)."""
    doc_xml = TnsEntry(
        name="Document.xml", method=METHOD_TI_ENCRYPTED, raw=DEFAULT_PROCESSED_DOCUMENT_XML,
        crc32=zlib.crc32(DEFAULT_PROCESSED_DOCUMENT_XML),
        uncompressed_size=len(DEFAULT_PROCESSED_DOCUMENT_XML),
        version_made_by=0, name_bytes=b"Document.xml",
    )
    return write(TnsDocument(version=DEFAULT_VERSION, entries=[doc_xml, _problem_entry(lua_source)]))


def read_script(doc: TnsDocument) -> str:
    """Return the Lua source of a Luna-style document."""
    try:
        entry = doc.entry(PROBLEM)
    except KeyError as exc:
        raise NotLuaDocumentError("no Problem1.xml in the document") from exc
    if not entry.is_encrypted:
        raise NotLuaDocumentError("Problem1.xml is not TI-encrypted XML")
    tixc = doccrypt.decrypt_entry(entry.raw)  # may raise UnknownKeyError
    if not (tixc.startswith(LUA_HEADER) and tixc.endswith(LUA_FOOTER)):
        raise NotLuaDocumentError("Problem1.xml is not a single Lua script widget")
    body = tixc[len(LUA_HEADER):len(tixc) - len(LUA_FOOTER)]
    return body.replace(_CDATA_RESTART, b"").decode("utf-8")


def replace_script(doc: TnsDocument, lua_source: str) -> TnsDocument:
    """Copy of ``doc`` with a new script; every other entry is kept byte for byte."""
    read_script(doc)  # refuses documents whose script cannot be read back
    new = TnsDocument(version=doc.version, entries=list(doc.entries),
                      end_magic=doc.end_magic, archive_comment=doc.archive_comment)
    new.replace_entry(_problem_entry(lua_source, template=doc.entry(PROBLEM)))
    return new


def try_read_script(data: bytes) -> str | None:
    """Script of a ``.tns`` file, or ``None`` if it has no readable script."""
    try:
        return read_script(parse(data))
    except (ValueError, KeyError):
        return None
