"""Editing workflow: rebuild a document with a new script, verify, compare."""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from . import container
from .inspect import validate_bytes
from .lua import build_lua_document, read_script, replace_script


class RebuildError(ValueError):
    """The rebuilt document failed validation; nothing should be written."""


def rebuild(original: bytes | None, script: str) -> bytes:
    """New document bytes holding ``script``.

    ``original=None`` creates a new Lua document. Otherwise only Problem1.xml
    changes; every other component is copied byte for byte. The result is
    re-parsed, validated and its script read back before it is returned.
    """
    if original is None:
        data = build_lua_document(script)
    else:
        data = container.write(replace_script(container.parse(original), script))
    problems = validate_bytes(data)
    if problems:
        raise RebuildError("; ".join(problems))
    if read_script(container.parse(data)) != script.removeprefix("﻿"):
        raise RebuildError("el script leído del documento reconstruido no coincide")
    if original is not None:
        changed = {c.name for c in compare_components(original, data) if c.status != "igual"}
        if changed - {"Problem1.xml"}:
            raise RebuildError("se modificaron componentes que no debían cambiar: " + ", ".join(sorted(changed)))
    return data


@dataclass(frozen=True)
class ComponentChange:
    name: str
    status: str  # igual | modificado | añadido | eliminado


def compare_components(a: bytes, b: bytes) -> list[ComponentChange]:
    """Component-level comparison of two documents (raw stored bytes)."""
    da, db = container.parse(a), container.parse(b)
    ea = {e.name: e for e in da.entries}
    eb = {e.name: e for e in db.entries}
    out = []
    for name in list(ea) + [n for n in eb if n not in ea]:
        if name not in eb:
            out.append(ComponentChange(name, "eliminado"))
        elif name not in ea:
            out.append(ComponentChange(name, "añadido"))
        else:
            same = ea[name].raw == eb[name].raw and ea[name].crc32 == eb[name].crc32
            out.append(ComponentChange(name, "igual" if same else "modificado"))
    return out


def text_diff(old: str, new: str, old_name: str = "original", new_name: str = "modificado") -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), old_name, new_name))
