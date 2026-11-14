"""Analysis and validation of ``.tns`` documents (read-only, never writes).

Every value in a report comes from parsing the given bytes: nothing is
assumed from file names or document type.
"""

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass, field

from . import doccrypt, tixc, xmldoc
from .container import (METHOD_DEFLATED, METHOD_STORED, METHOD_TI_ENCRYPTED, TnsDocument, TnsFormatError,
                        parse, write)
from .lua import is_luna_template, problem_names

METHOD_NAMES = {METHOD_STORED: "sin comprimir", METHOD_DEFLATED: "deflate", METHOD_TI_ENCRYPTED: "XML cifrado TI"}
FULL = "completamente interpretable"
PARTIAL = "parcialmente interpretable"


@dataclass
class EntryReport:
    name: str
    method: int
    stored_size: int
    declared_size: int
    status: str  # "ok", "protegido: …" or "error: …"
    readable: bool  # content can be extracted
    header: str = ""  # TI-encrypted entries: "Luna (fija)" or "propia del documento"
    seed: int | None = None
    metadata: str = ""  # final | legacy | mismatch (encrypted) / crc ok (plain)
    xml_size: int | None = None
    sha256: str = ""  # of the stored bytes

    @property
    def method_name(self) -> str:
        return METHOD_NAMES.get(self.method, f"método 0x{self.method:02X}")

    @property
    def kind(self) -> str:
        low = self.name.lower()
        if low.endswith(".xml"):
            return "XML"
        if low.endswith((".bmp", ".png", ".jpg", ".jpeg", ".gif")):
            return "Imagen"
        if low.endswith(".py"):
            return "Python"
        if low.endswith(".lua"):
            return "Lua"
        return "Recurso"

    @property
    def encrypted(self) -> bool:
        return self.method == METHOD_TI_ENCRYPTED

    @property
    def compressed(self) -> bool:
        return self.method in (METHOD_DEFLATED, METHOD_TI_ENCRYPTED)  # 0x0D bodies are deflated


@dataclass
class DocumentReport:
    version: str
    size: int
    sha256: str = ""
    entries: list[EntryReport] = field(default_factory=list)
    lua_script: str | None = None  # first script, if any
    lua_status: str = ""
    scripts: list[xmldoc.ScriptInfo] = field(default_factory=list)
    problems_info: list[xmldoc.ProblemInfo] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    origin: str = ""  # Luna / nativo / mixto / desconocido
    kind: str = ""
    roundtrip_identical: bool = False
    problems: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.problems

    @property
    def xml_blocks(self) -> int:
        return sum(1 for e in self.entries if e.kind == "XML")

    @property
    def compressed_blocks(self) -> int:
        return sum(1 for e in self.entries if e.compressed)

    @property
    def encrypted_blocks(self) -> int:
        return sum(1 for e in self.entries if e.encrypted)

    @property
    def resources(self) -> list[EntryReport]:
        return [e for e in self.entries if e.kind != "XML"]

    @property
    def interpretation(self) -> str:
        return FULL if all(e.readable for e in self.entries) and not self.problems else PARTIAL


def check_entry(entry) -> tuple[EntryReport, bytes | None]:
    """Report for one entry and, for XML entries, its decoded XML."""
    rep = EntryReport(entry.name, entry.method, len(entry.raw), entry.uncompressed_size, "ok", True,
                      sha256=hashlib.sha256(entry.raw).hexdigest())
    xml = None
    if entry.is_encrypted:
        try:
            header = doccrypt.read_header(entry.raw)
            rep.seed = header.seed
            rep.header = "Luna (fija)" if doccrypt.has_luna_header(entry.raw) else "propia del documento"
            _, xml = xmldoc.decode_entry(entry)
            rep.xml_size = len(xml)
            rep.metadata = xmldoc.metadata_convention(entry, xml)
            if rep.metadata == xmldoc.META_MISMATCH:
                rep.status = "error: el CRC/tamaño del directorio no coincide con el contenido"
        except doccrypt.ProtectedEntryError as exc:
            rep.status, rep.readable = f"protegido: {exc}", False
        except (tixc.TixcError, ValueError) as exc:
            rep.status, rep.readable = f"error: {exc}", False
    else:
        try:
            entry.payload()
            rep.metadata = "crc ok"
        except TnsFormatError as exc:
            rep.status, rep.readable = f"error: {exc}", False
    return rep, xml


def _origin(doc: TnsDocument, reports: list[EntryReport]) -> str:
    """Decided by the problems: Luna ships a TI-made Document.xml with its own header."""
    names = problem_names(doc)
    by_name = {r.name: r for r in reports}
    headers = {by_name[n].header for n in names if by_name[n].header}
    if not names or not headers:
        return "desconocido"
    if all(is_luna_template(doc.entry(n)) for n in names):
        return "Luna / Texas CAS Manager"
    if headers == {"propia del documento"}:
        return "nativo (calculadora o software TI)"
    if headers == {"Luna (fija)"}:
        return "cabecera de Luna (otro generador)"
    return "mixto"


def analyze(data: bytes) -> DocumentReport:
    """Parse and check a document. Raises TnsFormatError if the container cannot be parsed."""
    doc = parse(data)
    rep = DocumentReport(version=doc.version, size=len(data), sha256=hashlib.sha256(data).hexdigest())
    xmls: dict[str, bytes] = {}
    for e in doc.entries:
        er, xml = check_entry(e)
        rep.entries.append(er)
        if xml is not None:
            xmls[e.name] = xml
    rep.problems = [f"{e.name}: {e.status[7:]}" for e in rep.entries if e.status.startswith("error")]
    if not doc.entries or doc.entries[0].name != "Document.xml":
        rep.problems.append("Document.xml no es la primera entrada")
    rep.roundtrip_identical = write(doc) == data
    rep.origin = _origin(doc, rep.entries)

    if "Document.xml" in xmls:
        try:
            rep.properties = xmldoc.document_properties(xmls["Document.xml"])
        except xmldoc.XmlContentError as exc:
            rep.problems.append(f"Document.xml: {exc}")
    for name in problem_names(doc):
        if name in xmls:
            try:
                info = xmldoc.problem_info(name, xmls[name])
            except xmldoc.XmlContentError as exc:
                rep.problems.append(f"{name}: {exc}")
                continue
            rep.problems_info.append(info)
            rep.scripts += info.scripts

    widget_types = sorted({w for p in rep.problems_info for w, _ in p.widgets})
    rep.kind = ", ".join(widget_types) if widget_types else "sin widgets reconocidos"
    if rep.scripts:
        rep.lua_script = rep.scripts[0].source
        protected = sum(s.protected for s in rep.scripts)
        rep.lua_status = (f"{len(rep.scripts)} script(s) Lua" +
                          (f", {protected} protegido(s) por TI" if protected else ", editables"))
    elif any(not e.readable for e in rep.entries if e.kind == "XML"):
        rep.lua_status = "No se pudo leer todo el XML (ver componentes)"
    else:
        rep.lua_status = "Sin scripts Lua"
    return rep


def text_report(name: str, rep: DocumentReport) -> str:
    """Plain-text summary in the format of docs/TNS-EDITOR.md."""
    lines = [
        f"Documento: {name}",
        "Formato: TI-Nspire (.tns)",
        "Firma: válida (*TIMLP / TIPD)",
        f"Versión: {rep.version} (cabecera *TIMLP{rep.version})",
        f"Origen: {rep.origin}",
        f"Contenido: {rep.kind}",
        f"Secciones: {len(rep.entries)}",
        f"Bloques XML: {rep.xml_blocks}",
        f"Bloques comprimidos: {rep.compressed_blocks}",
        f"Bloques cifrados: {rep.encrypted_blocks} (descifrables: "
        f"{sum(1 for e in rep.entries if e.encrypted and e.readable)})",
        f"Scripts Lua: {len(rep.scripts)}" + (f" ({rep.lua_status})" if rep.scripts else ""),
        f"Recursos: {len(rep.resources)}",
        f"Reescritura del contenedor idéntica: {'sí' if rep.roundtrip_identical else 'no'}",
        f"SHA-256: {rep.sha256}",
        f"Estado: {rep.interpretation}",
    ]
    if rep.properties:
        sw = rep.properties.get("properties.swver", "").strip()
        if sw:
            lines.append(f"Creado con: {sw}")
    for e in rep.entries:
        extra = f", XML {e.xml_size} B, metadatos {e.metadata}" if e.xml_size is not None else ""
        lines.append(f"  - {e.name}: {e.kind}, {e.method_name}, {e.stored_size} B almacenados{extra} — {e.status}")
    lines += [f"Problema: {p}" for p in rep.problems]
    return "\n".join(lines)


def validate_bytes(data: bytes) -> list[str]:
    """Problems found in a document about to be written; empty list = valid."""
    try:
        rep = analyze(data)
    except TnsFormatError as exc:
        return [str(exc)]
    problems = list(rep.problems)
    if not rep.roundtrip_identical:
        problems.append("la reescritura del contenedor no es idéntica")
    problems += [f"{e.name}: {e.status}" for e in rep.entries if not e.readable and e.kind == "XML"]
    return problems


def entry_content(doc: TnsDocument, name: str) -> bytes:
    """Extractable content of one entry: decoded XML for encrypted entries."""
    e = doc.entry(name)
    return xmldoc.decode_entry(e)[1] if e.is_encrypted else e.payload()


def crc_ok(data: bytes, crc: int) -> bool:
    return zlib.crc32(data) == crc
