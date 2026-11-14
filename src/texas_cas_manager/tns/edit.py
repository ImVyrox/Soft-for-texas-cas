"""Editing workflow: rebuild a document with a new script, verify, compare."""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass, field

from . import container, inspect, xmldoc
from .lua import build_lua_document, list_scripts, replace_script


class RebuildError(ValueError):
    """The rebuilt document failed validation; nothing should be written."""


def rebuild(original: bytes | None, script: str, problem: str = "Problem1.xml", index: int = 0) -> bytes:
    """New document bytes holding ``script``.

    ``original=None`` creates a new Lua document. Otherwise only ``problem``
    changes; every other component is copied byte for byte. The result is
    re-parsed and validated, its script is read back, and the comparison with
    the original must show exactly one changed component.
    """
    if original is None:
        data = build_lua_document(script)
    else:
        data = container.write(replace_script(container.parse(original), script, problem, index))
    problems = inspect.validate_bytes(data)
    if problems:
        raise RebuildError("; ".join(problems))
    rebuilt = [s for s in list_scripts(container.parse(data)) if s.problem == problem]
    if len(rebuilt) <= index or rebuilt[index].source != script.removeprefix("﻿"):
        raise RebuildError("el script leído del documento reconstruido no coincide")
    if original is not None:
        changed = {c.name for c in compare_components(original, data) if c.status != "igual"}
        if changed - {problem}:
            raise RebuildError("se modificaron componentes que no debían cambiar: " + ", ".join(sorted(changed)))
    return data


@dataclass(frozen=True)
class ComponentChange:
    name: str
    status: str  # igual | contenido igual | modificado | añadido | eliminado | no verificable


def _content(entry) -> bytes | None:
    try:
        return xmldoc.decode_entry(entry)[1] if entry.is_encrypted else entry.payload()
    except ValueError:
        return None


def compare_components(a: bytes, b: bytes) -> list[ComponentChange]:
    """Per component: identical stored bytes, same decoded content, different, or not verifiable."""
    da, db = container.parse(a), container.parse(b)
    ea = {e.name: e for e in da.entries}
    eb = {e.name: e for e in db.entries}
    out = []
    for name in list(ea) + [n for n in eb if n not in ea]:
        if name not in eb:
            out.append(ComponentChange(name, "eliminado"))
        elif name not in ea:
            out.append(ComponentChange(name, "añadido"))
        elif ea[name].raw == eb[name].raw and ea[name].crc32 == eb[name].crc32:
            out.append(ComponentChange(name, "igual"))
        else:
            ca, cb = _content(ea[name]), _content(eb[name])
            if ca is None or cb is None:
                out.append(ComponentChange(name, "no verificable"))
            else:
                out.append(ComponentChange(name, "contenido igual" if ca == cb else "modificado"))
    return out


@dataclass
class Comparison:
    """Equality levels between two documents (strongest that holds)."""

    byte_identical: bool
    structural: bool  # same components, order and compression methods; content equal
    content: bool  # every component decodes to the same content
    verifiable: bool  # every component could be decoded on both sides
    components: list[ComponentChange] = field(default_factory=list)
    sha256: tuple[str, str] = ("", "")

    @property
    def level(self) -> str:
        if self.byte_identical:
            return "igualdad byte a byte"
        if self.structural:
            return "igualdad estructural"
        if self.content:
            return "igualdad de contenido"
        if not self.verifiable:
            return "reconstrucción no verificable"
        return "documentos distintos"


def compare_documents(a: bytes, b: bytes) -> Comparison:
    components = compare_components(a, b)
    da, db = container.parse(a), container.parse(b)
    same_layout = ([(e.name, e.method) for e in da.entries] == [(e.name, e.method) for e in db.entries]
                   and da.version == db.version)
    verifiable = all(c.status != "no verificable" for c in components)
    content = verifiable and all(c.status in ("igual", "contenido igual") for c in components)
    return Comparison(a == b, same_layout and content, content, verifiable, components,
                      (hashlib.sha256(a).hexdigest(), hashlib.sha256(b).hexdigest()))


def text_diff(old: str, new: str, old_name: str = "original", new_name: str = "modificado") -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), old_name, new_name))
