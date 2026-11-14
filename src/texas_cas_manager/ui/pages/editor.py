"""Editor page: inspect a .tns, edit its Lua script, rebuild and compare."""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QScrollArea, QSplitter, QStackedWidget, QTextBrowser, QToolBar, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ...config import atomic_write, unique_path
from ...tns import container, inspect
from ...tns.edit import RebuildError, compare_components, rebuild, text_diff
from ..widgets.code_editor import CodeEditor
from ..widgets.common import Card, confirm, human_size, icon, label
from ..workers import run_task
from .local_files import report_html

NEW_SCRIPT = """-- Nuevo script Lua para TI-Nspire (OS 3.0.2 o posterior)
function on.paint(gc)
  gc:drawString("Hola, TI-Nspire", 10, 10)
end
"""


class DiffDialog(QDialog):
    def __init__(self, parent, changes, diff: str):
        super().__init__(parent)
        self.setWindowTitle("Comparación con el original")
        self.resize(820, 600)
        lay = QVBoxLayout(self)
        rows = "".join(f"<li><b>{html.escape(c.name)}</b>: {c.status}</li>" for c in changes)
        top = QTextBrowser()
        top.setHtml(f"<p>Componentes:</p><ul>{rows}</ul>")
        top.setMaximumHeight(150)
        lay.addWidget(top)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(diff or "Sin cambios en el script.")
        f = view.font()
        f.setFamily("monospace")
        view.setFont(f)
        lay.addWidget(view, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class EditorPage(QWidget):
    message = Signal(str, str)
    opened = Signal(str)
    send_to_calculator = Signal(str)

    def __init__(self, settings, theme_name: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.settings = settings
        self.path: Path | None = None
        self.original: bytes | None = None  # bytes of the opened file, never modified
        self.original_script = ""
        self.editable = False
        self.last_saved: Path | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 18)
        root.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(label("Editor .tns", "title"))
        self.doc_title = label("", "muted")
        head.addWidget(self.doc_title)
        head.addStretch()
        root.addLayout(head)

        tb = QToolBar()
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.addAction(icon("new"), "Nuevo Lua", self.new_document)
        tb.addAction(icon("open"), "Abrir…", self.choose_file)
        tb.addAction(icon("import"), "Importar .lua…", self.import_lua)
        tb.addSeparator()
        self.act_validate = tb.addAction(icon("check"), "Validar", self.validate)
        self.act_diff = tb.addAction(icon("diff"), "Comparar", self.show_diff)
        self.act_save = tb.addAction(icon("save"), "Guardar como nueva versión…", self.save_new_version)
        self.act_send = tb.addAction(icon("upload"), "Enviar a la calculadora", self._send)
        root.addWidget(tb)
        QShortcut(QKeySequence.Save, self, self.save_new_version)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        res = Card("Componentes")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._select_component)
        res.body.addWidget(self.tree)
        split.addWidget(res)

        self.center = QStackedWidget()
        self.code = CodeEditor(theme=theme_name)
        self.code.textChanged.connect(self._update_actions)
        self.preview = QTextBrowser()
        self.image = QLabel(alignment=Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.image)
        scroll.setWidgetResizable(True)
        self.center.addWidget(self.code)
        self.center.addWidget(self.preview)
        self.center.addWidget(scroll)
        split.addWidget(self.center)

        info = Card("Documento")
        self.info = QTextBrowser()
        info.body.addWidget(self.info)
        split.addWidget(info)
        split.setSizes([220, 640, 340])
        self._show_placeholder()
        self._update_actions()

    # -- helpers -------------------------------------------------------------

    def set_theme(self, name: str) -> None:
        self.code.set_theme(name)

    @property
    def dirty(self) -> bool:
        return self.editable and self.code.toPlainText() != self.original_script

    def _show_placeholder(self) -> None:
        self.preview.setHtml("<h3>Ningún documento abierto</h3><p>Abre un archivo .tns o crea un nuevo "
                             "documento Lua. El archivo original nunca se modifica: los cambios se guardan "
                             "siempre como una versión nueva.</p>")
        self.center.setCurrentWidget(self.preview)
        self.info.setHtml("")

    def _update_actions(self) -> None:
        self.act_save.setEnabled(self.editable)
        self.act_validate.setEnabled(self.editable)
        self.act_diff.setEnabled(self.editable)
        self.act_send.setEnabled(self.last_saved is not None or self.path is not None)
        name = self.path.name if self.path else ("Nuevo documento" if self.editable else "")
        self.doc_title.setText(f"· {name}{' (modificado)' if self.dirty else ''}" if name else "")

    def _confirm_discard(self) -> bool:
        return not self.dirty or confirm(self, "Cambios sin guardar",
                                         "Hay cambios sin guardar en el script. ¿Descartarlos?")

    # -- open / new ------------------------------------------------------------

    def new_document(self, script: str = NEW_SCRIPT) -> None:
        if not self._confirm_discard():
            return
        self.path, self.original, self.last_saved = None, None, None
        self.original_script = script  # unchanged template/import is not "dirty"
        self.editable = True
        self.tree.clear()
        it = QTreeWidgetItem(["Script Lua"])
        it.setIcon(0, icon("editor"))
        it.setData(0, Qt.UserRole, "__script__")
        self.tree.addTopLevelItem(it)
        self.code.setPlainText(script)
        self.center.setCurrentWidget(self.code)
        self.info.setHtml("<h3>Nuevo documento Lua</h3><p>Se generará con la misma estructura que "
                          "Luna 2.1 (Document.xml + Problem1.xml). Requiere OS 3.0.2 o posterior.</p>")
        self.tree.setCurrentItem(it)
        self._update_actions()

    def choose_file(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Abrir documento", self.settings.workspace,
                                           "Documentos TI-Nspire (*.tns)")
        if f:
            self.open_file(f)

    def import_lua(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Importar script Lua", self.settings.workspace, "Lua (*.lua)")
        if f:
            try:
                text = Path(f).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self.message.emit("error", f"No se pudo leer {Path(f).name}: {exc}")
                return
            self.new_document(text)

    def open_file(self, file: str) -> None:
        if not self._confirm_discard():
            return
        path = Path(file)
        if path.suffix.lower() == ".lua":
            try:
                self.new_document(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                self.message.emit("error", f"No se pudo leer {path.name}: {exc}")
            return

        def load(p):
            data = path.read_bytes()
            return data, inspect.analyze(data)

        def done(result):
            data, rep = result
            self.path, self.original, self.last_saved = path, data, None
            self.report = rep
            self.doc = container.parse(data)
            self.editable = rep.lua_script is not None
            self.original_script = rep.lua_script or ""
            self._fill_tree(rep)
            self.code.setPlainText(self.original_script)
            self.info.setHtml(report_html(path, rep))
            self.opened.emit(str(path))
            self._update_actions()

        run_task(load, done, lambda err: self.message.emit("error", f"No se pudo abrir {path.name}: {err}"))

    def _fill_tree(self, rep) -> None:
        self.tree.clear()
        if rep.lua_script is not None:
            it = QTreeWidgetItem(["Script Lua (editable)"])
            it.setIcon(0, icon("editor"))
            it.setData(0, Qt.UserRole, "__script__")
            self.tree.addTopLevelItem(it)
        for e in rep.entries:
            it = QTreeWidgetItem([e.name])
            it.setIcon(0, icon("file"))
            it.setToolTip(0, f"{e.kind} · {e.method_name} · {human_size(e.stored_size)} · {e.status}")
            it.setData(0, Qt.UserRole, e.name)
            if not e.readable:
                it.setForeground(0, self.palette().placeholderText())
            self.tree.addTopLevelItem(it)
        self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _select_component(self, item, _prev=None) -> None:
        if item is None:
            return
        key = item.data(0, Qt.UserRole)
        if key == "__script__":
            self.center.setCurrentWidget(self.code)
            return
        rep = next(e for e in self.report.entries if e.name == key)
        head = (f"<h3>{html.escape(key)}</h3><p>{rep.kind} · {rep.method_name} · "
                f"{human_size(rep.stored_size)} almacenados · {human_size(rep.declared_size)} declarados</p>")
        if not rep.readable:
            self.preview.setHtml(head + f"<p><b>{rep.status}</b>. Este componente se conserva sin cambios "
                                        "al reconstruir el documento.</p>")
            self.center.setCurrentWidget(self.preview)
            return
        data = inspect.entry_content(self.doc, key)
        if rep.kind == "Imagen":
            pix = QPixmap()
            if pix.loadFromData(data):
                self.image.setPixmap(pix)
                self.center.setCurrentWidget(self.image)
                return
        text = data[:4000].decode("utf-8", errors="replace")
        self.preview.setHtml(head + "<p>Vista previa (solo lectura):</p><pre>" + html.escape(text) + "</pre>")
        self.center.setCurrentWidget(self.preview)

    # -- validate / diff / save ----------------------------------------------

    def _rebuild(self) -> bytes | None:
        try:
            return rebuild(self.original, self.code.toPlainText())
        except (RebuildError, ValueError) as exc:
            self.message.emit("error", f"No se puede reconstruir el documento: {exc}")
            return None

    def validate(self) -> None:
        data = self._rebuild()
        if data is not None:
            self.message.emit("ok", f"Documento válido ({human_size(len(data))}). Solo cambia Problem1.xml."
                              if self.original else f"Documento válido ({human_size(len(data))}).")

    def show_diff(self) -> None:
        data = self._rebuild()
        if data is None:
            return
        changes = compare_components(self.original, data) if self.original else []
        old = self.original_script if self.original else ""
        DiffDialog(self, changes, text_diff(old, self.code.toPlainText())).exec()

    def save_new_version(self) -> None:
        if not self.editable:
            return
        data = self._rebuild()
        if data is None:
            return
        base = self.path or Path(self.settings.workspace) / "nuevo.tns"
        suggestion = unique_path(base.with_name(f"{base.stem} (editado).tns") if self.path else base)
        f, _ = QFileDialog.getSaveFileName(self, "Guardar como nueva versión", str(suggestion),
                                           "Documentos TI-Nspire (*.tns)")
        if not f:
            return
        target = Path(f if f.lower().endswith(".tns") else f + ".tns")
        if self.path and target.resolve() == self.path.resolve():
            self.message.emit("error", "Por seguridad no se sobrescribe el documento original. Elige otro nombre.")
            return
        try:
            # The save dialog already asked before replacing another existing file.
            atomic_write(target, data, overwrite=target.exists())
        except OSError as exc:
            self.message.emit("error", f"No se pudo guardar: {exc}")
            return
        self.last_saved = target
        self.message.emit("ok", f"Guardado {target.name}")
        self._update_actions()

    def _send(self) -> None:
        target = self.last_saved or self.path
        if self.dirty and not confirm(self, "Enviar", "Hay cambios sin guardar; se enviará la última versión "
                                                      f"guardada ({target.name}). ¿Continuar?"):
            return
        self.send_to_calculator.emit(str(target))
