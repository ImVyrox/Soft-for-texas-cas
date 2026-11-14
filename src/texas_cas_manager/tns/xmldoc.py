"""Readable content of the XML components: properties, widgets, scripts.

Reading uses ``xml.etree`` (standard library) on the decoded XML. Editing a
script never re-serialises the document: only the bytes inside the chosen
``<…:script>`` element are replaced, so every other byte of the XML is kept.
"""

from __future__ import annotations

import re
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from . import doccrypt, tixc
from .container import TnsEntry

SCRIPT_NS = "urn:TI.ScriptApp"
_SCRIPT_RE = re.compile(rb"<([A-Za-z_][\w.-]*):script\b[^>]*>")
_CDATA_RE = re.compile(rb"<!\[CDATA\[(.*?)\]\]>", re.S)
CDATA_RESTART = b"]]><![CDATA["

# How the directory CRC/size of an encrypted entry are computed.
META_FINAL = "final"  # CRC/size of the decoded XML (documents saved by TI)
META_LEGACY = "legacy"  # CRC/size of the stored bytes (Luna and this program)
META_MISMATCH = "mismatch"


class XmlContentError(ValueError):
    """The decoded XML is not what the operation expects."""


def decode_entry(entry: TnsEntry) -> tuple[bytes, bytes]:
    """(TIXC, XML) of an encrypted entry. Raises ProtectedEntryError/TixcError/ValueError."""
    stream = doccrypt.decrypt_entry(entry.raw)
    if stream.startswith(b"<?xml"):  # plain XML inside the encryption (accepted by Rust TNS)
        return stream, stream
    return stream, tixc.decode(stream)


def metadata_convention(entry: TnsEntry, xml: bytes) -> str:
    if entry.uncompressed_size == len(xml) and entry.crc32 == zlib.crc32(xml):
        return META_FINAL
    if entry.uncompressed_size == len(entry.raw) and entry.crc32 == zlib.crc32(entry.raw):
        return META_LEGACY
    return META_MISMATCH


@dataclass
class ScriptInfo:
    problem: str
    index: int  # n-th script element in the problem
    title: str
    version: str
    protected: bool  # sc:cry != 0: TI marks the script as encrypted/protected
    source: str


@dataclass
class ProblemInfo:
    name: str
    widgets: list[tuple[str, str]] = field(default_factory=list)  # (type, version)
    scripts: list[ScriptInfo] = field(default_factory=list)
    variables: list[tuple[str, str]] = field(default_factory=list)
    referenced_files: list[str] = field(default_factory=list)  # e.g. Python sources


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse(xml: bytes) -> ET.Element:
    try:
        return ET.fromstring(xml)
    except ET.ParseError as exc:
        raise XmlContentError(f"XML no válido: {exc}") from exc


def _children(node: ET.Element, local: str) -> list[ET.Element]:
    return [el for el in node.iter() if _local(el.tag) == local]


def _child(node: ET.Element, local: str) -> ET.Element | None:
    return next((el for el in node if _local(el.tag) == local), None)


def document_properties(xml: bytes) -> dict[str, str]:
    """Flat view of ``<properties>`` and ``<settings>`` from Document.xml."""
    root = _parse(xml)
    props: dict[str, str] = {}
    for section in ("properties", "settings"):
        node = _child(root, section)
        if node is None:
            continue
        for child in node:
            props[f"{section}.{_local(child.tag)}"] = (child.text or "").strip()
    return props


def problem_info(name: str, xml: bytes) -> ProblemInfo:
    # <prob> declares a default namespace (urn:TI.Problem): match local names only.
    root = _parse(xml)
    info = ProblemInfo(name)
    for sym in _children(root, "sym"):
        for e in sym:
            n, v = _child(e, "n"), _child(e, "v")
            if n is not None:
                info.variables.append(((n.text or ""), (v.text or "") if v is not None else ""))
    widgets = _children(root, "wdgt")
    for w in widgets:
        info.widgets.append((w.get("type", "?"), w.get("ver", "")))
        for el in w.iter():
            if _local(el.tag) == "name" and el.tag.startswith("{urn:TI.PythonEditor}") and el.text:
                info.referenced_files.append(el.text)
    for i, script in enumerate(el for el in root.iter() if _local(el.tag) == "script"):
        widget = next((w for w in widgets if script in list(w.iter())), None)
        title, cry = "", "0"
        if widget is not None:
            for el in widget.iter():
                if _local(el.tag) == "mde" and el.get("name") == "TITLE":
                    title = el.text or ""
                if _local(el.tag) == "cry":
                    cry = (el.text or "0").strip()
        info.scripts.append(ScriptInfo(name, i, title, script.get("version", ""), cry not in ("", "0"),
                                       script.text or ""))
    return info


def _script_spans(xml: bytes) -> list[tuple[int, int]]:
    """(content_start, content_end) of every ``<p:script>…</p:script>`` element."""
    spans = []
    for m in _SCRIPT_RE.finditer(xml):
        if m.group(0).endswith(b"/>"):
            continue
        close = xml.find(b"</" + m.group(1) + b":script>", m.end())
        if close < 0:
            raise XmlContentError("script element without closing tag")
        spans.append((m.end(), close))
    return spans


def encode_cdata(source: str) -> bytes:
    data = source.encode("utf-8")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    # Like Luna: split any "]]>" across two CDATA sections.
    return b"<![CDATA[" + data.replace(b"]]>", b"]]" + CDATA_RESTART + b">") + b"]]>"


def replace_script(xml: bytes, index: int, source: str) -> bytes:
    """XML with the ``index``-th script content replaced; other bytes untouched."""
    spans = _script_spans(xml)
    if not 0 <= index < len(spans):
        raise XmlContentError(f"el documento no tiene script número {index + 1}")
    start, end = spans[index]
    inner = xml[start:end]
    if _CDATA_RE.sub(b"", inner).strip():
        raise XmlContentError("el script no está guardado como CDATA; no se modifica")
    new = xml[:start] + encode_cdata(source) + xml[end:]
    _parse(new)  # still well-formed
    return new
