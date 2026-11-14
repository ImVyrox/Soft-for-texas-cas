"""Pages of a problem: what each page type holds (read-only) and page reordering.

Page types seen in documents made on a CX CAS, OS 4.5.5 (docs/PAGE-STRUCTURE.md):

=================  ==========================  ====================================
widget type        application                 content read here
=================  ==========================  ====================================
TI.Notepad         Notas                       notes.py
TI.ScriptApp       Lua                         lua.py / xmldoc.py
TI.Scratchpad      Calculadora                 entries (<erow>): input and cached result
TI.GeoGrapher      Gráficos / Geometría        object kinds in <fig><objs>
tabulator          Listas y hojas de cálculo   columns: name, formula, cell count
TI.DataGrapher     Datos y estadísticas        plot type
=================  ==========================  ====================================

Only page *order* can be changed: every card is kept byte for byte.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field

from . import xmldoc, xmlentry
from .container import TnsDocument
from .notes import NotesError, _card_spans

APP_NAMES = {
    "TI.Notepad": "Notas", "TI.ScriptApp": "Lua", "TI.Scratchpad": "Calculadora",
    "TI.GeoGrapher": "Gráficos y geometría", "tabulator": "Listas y hojas de cálculo",
    "TI.DataGrapher": "Datos y estadísticas",
}


@dataclass
class PageSummary:
    card: int
    widget: str
    app: str
    details: list[tuple[str, str]] = field(default_factory=list)  # (label, value), read-only
    understood: bool = True


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in el if _local(c.tag) == name), None)


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _summary(card: int, wdgt: ET.Element) -> PageSummary:
    wtype = wdgt.get("type", "?")
    s = PageSummary(card, wtype, APP_NAMES.get(wtype, "desconocida"), understood=wtype in APP_NAMES)
    if wtype == "TI.Scratchpad":
        for row in (c for c in wdgt if _local(c.tag) == "erow"):
            res = _child(row, "rslt")
            s.details.append(("Entrada", f"{_text(_child(row, 'entr'))}  →  {_text(_child(res, 'full')) if res is not None else ''}"))
    elif wtype == "TI.GeoGrapher":
        fig = _child(wdgt, "fig")
        objs = _child(fig, "objs") if fig is not None else None
        if objs is not None:
            kinds = Counter(_local(o.tag) for o in objs)
            for kind, n in sorted(kinds.items()):
                s.details.append(("Objeto", f"{kind} × {n}"))
        else:
            s.understood = False
    elif wtype == "tabulator":
        table = _child(wdgt, "table")
        cols = _child(table, "columns") if table is not None else None
        for i, col in enumerate(cols if cols is not None else []):
            cells = _child(col, "cells")
            formula = _text(_child(col, "formula"))
            n = len(cells) if cells is not None else 0
            if formula or n:
                s.details.append((f"Columna {i + 1}", f"{formula or '(sin fórmula)'}; {n} celdas"))
    elif wtype == "TI.DataGrapher":
        for plot in (e for e in wdgt.iter() if _local(e.tag) == "PlotType2"):
            s.details.append(("Gráfico", f"tipo {_text(plot)}"))
    return s  # variables (<sym>) are problem-wide: see problem_variables()


def problem_variables(xml: bytes) -> list[tuple[str, str, str]]:
    """(name, parameter, value) of the problem's variables (<sym>), e.g. f1, x, x^2."""
    root = ET.fromstring(xml)
    sym = _child(root, "sym")
    out = []
    for e in sym if sym is not None else []:
        out.append((_text(_child(e, "n")), _text(_child(e, "p")), _text(_child(e, "v"))))
    return out


def problem_summaries(xml: bytes) -> list[PageSummary]:
    root = ET.fromstring(xml)
    out = []
    for i, card in enumerate(c for c in root if _local(c.tag) == "card"):
        wdgt = _child(card, "wdgt")
        out.append(_summary(i, wdgt) if wdgt is not None else PageSummary(i, "?", "desconocida", understood=False))
    return out


# ------------------------------------------------------------------- reordering

_CARD_CLOSE = b"</card>"


def _card_blocks(xml: bytes) -> tuple[int, int, list[bytes]]:
    """(start of first card, end of last card, exact bytes of every card)."""
    spans = _card_spans(xml)
    if not spans:
        raise NotesError("el problema no tiene páginas")
    blocks = []
    for start, end in spans:
        close = xml.rfind(_CARD_CLOSE, start, end)
        if close < 0:
            raise NotesError("página sin cierre </card>")
        blocks.append((start, close + len(_CARD_CLOSE)))
    for (a, b), (c, _) in zip(blocks, blocks[1:]):
        if xml[b:c].strip():
            raise NotesError("hay contenido entre páginas; no se reordena")
    return blocks[0][0], blocks[-1][1], [xml[a:b] for a, b in blocks]


def reorder(xml: bytes, order: list[int]) -> bytes:
    """Problem XML with its pages in ``order`` (a permutation); every page is kept byte for byte."""
    first, last, cards = _card_blocks(xml)
    if sorted(order) != list(range(len(cards))):
        raise NotesError("el nuevo orden debe incluir cada página exactamente una vez")
    body = b"".join(cards[i] for i in order)
    new = xml[:first] + body + xml[last:]
    ET.fromstring(new)
    _, _, after = _card_blocks(new)
    if after != [cards[i] for i in order] or len(new) != len(xml):
        raise NotesError("la reordenación no conservó las páginas")
    return new


def reorder_pages(doc: TnsDocument, problem: str, order: list[int]) -> TnsDocument:
    _, xml = xmldoc.decode_entry(doc.entry(problem))
    return xmlentry.rewrite(doc, problem, xml, reorder(xml, order))


def has_cross_page_refs(xml: bytes) -> bool:
    """True if the problem has variables (<sym>): pages may depend on each other through them."""
    return bool(problem_variables(xml))

