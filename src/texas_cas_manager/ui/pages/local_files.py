"""Local files page: organise .tns documents stored on this computer."""

from __future__ import annotations

import html

import shutil
from pathlib import Path

from PySide6.QtCore import QDir, QFile, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFileSystemModel, QHBoxLayout, QHeaderView,
                               QInputDialog, QLineEdit, QSplitter, QTextBrowser, QToolBar, QTreeView,
                               QVBoxLayout, QWidget)

from ...config import unique_path
from ...tns import inspect
from ...tns.extract import export_resources
from ..widgets.common import Card, confirm, human_size, icon, label
from ..workers import run_task


def report_html(path: Path, rep) -> str:
    items = "".join(
        f"<li><b>{html.escape(e.name)}</b><br><span>{e.kind} · {e.method_name} · {human_size(e.stored_size)}"
        f" · {html.escape(e.status)}</span></li>" for e in rep.entries)
    problems = "".join(f"<li>{html.escape(p)}</li>" for p in rep.problems) or "<li>Ninguno</li>"
    return (f"<h3>{html.escape(path.name)}</h3><p>Formato <b>*TIMLP{rep.version}</b> · {human_size(rep.size)} · "
            f"{len(rep.entries)} componentes</p><p>{html.escape(rep.lua_status)}</p>"
            f"<p><b>Componentes</b></p><ul>{items}</ul>"
            f"<p>Reescritura idéntica del contenedor: <b>{'sí' if rep.roundtrip_identical else 'no'}</b></p>"
            f"<p><b>Problemas</b></p><ul>{problems}</ul>")


class LocalFilesPage(QWidget):
    open_document = Signal(str)
    message = Signal(str, str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.settings = settings
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 18)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label("Archivos locales", "title"))
        head.addStretch()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrar por nombre…")
        self.filter.setClearButtonEnabled(True)
        self.filter.setMaximumWidth(260)
        self.filter.textChanged.connect(self._apply_filter)
        head.addWidget(self.filter)
        root.addLayout(head)

        tb = QToolBar()
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.addAction(icon("open"), "Abrir en editor", self._open)
        tb.addAction(icon("copy"), "Duplicar", self._duplicate)
        tb.addAction(icon("rename"), "Renombrar", self._rename)
        tb.addAction(icon("folder-new"), "Carpeta", self._mkdir)
        tb.addAction(icon("import"), "Importar…", self._import)
        tb.addAction(icon("export"), "Exportar recursos", self._export)
        tb.addAction(icon("delete"), "A la papelera", self._trash)
        tb.addAction(icon("folder"), "Abrir carpeta", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.root)))
        root.addWidget(tb)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)
        files = Card()
        self.fs = QFileSystemModel(self)
        self.fs.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)
        self.fs.setNameFilters(["*.tns", "*.lua"])
        self.fs.setNameFilterDisables(False)
        self.fs.setReadOnly(True)
        self.view = QTreeView()
        self.view.setModel(self.fs)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(0, Qt.AscendingOrder)
        self.view.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.view.hideColumn(2)
        self.view.doubleClicked.connect(lambda i: self._open())
        self.view.selectionModel().currentChanged.connect(self._show_info)
        files.body.addWidget(self.view)
        split.addWidget(files)
        info = Card("Información")
        self.info = QTextBrowser()
        self.info.setOpenLinks(False)
        info.body.addWidget(self.info)
        split.addWidget(info)
        split.setSizes([620, 420])
        self.set_root(settings.workspace)

    @property
    def root(self) -> str:
        return self.fs.rootPath()

    def set_root(self, folder: str) -> None:
        Path(folder).mkdir(parents=True, exist_ok=True)
        self.fs.setRootPath(folder)
        self.view.setRootIndex(self.fs.index(folder))

    def _apply_filter(self, text: str) -> None:
        text = text.strip()
        self.fs.setNameFilters([f"*{text}*.tns", f"*{text}*.lua"] if text else ["*.tns", "*.lua"])

    def _selected(self) -> list[Path]:
        return [Path(self.fs.filePath(i)) for i in self.view.selectionModel().selectedRows(0)]

    def _current_dir(self) -> Path:
        sel = self._selected()
        if sel:
            return sel[0] if sel[0].is_dir() else sel[0].parent
        return Path(self.root)

    def _show_info(self, idx) -> None:
        path = Path(self.fs.filePath(idx))
        if not path.is_file() or path.suffix.lower() != ".tns":
            self.info.setHtml(f"<h3>{path.name}</h3><p>{human_size(path.stat().st_size) if path.is_file() else 'Carpeta'}</p>")
            return
        self.info.setHtml("<p>Analizando…</p>")

        def done(rep):
            if self.view.currentIndex() == idx:
                self.info.setHtml(report_html(path, rep))

        run_task(lambda p: inspect.analyze(path.read_bytes()), done,
                 lambda err: self.info.setHtml(f"<h3>{path.name}</h3><p>No es un documento válido: {err}</p>"))

    def _open(self) -> None:
        for p in self._selected():
            if p.is_file():
                self.open_document.emit(str(p))

    def _duplicate(self) -> None:
        for p in self._selected():
            if p.is_file():
                target = unique_path(p.with_name(f"{p.stem} copia{p.suffix}"))
                shutil.copy2(p, target)
                self.message.emit("ok", f"Copia creada: {target.name}")

    def _rename(self) -> None:
        sel = [p for p in self._selected() if p.exists()]
        if len(sel) != 1:
            return
        p = sel[0]
        name, ok = QInputDialog.getText(self, "Renombrar", "Nuevo nombre:", text=p.name)
        name = name.strip()
        if not ok or not name or name == p.name:
            return
        if "/" in name:
            self.message.emit("error", "El nombre no puede contener «/».")
            return
        target = p.with_name(name)
        if target.exists():
            self.message.emit("error", f"Ya existe {name}.")
            return
        p.rename(target)

    def _mkdir(self) -> None:
        name, ok = QInputDialog.getText(self, "Nueva carpeta", "Nombre:")
        name = name.strip()
        if ok and name and "/" not in name:
            unique_path(self._current_dir() / name).mkdir()

    def _import(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Importar documentos", str(Path.home()),
                                                "Documentos TI-Nspire o Lua (*.tns *.lua)")
        for f in files:
            target = unique_path(self._current_dir() / Path(f).name)
            shutil.copy2(f, target)
        if files:
            self.message.emit("ok", f"{len(files)} archivos importados")

    def _export(self) -> None:
        for p in self._selected():
            if p.suffix.lower() != ".tns":
                continue
            out = unique_path(p.with_name(f"{p.stem} recursos"))
            try:
                written = export_resources(p, out)
            except (ValueError, OSError) as exc:
                self.message.emit("error", f"{p.name}: {exc}")
                continue
            self.message.emit("ok", f"{len(written)} recursos exportados a {out.name}")

    def _trash(self) -> None:
        sel = [p for p in self._selected() if p.exists()]
        if not sel or not confirm(self, "Mover a la papelera",
                                  "Se moverán a la papelera:\n" + "\n".join(p.name for p in sel)):
            return
        for p in sel:
            if not QFile.moveToTrash(str(p)):
                self.message.emit("error", f"No se pudo mover a la papelera: {p.name}")
