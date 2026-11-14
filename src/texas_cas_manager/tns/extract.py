"""Extraction of the readable components of a ``.tns`` document."""

from __future__ import annotations

from pathlib import Path

from . import container, inspect
from .lua import NotLuaDocumentError, read_script


def export_resources(tns_file: Path, out_dir: Path) -> list[Path]:
    """Write every readable entry of a document into ``out_dir`` (new folder)."""
    doc = container.parse(tns_file.read_bytes())
    out_dir.mkdir(parents=True, exist_ok=False)
    written = []
    for e in doc.entries:
        try:
            data = inspect.entry_content(doc, e.name)
        except ValueError:
            continue
        name = e.name + (".tixc" if e.is_encrypted else "")  # XML-compressed TI data
        target = out_dir / Path(name).name
        target.write_bytes(data)
        written.append(target)
    try:
        script = read_script(doc)
        target = out_dir / "script.lua"
        target.write_text(script, encoding="utf-8")
        written.append(target)
    except (NotLuaDocumentError, ValueError):
        pass
    return written
