"""Notes pages (``TI.Notepad`` widgets): read their content, edit plain text.

Layout observed in real documents (docs/NOTES-FORMAT.md): each ``<card>`` of
a ``ProblemN.xml`` is a page; a Notes page holds ``<np:fmtxt>`` whose text is
an *escaped* XML document ``<r2dtotree>`` with a ``formatManager`` and a tree
``1doc > 1para > 1rtline > leaves``. Text runs are
``<leaf name="1word" np="1" id0=FORMAT pp0=LENGTH>text</leaf>``; maths boxes
are ``<node name="0el" flags="8">`` with ``<mbox>``; images are widget leaves
naming a ``.BMP`` entry of the container.

Editing is deliberately narrow: only the text of existing ``1word`` leaves
with a single format run (``np="1"``) and no child elements. In samples ``pp0``
is the character count, also for a non-ASCII character (``π`` -> ``pp0="1"``);
allowed text is ASCII letters, digits, space and punctuation that needs no XML
escaping, plus Spanish letters and ``π``.
The bytes are replaced in place inside the escaped ``np:fmtxt``; everything
else in the XML is kept byte for byte, and the result is re-read and compared
before it is accepted.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from . import xmldoc, xmlentry
from .container import TnsDocument
from .lua import problem_names

_CARD_RE = re.compile(rb"<card\b")
_FMTXT_RE = re.compile(rb"<([A-Za-z_][\w.-]*):fmtxt>(.*?)</\1:fmtxt>", re.S)
# A text run as written inside the escaped np:fmtxt (TI escapes < > " as entities).
_RUN_RE = re.compile(rb"&lt;leaf name=&quot;1word&quot;(.*?)(/&gt;|&gt;(.*?)&lt;/leaf&gt;)", re.S)
_PLAIN_RUN_ATTRS = re.compile(rb" np=&quot;1&quot; id0=&quot;(\d+)&quot; pp0=&quot;(\d+)&quot;\Z")
# Characters allowed in edited text (none needs XML escaping): ASCII letters, digits,
# space and punctuation, Spanish letters and π. Others stay read-only until verified.
ALLOWED = re.compile(r"[A-Za-z0-9 .,;:!?()\[\]{}+\-*/=_'%#@^~|$áéíóúüñÁÉÍÓÚÜÑ¿¡π]*\Z")


class NotesError(ValueError):
    """The notes content cannot be read or the edit is not allowed."""


@dataclass
class TextRun:
    index: int  # n-th 1word leaf of the page (document order)
    text: str
    format_id: int | None
    editable: bool
    reason: str = ""  # why it is read-only


@dataclass
class MathBox:
    input: str
    output: str  # cached result shown by TI ("" if none)


@dataclass
class NotesPage:
    problem: str
    card: int  # 0-based card (page) index in the problem
    widget: str  # widget type of the page
    runs: list[TextRun] = field(default_factory=list)
    math: list[MathBox] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    paragraphs: int = 0
    readable: bool = True
    error: str = ""

    @property
    def is_notes(self) -> bool:
        return self.widget == "TI.Notepad"

    @property
    def text(self) -> str:
        return " ".join(r.text for r in self.runs if r.text)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _card_spans(xml: bytes) -> list[tuple[int, int]]:
    starts = [m.start() for m in _CARD_RE.finditer(xml)]
    return [(s, starts[i + 1] if i + 1 < len(starts) else len(xml)) for i, s in enumerate(starts)]


def _parse_inner(inner: str, page: NotesPage) -> None:
    root = ET.fromstring(inner)
    runs = [el for el in root.iter() if el.tag == "leaf" and el.get("name") == "1word"]
    for i, leaf in enumerate(runs):
        text = leaf.text or ""
        fid = int(leaf.get("id0")) if (leaf.get("id0") or "").isdigit() else None
        reason = ""
        if leaf.get("np") != "1":
            reason = "varios formatos en el mismo fragmento"
        elif len(leaf):
            reason = "contiene elementos (cursor u objetos)"
        elif not text:
            reason = "fragmento vacío"
        elif leaf.get("pp0") != str(len(text)):
            reason = "longitud declarada distinta del texto"
        elif not ALLOWED.match(text):
            reason = "contiene caracteres sin verificar"
        page.runs.append(TextRun(i, text, fid, not reason, reason))
    for node in root.iter("node"):
        if node.get("name") == "1para":
            page.paragraphs += 1
        mbox = next((c for c in node if c.tag == "mbox"), None)
        if node.get("name") == "0el" and mbox is not None:
            texts = [(lf.text or "", lf.get("readonly") == "1") for lf in node.iter("leaf") if lf.get("name") == "0text"]
            full = mbox.find("out/full")
            page.math.append(MathBox("".join(t for t, ro in texts if not ro),
                                     full.text if full is not None and full.text else ""))
    for w in root.iter("wdgt"):
        name = w.find("name")
        if w.get("type") == "Image" and name is not None and name.text:
            page.images.append(name.text)


def problem_pages(problem: str, xml: bytes) -> list[NotesPage]:
    """Every page (card) of a problem, with Notes content parsed."""
    pages = []
    for i, (start, end) in enumerate(_card_spans(xml)):
        chunk = xml[start:end]
        wm = re.search(rb'<wdgt\b[^>]*\btype="([^"]+)"', chunk)
        page = NotesPage(problem, i, wm.group(1).decode() if wm else "?")
        if page.is_notes:
            fm = _FMTXT_RE.search(chunk)
            if fm:
                try:
                    inner = ET.fromstring(b"<x>" + fm.group(2) + b"</x>").text or ""
                    _parse_inner(inner, page)
                except ET.ParseError as exc:
                    page.readable, page.error = False, f"texto enriquecido no válido: {exc}"
        pages.append(page)
    return pages


def document_pages(doc: TnsDocument) -> list[NotesPage]:
    pages = []
    for name in problem_names(doc):
        _, xml = xmldoc.decode_entry(doc.entry(name))
        pages += problem_pages(name, xml)
    return pages


def replace_texts(xml: bytes, card: int, edits: dict[int, str]) -> bytes:
    """Problem XML with run texts of one Notes page replaced (run index -> new text)."""
    page = next((p for p in problem_pages("?", xml) if p.card == card), None)
    if page is None or not page.is_notes or not page.readable:
        raise NotesError(f"la página {card + 1} no es una página de notas legible")
    runs = {r.index: r for r in page.runs}
    for idx, text in edits.items():
        run = runs.get(idx)
        if run is None or not run.editable:
            raise NotesError(f"el fragmento {idx + 1} no es editable ({run.reason if run else 'no existe'})")
        if not text or not ALLOWED.match(text):
            raise NotesError("texto no permitido: usa letras (incluidas á é í ó ú ü ñ), números, espacios, "
                             "π y puntuación básica; no se permiten < > & \"")
    start, end = _card_spans(xml)[card]
    chunk = xml[start:end]
    fm = _FMTXT_RE.search(chunk)
    body_start, body_end = start + fm.start(2), start + fm.end(2)
    body = xml[body_start:body_end]
    out, pos = [], 0
    for i, m in enumerate(_RUN_RE.finditer(body)):
        if i not in edits:
            continue
        attrs = _PLAIN_RUN_ATTRS.search(m.group(1))
        if attrs is None or m.group(3) is None:
            raise NotesError(f"fragmento {i + 1} con una forma inesperada; no se modifica")
        new_attrs = m.group(1)[:attrs.start(2)] + str(len(edits[i])).encode() + m.group(1)[attrs.end(2):]
        out += [body[pos:m.start(1)], new_attrs, b"&gt;", edits[i].encode("utf-8"), b"&lt;/leaf&gt;"]
        pos = m.end()
    out.append(body[pos:])
    new = xml[:body_start] + b"".join(out) + xml[body_end:]
    _verify(xml, new, card, edits)
    return new


def _verify(old: bytes, new: bytes, card: int, edits: dict[int, str]) -> None:
    """The new XML must parse and differ from the old one only in the edited runs."""
    try:
        ET.fromstring(new)
    except ET.ParseError as exc:
        raise NotesError(f"el XML resultante no es válido: {exc}") from exc
    before = problem_pages("?", old)
    after = problem_pages("?", new)
    if len(before) != len(after):
        raise NotesError("cambió el número de páginas")
    for b, a in zip(before, after):
        if (b.widget, b.math, b.images, b.paragraphs, len(b.runs)) != (a.widget, a.math, a.images, a.paragraphs, len(a.runs)):
            raise NotesError(f"cambió la estructura de la página {b.card + 1}")
        for rb_, ra in zip(b.runs, a.runs):
            expected = edits.get(rb_.index, rb_.text) if b.card == card else rb_.text
            if ra.text != expected or ra.format_id != rb_.format_id:
                raise NotesError(f"el fragmento {rb_.index + 1} de la página {b.card + 1} no quedó como se esperaba")


def edit_notes(doc: TnsDocument, problem: str, card: int, edits: dict[int, str]) -> TnsDocument:
    """Copy of ``doc`` with note texts replaced; other entries kept byte for byte."""
    _, xml = xmldoc.decode_entry(doc.entry(problem))
    return xmlentry.rewrite(doc, problem, xml, replace_texts(xml, card, edits))
