"""Read-only view of maths boxes (``<node name="0el" flags="8">`` with ``<mbox>``).

Structure observed in documents made on a CX CAS (docs/MATH-FORMAT.md): the
box holds ``<mbox>`` (attributes and the cached result ``<out><full>``) and two
``0el`` children: the typed input and the read-only displayed output. Inside,
text is in ``0text`` leaves and 2-D templates are nodes named ``0fraction``,
``0sqrt``, ``0power``, ``0integral``, ``0matrix`` and ``0mline``.

The linear form below is for display only: it is built from the stored tree
and never computed. Editing is not offered (see MATH-FORMAT.md).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# Templates seen in samples -> number of 0el children they hold.
KNOWN_TEMPLATES = {"0fraction": 2, "0sqrt": 1, "0power": 1, "0integral": 4, "0matrix": None, "0mline": 1}


@dataclass
class MathInfo:
    input: str  # linear form rebuilt from the input tree
    output: str  # TI's cached result (<out><full>) or the error text
    error: int = 0  # <out><err>
    templates: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)  # node names not understood


def _children_el(node: ET.Element) -> list[ET.Element]:
    return [c for c in node if c.tag == "node" and c.get("name") == "0el"]


def linear(el: ET.Element, info: MathInfo) -> str:
    """Linear text of a ``0el`` subtree."""
    out = []
    for child in el:
        name = child.get("name")
        if child.tag == "leaf" and name == "0text":
            out.append(child.text or "")
        elif child.tag == "node" and name == "0el":
            out.append(linear(child, info))
        elif child.tag == "node" and name in KNOWN_TEMPLATES:
            info.templates.append(name)
            parts = [linear(c, info) for c in _children_el(child)]
            expected = KNOWN_TEMPLATES[name]
            if expected is not None and len(parts) != expected:
                info.unknown.append(f"{name} con {len(parts)} partes")
                out.append("?")
            elif name == "0fraction":
                out.append(f"({parts[0]})/({parts[1]})")
            elif name == "0sqrt":
                out.append(f"√({parts[0]})")
            elif name == "0power":
                out.append(f"^({parts[0]})")
            elif name == "0integral":  # stored order (one sample): lower, upper, integrand, variable
                out.append(f"∫({parts[2]},{parts[3]},{parts[0]},{parts[1]})")
            elif name == "0matrix":
                cols = int(child.get("data", "0") or 0)
                if cols <= 0 or len(parts) % cols:
                    info.unknown.append("0matrix con dimensiones no reconocidas")
                    out.append("?")
                else:
                    rows = [parts[i:i + cols] for i in range(0, len(parts), cols)]
                    out.append("[" + "".join("[" + ",".join(r) + "]" for r in rows) + "]")
            elif name == "0mline":
                out.append(f"\"{parts[0]}\"")
        elif child.tag in ("cursor",):
            continue
        else:
            info.unknown.append(name or child.tag)
            out.append("?")
    return "".join(out)


def read_box(node: ET.Element) -> MathInfo:
    """Information of one maths box node (``0el`` with ``flags="8"``)."""
    mbox = node.find("mbox")
    els = _children_el(node)
    info = MathInfo("", "")
    if els:
        info.input = linear(els[0], info)
    err = mbox.find("out/err") if mbox is not None else None
    info.error = int(err.text) if err is not None and (err.text or "").strip().lstrip("-").isdigit() else 0
    full = mbox.find("out/full") if mbox is not None else None
    if full is not None and full.text:
        info.output = full.text
    elif info.error and len(els) > 1:
        info.output = linear(els[1], MathInfo("", ""))  # error message shown by TI
    return info
