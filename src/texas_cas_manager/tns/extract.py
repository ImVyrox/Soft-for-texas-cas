"""Extraction of the readable components of a ``.tns`` document.

Always writes into a new folder; the source file is only read.
"""

from __future__ import annotations

from pathlib import Path

from . import container, inspect, xmldoc
from .lua import problem_names


def _safe_name(name: str) -> str:
    return Path(name.replace("\\", "/")).name or "componente"


def export_resources(tns_file: Path, out_dir: Path) -> list[Path]:
    """Write decoded XML, scripts (.lua), plain resources and a report into ``out_dir`` (must not exist)."""
    data = Path(tns_file).read_bytes()
    doc = container.parse(data)
    out_dir.mkdir(parents=True, exist_ok=False)
    written: list[Path] = []
    for e in doc.entries:
        try:
            content = inspect.entry_content(doc, e.name)
        except ValueError:
            continue  # protected or corrupt: listed in the report, not exported
        target = out_dir / _safe_name(e.name)
        target.write_bytes(content)
        written.append(target)
    for name in problem_names(doc):
        try:
            _, xml = xmldoc.decode_entry(doc.entry(name))
            info = xmldoc.problem_info(name, xml)
        except ValueError:
            continue
        for s in info.scripts:
            suffix = "" if len(info.scripts) == 1 else f"_{s.index + 1}"
            target = out_dir / f"{Path(name).stem}{suffix}.lua"
            target.write_text(s.source, encoding="utf-8")
            written.append(target)
    report = out_dir / "informe.txt"
    report.write_text(inspect.text_report(Path(tns_file).name, inspect.analyze(data)) + "\n", encoding="utf-8")
    written.append(report)
    return written
