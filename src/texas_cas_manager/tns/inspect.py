"""Inspection and validation of ``.tns`` documents (read-only)."""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field

from . import doccrypt
from .container import METHOD_DEFLATED, METHOD_STORED, TnsDocument, TnsFormatError, parse, write
from .lua import NotLuaDocumentError, read_script

METHOD_NAMES = {METHOD_STORED: "sin comprimir", METHOD_DEFLATED: "deflate", 0x0D: "XML cifrado TI"}


@dataclass
class EntryReport:
    name: str
    method: int
    stored_size: int
    declared_size: int
    status: str  # "ok", "clave desconocida", or an error message
    readable: bool  # content can be extracted

    @property
    def method_name(self) -> str:
        return METHOD_NAMES.get(self.method, f"método 0x{self.method:02X}")

    @property
    def kind(self) -> str:
        low = self.name.lower()
        if low.endswith(".xml"):
            return "XML"
        if low.endswith((".bmp", ".png", ".jpg", ".jpeg")):
            return "Imagen"
        if low.endswith(".py"):
            return "Python"
        if low.endswith(".lua"):
            return "Lua"
        return "Recurso"


@dataclass
class DocumentReport:
    version: str
    size: int
    entries: list[EntryReport] = field(default_factory=list)
    lua_script: str | None = None
    lua_status: str = ""
    roundtrip_identical: bool = False
    problems: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.problems


def check_entry(entry) -> EntryReport:
    if entry.is_encrypted:
        try:
            doccrypt.decrypt_entry(entry.raw)
            status, readable = "ok", True
        except doccrypt.UnknownKeyError:
            status, readable = "clave desconocida", False
        except ValueError as exc:
            status, readable = f"error: {exc}", False
    else:
        try:
            entry.payload()
            status, readable = "ok", True
        except TnsFormatError as exc:
            status, readable = f"error: {exc}", False
    return EntryReport(entry.name, entry.method, len(entry.raw), entry.uncompressed_size, status, readable)


def analyze(data: bytes) -> DocumentReport:
    """Parse and check a document. Raises TnsFormatError if it cannot be parsed."""
    doc = parse(data)
    rep = DocumentReport(version=doc.version, size=len(data))
    rep.entries = [check_entry(e) for e in doc.entries]
    rep.problems = [f"{e.name}: {e.status}" for e in rep.entries if e.status.startswith("error")]
    if not doc.entries or doc.entries[0].name != "Document.xml":
        rep.problems.append("Document.xml no es la primera entrada")
    rep.roundtrip_identical = write(doc) == data
    try:
        rep.lua_script = read_script(doc)
        rep.lua_status = "Script Lua editable"
    except doccrypt.UnknownKeyError:
        rep.lua_status = "Contenido cifrado con clave desconocida (documento guardado por la calculadora o el software de TI)"
    except (NotLuaDocumentError, ValueError) as exc:
        rep.lua_status = f"Sin script Lua editable: {exc}"
    return rep


def validate_bytes(data: bytes) -> list[str]:
    """Problems found in a document about to be written; empty list = valid."""
    try:
        rep = analyze(data)
    except TnsFormatError as exc:
        return [str(exc)]
    problems = list(rep.problems)
    if not rep.roundtrip_identical:
        problems.append("la reescritura del contenedor no es idéntica")
    return problems


def entry_content(doc: TnsDocument, name: str) -> bytes:
    """Extractable content of one entry (TIXC data for known encrypted XML)."""
    e = doc.entry(name)
    return doccrypt.decrypt_entry(e.raw) if e.is_encrypted else e.payload()


def crc_ok(data: bytes, crc: int) -> bool:
    return zlib.crc32(data) == crc
