"""Lua scripts: build Lua documents like Luna, read and replace scripts.

A Lua script lives in a ``TI.ScriptApp`` widget, as CDATA inside its
``<sc:script>`` element. Two kinds of documents are handled:

* **Luna template** (Luna 2.1 or this program): ``Problem1.xml`` is exactly
  Luna's template around the script, under Luna's fixed TIEN header. Rebuilt
  byte-identically to what Luna would produce.
* **Native** (saved by the calculator or TI's software): every encrypted entry
  has its own TIEN header. The script bytes are replaced in the decoded XML,
  re-encoded to TIXC and encrypted again under the entry's *own* header; the
  directory CRC/size follow the entry's original convention (xmlentry.py).
  Verified on a CX CAS on 2026-11-14 (edited stopwatch.tns opened and ran).

Scripts TI marks as protected (``sc:cry`` != 0) are never modified.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import replace

from . import doccrypt, xmldoc, xmlentry
from ._luna_data import DEFAULT_PROCESSED_DOCUMENT_XML, LUA_FOOTER, LUA_HEADER
from .container import METHOD_TI_ENCRYPTED, TnsDocument, TnsEntry, parse, write

PROBLEM = "Problem1.xml"
DEFAULT_VERSION = "0500"  # Luna's default; 0700 only when BMP resources are added
_PROBLEM_RE = re.compile(r"Problem(\d+)\.xml\Z")


class NotLuaDocumentError(ValueError):
    """The document has no Lua script."""


class ProtectedScriptError(ValueError):
    """The script is marked as protected by TI and is not modified."""


def problem_names(doc: TnsDocument) -> list[str]:
    names = [e.name for e in doc.entries if _PROBLEM_RE.match(e.name)]
    return sorted(names, key=lambda n: int(_PROBLEM_RE.match(n).group(1)))


def _luna_problem_entry(lua_source: str, template: TnsEntry | None = None) -> TnsEntry:
    cdata_body = xmldoc.encode_cdata(lua_source)[len(b"<![CDATA["):-len(b"]]>")]
    raw = doccrypt.encrypt_entry(LUA_HEADER + cdata_body + LUA_FOOTER)
    # Luna (minizip, method 0x0D stored as-is) writes CRC and sizes of the stored bytes.
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
    return write(TnsDocument(version=DEFAULT_VERSION, entries=[doc_xml, _luna_problem_entry(lua_source)]))


def is_luna_template(entry: TnsEntry) -> bool:
    if not (entry.is_encrypted and doccrypt.has_luna_header(entry.raw)):
        return False
    try:
        stream = doccrypt.decrypt_entry(entry.raw)
    except ValueError:
        return False
    return stream.startswith(LUA_HEADER) and stream.endswith(LUA_FOOTER)


def list_scripts(doc: TnsDocument) -> list[xmldoc.ScriptInfo]:
    """Every script of every problem. Raises ProtectedEntryError/TixcError if a problem cannot be read."""
    scripts = []
    for name in problem_names(doc):
        _, xml = xmldoc.decode_entry(doc.entry(name))
        scripts += xmldoc.problem_info(name, xml).scripts
    return scripts


def read_script(doc: TnsDocument) -> str:
    """Source of the first script of the document."""
    scripts = list_scripts(doc)
    if not scripts:
        raise NotLuaDocumentError("el documento no contiene scripts Lua")
    return scripts[0].source


def replace_script(doc: TnsDocument, lua_source: str, problem: str = PROBLEM, index: int = 0) -> TnsDocument:
    """Copy of ``doc`` with one script replaced; every other entry is kept byte for byte."""
    try:
        entry = doc.entry(problem)
    except KeyError as exc:
        raise NotLuaDocumentError(f"no existe {problem}") from exc
    if not entry.is_encrypted:
        raise NotLuaDocumentError(f"{problem} no es XML cifrado de TI")
    _, xml = xmldoc.decode_entry(entry)
    scripts = xmldoc.problem_info(problem, xml).scripts
    if not 0 <= index < len(scripts):
        raise NotLuaDocumentError(f"{problem} no tiene script número {index + 1}")
    if scripts[index].protected:
        raise ProtectedScriptError("TI marca este script como protegido (sc:cry); no se modifica")

    if is_luna_template(entry) and index == 0:
        new = TnsDocument(version=doc.version, entries=list(doc.entries),
                          end_magic=doc.end_magic, archive_comment=doc.archive_comment)
        new.replace_entry(_luna_problem_entry(lua_source, template=entry))
        return new
    return xmlentry.rewrite(doc, problem, xml, xmldoc.replace_script(xml, index, lua_source))


def try_read_script(data: bytes) -> str | None:
    """Script of a ``.tns`` file, or ``None`` if it has no readable script."""
    try:
        return read_script(parse(data))
    except (ValueError, KeyError):
        return None
