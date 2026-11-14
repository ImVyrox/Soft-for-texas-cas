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

from . import mathbox, xmldoc, xmlentry
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
    input: str  # linear form rebuilt from the stored input tree (mathbox.py)
    output: str  # cached result shown by TI ("" if none) or its error message
    error: int = field(default=0, compare=False)
    templates: list[str] = field(default_factory=list, compare=False)
    unknown: list[str] = field(default_factory=list, compare=False)


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
            info = mathbox.read_box(node)
            page.math.append(MathBox(info.input, info.output, info.error, info.templates, info.unknown))
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


# ------------------------------------------------------------------ paragraphs (Phase 5)
#
# Facts used (docs/NOTES-FORMAT.md): pressing Enter in a Notes page starts a new
# ``1para`` (sample: "π" Enter "n" -> two paragraphs); format entry 0 has the
# sentinel reference count 2147483647, so paragraphs whose runs all use format 0
# can be added or removed without touching any reference count. A page that TI
# re-saved after our edits came back with byte-identical XML.

SENTINEL_REFCNT = "2147483647"


@dataclass
class Paragraph:
    index: int
    text: str
    kind: str  # "text": only format-0 plain runs -> may be edited, moved, deleted; "complex": kept as is
    reason: str = ""


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _unescape(b: bytes) -> str:
    return ET.fromstring(b"<x>" + b + b"</x>").text or ""


def _paragraph_spans(inner: str) -> tuple[int, int, list[tuple[int, int]]]:
    """(doc_content_start, doc_content_end, [(start, end) of each top-level 1para]) in the inner XML."""
    doc_open = '<node name="1doc">'
    start = inner.find(doc_open)
    if start < 0:
        raise NotesError("la página no tiene nodo 1doc")
    pos = start + len(doc_open)
    content_start, spans, depth, para_start = pos, [], 0, None
    tag_re = re.compile(r"<(/?)(node|leaf)\b[^>]*?(/?)>")
    for m in tag_re.finditer(inner, pos):
        closing, name, selfclose = m.group(1), m.group(2), m.group(3)
        if name != "node" or selfclose:
            continue
        if not closing:
            if depth == 0:
                if 'name="1para"' not in m.group(0):
                    raise NotesError("elemento inesperado dentro de 1doc")
                para_start = m.start()
            depth += 1
        else:
            if depth == 0:  # closes 1doc
                return content_start, m.start(), spans
            depth -= 1
            if depth == 0:
                spans.append((para_start, m.end()))
    raise NotesError("1doc sin cerrar")


def _classify(para_xml: str, index: int) -> Paragraph:
    el = ET.fromstring(para_xml)
    lines = list(el)
    texts, reason = [], ""
    if not lines or any(c.tag != "node" or c.get("name") != "1rtline" for c in lines):
        reason = "estructura de párrafo inesperada"
    for line in lines:
        for leaf in line:
            if leaf.tag != "leaf" or leaf.get("name") != "1word":
                reason = reason or "contiene cuadros matemáticos u objetos"
            elif len(leaf):
                reason = reason or "contiene el cursor u otros elementos"
            elif leaf.get("np") != "1" or leaf.get("id0") != "0":
                reason = reason or "usa un formato distinto del básico"
            elif leaf.get("pp0") != str(len(leaf.text or "")):
                reason = reason or "longitud declarada distinta del texto"
            else:
                texts.append(leaf.text or "")
    text = "".join(texts)
    if not reason and text and not ALLOWED.match(text):
        reason = "contiene caracteres sin verificar"
    return Paragraph(index, text, "complex" if reason else "text", reason)


def _page_inner(xml: bytes, card: int) -> tuple[int, int, str]:
    spans = _card_spans(xml)
    if not 0 <= card < len(spans):
        raise NotesError(f"la página {card + 1} no existe")
    start, end = spans[card]
    fm = _FMTXT_RE.search(xml[start:end])
    if not fm:
        raise NotesError(f"la página {card + 1} no es una página de notas")
    body = fm.group(2)
    inner = _unescape(body)
    if _escape(inner).encode() != body:
        raise NotesError("el texto de la página usa un escapado distinto del esperado; no se modifica")
    return start + fm.start(2), start + fm.end(2), inner


def page_paragraphs(xml: bytes, card: int) -> list[Paragraph]:
    _, _, inner = _page_inner(xml, card)
    _, _, spans = _paragraph_spans(inner)
    return [_classify(inner[a:b], i) for i, (a, b) in enumerate(spans)]


def structure_allowed(xml: bytes, card: int) -> tuple[bool, str]:
    """Whether paragraphs of this page may be added/removed/moved, and why not."""
    try:
        _, _, inner = _page_inner(xml, card)
        root = ET.fromstring(inner)
    except (NotesError, ET.ParseError) as exc:
        return False, str(exc)
    entry0 = next((f for f in root.iter("formatEntry") if f.get("entryIndex") == "0"), None)
    if entry0 is None or entry0.get("entryRefCnt") != SENTINEL_REFCNT:
        return False, "el formato básico no tiene el contador esperado"
    return True, ""


def _new_paragraph(text: str) -> str:
    leaf = (f'<leaf name="1word" np="1" id0="0" pp0="{len(text)}">{_escape(text)}</leaf>' if text
            else '<leaf name="1word" np="1" id0="0" pp0="0"/>')
    return f'<node name="1para"><node name="1rtline">{leaf}</node></node>'


def set_paragraphs(xml: bytes, card: int, layout: list[int | str]) -> bytes:
    """Problem XML whose page ``card`` has the paragraphs in ``layout``.

    Each item is an ``int`` (keep that original paragraph byte for byte) or a
    ``str`` (a plain text paragraph, new or replacing a text paragraph). Complex
    paragraphs must all be kept, once each, in their original order.
    """
    ok, why = structure_allowed(xml, card)
    if not ok:
        raise NotesError(why)
    body_start, body_end, inner = _page_inner(xml, card)
    content_start, content_end, spans = _paragraph_spans(inner)
    paras = [_classify(inner[a:b], i) for i, (a, b) in enumerate(spans)]
    kept = [item for item in layout if isinstance(item, int)]
    if len(kept) != len(set(kept)) or any(not 0 <= i < len(paras) for i in kept):
        raise NotesError("cada párrafo original solo puede aparecer una vez")
    complex_ids = [p.index for p in paras if p.kind == "complex"]
    if [i for i in kept if paras[i].kind == "complex"] != complex_ids:
        raise NotesError("los párrafos con matemáticas u objetos deben conservarse y en su orden")
    if not layout:
        raise NotesError("la página debe tener al menos un párrafo")
    parts = []
    for item in layout:
        if isinstance(item, int):
            parts.append(inner[spans[item][0]:spans[item][1]])
        else:
            if item and not ALLOWED.match(item):
                raise NotesError("texto no permitido en un párrafo nuevo")
            parts.append(_new_paragraph(item))
    new_inner = inner[:content_start] + "".join(parts) + inner[content_end:]
    new = xml[:body_start] + _escape(new_inner).encode() + xml[body_end:]
    _verify_layout(xml, new, card, layout, inner, spans)
    return new


def _verify_layout(old: bytes, new: bytes, card: int, layout, old_inner: str, old_spans) -> None:
    try:
        ET.fromstring(new)
    except ET.ParseError as exc:
        raise NotesError(f"el XML resultante no es válido: {exc}") from exc
    if old[:_card_spans(old)[card][0]] != new[:_card_spans(new)[card][0]]:
        raise NotesError("cambió contenido anterior a la página")
    after = _card_spans(new)
    if len(after) != len(_card_spans(old)) or old[_card_spans(old)[card][1]:] != new[after[card][1]:]:
        raise NotesError("cambió contenido posterior a la página")
    _, _, inner = _page_inner(new, card)
    _, _, spans = _paragraph_spans(inner)
    got = [_classify(inner[a:b], i) for i, (a, b) in enumerate(spans)]
    if len(got) != len(layout):
        raise NotesError("el número de párrafos no es el esperado")
    for item, (a, b), p in zip(layout, spans, got):
        if isinstance(item, int):
            if inner[a:b] != old_inner[old_spans[item][0]:old_spans[item][1]]:
                raise NotesError("un párrafo conservado cambió")
        elif p.kind != "text" or p.text != item:
            raise NotesError("un párrafo nuevo no quedó como se esperaba")


def edit_paragraphs(doc: TnsDocument, problem: str, card: int, layout: list[int | str]) -> TnsDocument:
    _, xml = xmldoc.decode_entry(doc.entry(problem))
    return xmlentry.rewrite(doc, problem, xml, set_paragraphs(xml, card, layout))
