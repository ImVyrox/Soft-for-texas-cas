"""Editor page: tabs of documents, internal explorer, viewers, rebuild and compare.

Workflow (the original file is never written): open -> analyse -> edit scripts
-> rebuild + validate -> save as a new file.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QPlainTextEdit,
                               QScrollArea, QSplitter, QStackedWidget, QTabWidget, QTextBrowser, QToolBar,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ...config import atomic_write, unique_path
from ...editor import lua_tools
from ...tns import container, images, inspect
from ...tns.edit import RebuildError, compare_documents, rebuild, text_diff
from ...tns.extract import export_resources
from ..widgets.code_editor import CodeEditor
from ..widgets.common import Card, confirm, human_size, icon, label
from ..widgets.find_bar import FindBar
from ..workers import run_task

NEW_SCRIPT = """-- Nuevo script Lua para TI-Nspire (OS 3.0.2 o posterior)
function on.paint(gc)
  gc:drawString("Hola, TI-Nspire", 10, 10)
end
"""
ROLE = Qt.UserRole  # ("script", key) | ("xml", name) | ("resource", name) | ("entry", name)


def _xml_for_display(xml: bytes) -> str:
    """One element per line for reading and diffs; the stored XML is never changed."""
    return xml.decode("utf-8", errors="replace").replace("><", ">\n<")


def report_html(path_name: str, rep) -> str:
    """Summary panel (also used by the local files page)."""
    items = "".join(
        f"<li><b>{html.escape(e.name)}</b><br><span>{e.kind} · {e.method_name} · {human_size(e.stored_size)}"
        f" · {html.escape(e.status)}</span></li>" for e in rep.entries)
    problems = "".join(f"<li>{html.escape(p)}</li>" for p in rep.problems) or "<li>Ninguno</li>"
    sw = rep.properties.get("properties.swver", "").strip()
    return (f"<h3>{html.escape(path_name)}</h3>"
            f"<p><b>{rep.interpretation.capitalize()}</b><br>Formato *TIMLP{rep.version} · {human_size(rep.size)}"
            f"<br>Origen: {html.escape(rep.origin)}" + (f"<br>Creado con: {html.escape(sw)}" if sw else "") +
            f"<br>Contenido: {html.escape(rep.kind)}</p>"
            f"<p>{len(rep.entries)} secciones · {rep.xml_blocks} XML · {rep.encrypted_blocks} cifradas · "
            f"{len(rep.resources)} recursos · {len(rep.scripts)} scripts</p>"
            f"<p>{html.escape(rep.lua_status)}</p><p><b>Componentes</b></p><ul>{items}</ul>"
            f"<p>Reescritura idéntica del contenedor: <b>{'sí' if rep.roundtrip_identical else 'no'}</b></p>"
            f"<p><b>Problemas</b></p><ul>{problems}</ul>")


class CompareDialog(QDialog):
    def __init__(self, parent, title: str, comparison, diffs: list[tuple[str, str]]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 640)
        lay = QVBoxLayout(self)
        rows = "".join(f"<li><b>{html.escape(c.name)}</b>: {c.status}</li>" for c in comparison.components)
        top = QTextBrowser()
        top.setHtml(f"<p>Resultado: <b>{comparison.level}</b></p><p>SHA-256 A: <code>{comparison.sha256[0]}</code>"
                    f"<br>SHA-256 B: <code>{comparison.sha256[1]}</code></p><ul>{rows}</ul>")
        top.setMaximumHeight(200)
        lay.addWidget(top)
        tabs = QTabWidget()
        for name, diff in diffs or [("Diferencias", "Sin diferencias de texto.")]:
            view = QPlainTextEdit(diff or "Sin diferencias.")
            view.setReadOnly(True)
            f = view.font()
            f.setFamily("monospace")
            view.setFont(f)
            tabs.addTab(view, name)
        lay.addWidget(tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class DocumentTab(QWidget):
    """One open document: explorer, viewers, properties, edit state."""

    changed = Signal()
    message = Signal(str, str)
    loaded = Signal(str)

    def __init__(self, theme_name: str, parent=None):
        super().__init__(parent)
        self.path: Path | None = None
        self.original: bytes | None = None  # bytes of the opened file, never modified
        self.report = None
        self.doc = None
        self.originals: dict[tuple[str, int], str] = {}  # script key -> source as opened
        self.edits: dict[tuple[str, int], str] = {}
        self.protected: set[tuple[str, int]] = set()
        self.current: tuple[str, int] | None = None
        self.last_saved: Path | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split)

        left = Card("Explorador")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._select)
        left.body.addWidget(self.tree)
        split.addWidget(left)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.code = CodeEditor(theme=theme_name)
        self.code.textChanged.connect(self._code_changed)
        self.xml_view = CodeEditor(theme=theme_name, lua=False)
        self.xml_view.setReadOnly(True)
        self.info = QTextBrowser()
        self.image = QLabel(alignment=Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.image)
        scroll.setWidgetResizable(True)
        for w in (self.code, self.xml_view, self.info, scroll):
            self.stack.addWidget(w)
        self.image_page = scroll
        self.find_bar = FindBar()
        cl.addWidget(self.stack, 1)
        cl.addWidget(self.find_bar)
        split.addWidget(center)

        right = Card("Propiedades")
        self.props = QTextBrowser()
        right.body.addWidget(self.props)
        split.addWidget(right)
        split.setSizes([240, 640, 330])
        self._show_info("<h3>Cargando…</h3>")

    # -- state ------------------------------------------------------------------

    @property
    def title(self) -> str:
        name = self.path.name if self.path else "Nuevo documento Lua"
        return name + (" *" if self.dirty else "")

    @property
    def editable(self) -> bool:
        return bool(set(self.originals) - self.protected)

    @property
    def dirty(self) -> bool:
        return any(self.edits.get(k, v) != v for k, v in self.originals.items())

    @property
    def is_new(self) -> bool:
        return self.original is None and bool(self.originals)

    def _code_changed(self) -> None:
        if self.current is not None and self.current not in self.protected:
            self.edits[self.current] = self.code.toPlainText()
            self.changed.emit()

    def _show_info(self, html_text: str) -> None:
        self.info.setHtml(html_text)
        self.stack.setCurrentWidget(self.info)

    # -- loading ------------------------------------------------------------------

    def load_new(self, script: str) -> None:
        key = ("Problem1.xml", 0)
        self.originals = {key: script}
        self.edits = {key: script}
        self.tree.clear()
        root = QTreeWidgetItem(["Scripts"])
        it = QTreeWidgetItem(["Script Lua (nuevo)"])
        it.setIcon(0, icon("editor"))
        it.setData(0, ROLE, ("script", key))
        root.addChild(it)
        self.tree.addTopLevelItem(root)
        root.setExpanded(True)
        self.props.setHtml("<h3>Nuevo documento Lua</h3><p>Se genera con la misma estructura que Luna 2.1 "
                           "(Document.xml + Problem1.xml), idéntica byte a byte. Requiere OS 3.0.2 o posterior.</p>")
        self.tree.setCurrentItem(it)

    def load_file(self, path: Path) -> None:
        self.path = Path(path)

        def failed(err):
            self._show_info(f"<h3>{html.escape(self.path.name)}</h3><p>No es un documento .tns legible: "
                            f"{html.escape(err)}</p>")
            self.message.emit("error", f"No se pudo abrir {self.path.name}: {err}")

        run_task(lambda p: (lambda d: (d, inspect.analyze(d)))(self.path.read_bytes()), self._loaded, failed)

    def _loaded(self, result) -> None:
        self.original, self.report = result
        self.doc = container.parse(self.original)
        rep = self.report
        self.originals = {(s.problem, s.index): s.source for s in rep.scripts}
        self.edits = dict(self.originals)
        self.protected = {(s.problem, s.index) for s in rep.scripts if s.protected}
        self._fill_tree()
        self.props.setHtml(report_html(self.path.name, rep))
        self.loaded.emit(str(self.path))
        self.changed.emit()

    def _fill_tree(self) -> None:
        rep = self.report
        self.tree.clear()

        def section(title: str, children: list[QTreeWidgetItem], empty: str) -> None:
            root = QTreeWidgetItem([f"{title} ({len(children)})"])
            if children:
                root.addChildren(children)
            else:
                hint = QTreeWidgetItem([empty])
                hint.setFlags(Qt.NoItemFlags)
                root.addChild(hint)
            self.tree.addTopLevelItem(root)
            root.setExpanded(True)

        scripts = []
        for s in rep.scripts:
            it = QTreeWidgetItem([(s.title or f"Script {s.index + 1}") + f" — {s.problem}"
                                  + (" (protegido)" if s.protected else "")])
            it.setIcon(0, icon("editor"))
            it.setData(0, ROLE, ("script", (s.problem, s.index)))
            scripts.append(it)
        section("Scripts", scripts, "Sin scripts Lua")

        xmls, resources, entries = [], [], []
        for e in rep.entries:
            it = QTreeWidgetItem([e.name])
            it.setIcon(0, icon("file"))
            it.setToolTip(0, f"{e.kind} · {e.method_name} · {e.status}")
            if not e.readable:
                it.setForeground(0, self.palette().placeholderText())
            it.setData(0, ROLE, ("xml" if e.kind == "XML" else "resource", e.name))
            (xmls if e.kind == "XML" else resources).append(it)
            bin_item = QTreeWidgetItem([e.name])
            bin_item.setData(0, ROLE, ("entry", e.name))
            entries.append(bin_item)
        section("XML", xmls, "Sin XML")
        section("Recursos", resources, "Sin recursos")
        section("Secciones binarias", entries, "—")
        first = scripts[0] if scripts else (xmls[0] if xmls else None)
        if first:
            self.tree.setCurrentItem(first)
        else:
            self._show_info(report_html(self.path.name, rep))

    # -- explorer selection --------------------------------------------------------

    def _entry_props(self, name: str) -> str:
        e = next(x for x in self.report.entries if x.name == name)
        rows = [("Tipo", e.kind), ("Codificación", e.method_name), ("Almacenado", f"{e.stored_size} B"),
                ("Tamaño declarado", f"{e.declared_size} B"), ("Estado", e.status)]
        if e.encrypted:
            rows += [("Cabecera TIEN", e.header or "—"),
                     ("Semilla del contador", f"0x{e.seed:08X}" if e.seed is not None else "—"),
                     ("XML decodificado", f"{e.xml_size} B" if e.xml_size is not None else "—"),
                     ("Metadatos del directorio", {"final": "CRC/tamaño del XML (convención de TI)",
                                                    "legacy": "CRC/tamaño de los bytes guardados (Luna)",
                                                    "mismatch": "no coinciden"}.get(e.metadata, e.metadata))]
        return (f"<h3>{html.escape(name)}</h3><table cellpadding=3>" +
                "".join(f"<tr><td><b>{k}</b></td><td>{html.escape(str(v))}</td></tr>" for k, v in rows) +
                f"<tr><td><b>SHA-256</b></td><td><code>{e.sha256}</code></td></tr></table>")

    def _select(self, item, _prev=None) -> None:
        if item is None or item.data(0, ROLE) is None:
            return
        kind, key = item.data(0, ROLE)
        if kind == "script":
            self.current = None  # the swap below is not an edit
            self.code.setPlainText(self.edits.get(key, self.originals[key]))
            self.current = key
            locked = key in self.protected
            self.code.setReadOnly(locked)
            self.stack.setCurrentWidget(self.code)
            self.find_bar.attach(self.code, with_replace=not locked)
            if self.report:
                self.props.setHtml(self._entry_props(key[0]) + (
                    "<p><b>Script protegido por TI (sc:cry): solo lectura.</b></p>" if locked else ""))
            return
        self.current = None
        if self.report is None:
            return
        self.props.setHtml(self._entry_props(key))
        entry = self.doc.entry(key)
        rep = next(x for x in self.report.entries if x.name == key)
        if kind == "entry":
            self._show_info(self._entry_props(key) + "<p>Primeros bytes almacenados:</p><pre>" +
                            html.escape(" ".join(f"{b:02X}" for b in entry.raw[:96])) + "</pre>")
            return
        if not rep.readable:
            self._show_info(f"<h3>{html.escape(key)}</h3><p><b>No interpretable</b>: {html.escape(rep.status)}.</p>"
                            "<p>Se conserva sin cambios al reconstruir el documento.</p>")
            return
        content = inspect.entry_content(self.doc, key)
        if kind == "xml":
            self.xml_view.setPlainText(_xml_for_display(content))
            self.stack.setCurrentWidget(self.xml_view)
            self.find_bar.attach(self.xml_view, with_replace=False)
            return
        pix = QPixmap()
        if rep.kind == "Imagen" and not pix.loadFromData(content):
            try:
                w, h, rgb = images.decode_bmp16(content)
                pix = QPixmap.fromImage(QImage(rgb, w, h, w * 3, QImage.Format_RGB888).copy())
            except images.UnsupportedImage as exc:
                self._show_info(f"<h3>{html.escape(key)}</h3><p>Imagen que no se puede mostrar: "
                                f"{html.escape(str(exc))}. Se puede extraer.</p>")
                return
        if rep.kind == "Imagen" and not pix.isNull():
            self.image.setPixmap(pix)
            self.stack.setCurrentWidget(self.image_page)
            self.props.setHtml(self._entry_props(key) + f"<p>Imagen {pix.width()}×{pix.height()} px</p>")
            return
        self._show_info(f"<h3>{html.escape(key)}</h3><p>Recurso de {human_size(len(content))}; "
                        "no hay visor para este tipo. Se puede extraer.</p>")

    # -- build ---------------------------------------------------------------------

    def build(self) -> bytes:
        """Rebuilt document with every edited script (raises RebuildError/ValueError). Thread-safe."""
        if self.is_new:
            return rebuild(None, self.edits[("Problem1.xml", 0)])
        data = self.original
        for (problem, index), source in sorted(self.edits.items()):
            if source != self.originals.get((problem, index)):
                data = rebuild(data, source, problem, index)
        return data


class EditorPage(QWidget):
    message = Signal(str, str)
    opened = Signal(str)
    send_to_calculator = Signal(str)

    def __init__(self, settings, theme_name: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.settings = settings
        self.theme_name = theme_name
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 18)
        root.setSpacing(10)
        root.addWidget(label("Editor .tns", "title"))

        tb = QToolBar()
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.addAction(icon("new"), "Nuevo Lua", self.new_document)
        tb.addAction(icon("open"), "Abrir…", self.choose_file)
        tb.addAction(icon("import"), "Importar .lua…", self.import_lua)
        tb.addSeparator()
        self.act_save = tb.addAction(icon("save"), "Guardar como…", self.save_new_version)
        self.act_extract = tb.addAction(icon("export"), "Extraer…", self.extract)
        self.act_rebuild = tb.addAction(icon("build"), "Reconstruir", self.rebuild_and_report)
        self.act_validate = tb.addAction(icon("check"), "Validar", self.validate)
        cmp_btn = QToolButton()
        cmp_btn.setText("Comparar")
        cmp_btn.setIcon(icon("diff"))
        cmp_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        cmp_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(cmp_btn)
        self.act_cmp_orig = menu.addAction("Con el original (cambios sin guardar)", self.compare_with_original)
        self.act_cmp_file = menu.addAction("Con otro documento .tns…", self.compare_with_file)
        cmp_btn.setMenu(menu)
        self.cmp_btn = cmp_btn
        tb.addWidget(cmp_btn)
        self.act_send = tb.addAction(icon("upload"), "Enviar a la calculadora", self._send)
        root.addWidget(tb)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(lambda _: self._update_actions())
        self.placeholder = QTextBrowser()
        self.placeholder.setHtml("<h3>Ningún documento abierto</h3><p>Abre un .tns o crea un documento Lua. "
                                 "El archivo original nunca se modifica: los cambios se reconstruyen, se validan "
                                 "y se guardan siempre como un archivo nuevo.</p>")
        self.body = QStackedWidget()
        self.body.addWidget(self.placeholder)
        self.body.addWidget(self.tabs)
        root.addWidget(self.body, 1)

        QShortcut(QKeySequence.Save, self, self.save_new_version)
        QShortcut(QKeySequence.Find, self, lambda: self.tab and self.tab.find_bar.open())
        QShortcut(QKeySequence("Ctrl+H"), self, lambda: self.tab and self.tab.find_bar.open(replace=True))
        self.luac = lua_tools.find_luac()
        self._update_actions()

    # -- used by the main window and tests ------------------------------------------

    @property
    def tab(self) -> DocumentTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocumentTab) else None

    @property
    def editable(self) -> bool:
        return bool(self.tab and self.tab.editable)

    @property
    def code(self) -> CodeEditor | None:
        return self.tab.code if self.tab else None

    @property
    def dirty(self) -> bool:
        return any(self.tabs.widget(i).dirty for i in range(self.tabs.count()))

    def set_theme(self, name: str) -> None:
        self.theme_name = name
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            t.code.set_theme(name)
            t.xml_view.set_theme(name)

    def _confirm_discard(self) -> bool:
        return not self.dirty or confirm(self, "Cambios sin guardar",
                                         "Hay documentos con cambios sin guardar. ¿Descartarlos?")

    def discard_changes(self) -> None:
        """Forget unsaved edits (used when closing without prompting)."""
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            t.edits = dict(t.originals)

    def _rebuild(self) -> bytes | None:
        try:
            return self.tab.build()
        except (RebuildError, ValueError) as exc:
            self.message.emit("error", f"No se puede reconstruir el documento: {exc}")
            return None

    # -- tabs ---------------------------------------------------------------------

    def _add_tab(self, tab: DocumentTab) -> None:
        tab.changed.connect(lambda t=tab: self._retitle(t))
        tab.message.connect(self.message)
        tab.loaded.connect(self.opened)
        self.tabs.addTab(tab, tab.title)
        self.tabs.setCurrentWidget(tab)
        self.body.setCurrentWidget(self.tabs)
        self._update_actions()

    def _retitle(self, tab: DocumentTab) -> None:
        i = self.tabs.indexOf(tab)
        if i >= 0:
            self.tabs.setTabText(i, tab.title)
        self._update_actions()

    def close_tab(self, index: int) -> None:
        tab = self.tabs.widget(index)
        if tab.dirty and not confirm(self, "Cambios sin guardar",
                                     f"«{tab.title}» tiene cambios sin guardar. ¿Cerrar y descartarlos?"):
            return
        self.tabs.removeTab(index)
        tab.deleteLater()
        if not self.tabs.count():
            self.body.setCurrentWidget(self.placeholder)
        self._update_actions()

    def _update_actions(self) -> None:
        t = self.tab
        saved = t is not None and t.original is not None
        rules = {
            self.act_save: (t is not None and (t.dirty or t.is_new),
                            "Haz cambios en un script editable para guardar una versión nueva"),
            self.act_rebuild: (t is not None and t.editable, "El documento no tiene scripts editables"),
            self.act_validate: (t is not None and t.editable, "El documento no tiene scripts editables"),
            self.act_extract: (saved, "Abre un documento .tns guardado"),
            self.act_cmp_orig: (saved and t.dirty, "No hay cambios respecto al original"),
            self.act_cmp_file: (saved, "Abre un documento .tns guardado"),
            self.act_send: (t is not None and (t.last_saved or t.path) is not None,
                            "Guarda el documento antes de enviarlo"),
        }
        for act, (enabled, why) in rules.items():
            act.setEnabled(bool(enabled))
            act.setToolTip("" if enabled else why)
        self.cmp_btn.setEnabled(bool(saved))
        self.cmp_btn.setToolTip("" if saved else "Abre un documento .tns guardado")

    # -- open / new ------------------------------------------------------------------

    def new_document(self, script: str = NEW_SCRIPT) -> None:
        tab = DocumentTab(self.theme_name)
        tab.load_new(script)
        self._add_tab(tab)

    def choose_file(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Abrir documentos", self.settings.workspace,
                                                "Documentos TI-Nspire (*.tns);;Scripts Lua (*.lua)")
        for f in files:
            self.open_file(f)

    def import_lua(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Importar script Lua", self.settings.workspace, "Lua (*.lua)")
        if f:
            self.open_file(f)

    def open_file(self, file: str) -> None:
        path = Path(file)
        if path.suffix.lower() == ".lua":
            try:
                self.new_document(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                self.message.emit("error", f"No se pudo leer {path.name}: {exc}")
            return
        for i in range(self.tabs.count()):  # already open: show it
            t = self.tabs.widget(i)
            if t.path and t.path.resolve() == path.resolve():
                self.tabs.setCurrentIndex(i)
                return
        tab = DocumentTab(self.theme_name)
        self._add_tab(tab)
        tab.load_file(path)

    # -- actions -------------------------------------------------------------------

    def _build_async(self, on_done) -> None:
        tab = self.tab
        run_task(lambda p: tab.build(), on_done,
                 lambda err: self.message.emit("error", f"No se puede reconstruir el documento: {err}"))

    def validate(self) -> None:
        tab = self.tab
        source = tab.code.toPlainText() if tab.current else None

        def work(p):
            syntax = lua_tools.check_syntax(source, self.luac) if source is not None else None
            return syntax, tab.build()

        def done(result):
            syntax, data = result
            parts = []
            if syntax is not None:
                if syntax.available and not syntax.ok:
                    tab.code.set_error_line(syntax.line)
                    self.message.emit("error", f"Error de sintaxis Lua (línea {syntax.line}): {syntax.message}")
                    return
                parts.append(syntax.message)
            parts.append(f"documento reconstruido válido ({human_size(len(data))})")
            self.message.emit("ok", "; ".join(parts) + ".")

        run_task(work, done, lambda err: self.message.emit("error", f"Validación fallida: {err}"))

    def rebuild_and_report(self) -> None:
        tab = self.tab

        def done(data):
            if tab.is_new:
                self.message.emit("ok", f"Documento nuevo válido ({human_size(len(data))}).")
                return
            cmp = compare_documents(tab.original, data)
            changed = [c.name for c in cmp.components if c.status != "igual"]
            self.message.emit("ok", f"Reconstrucción válida: {cmp.level}. Cambiado: "
                                    f"{', '.join(changed) or 'nada'}; el resto se conserva byte a byte.")

        self._build_async(done)

    @staticmethod
    def _diffs(a: bytes, b: bytes, tab: DocumentTab | None) -> list[tuple[str, str]]:
        diffs = []
        if tab is not None:
            for key, old in tab.originals.items():
                new = tab.edits.get(key, old)
                if new != old:
                    diffs.append((f"Script {key[0]} #{key[1] + 1}", text_diff(old, new)))
        da, db = container.parse(a), container.parse(b)
        names_b = {e.name for e in db.entries}
        for e in da.entries:
            if e.name.lower().endswith(".xml") and e.name in names_b:
                try:
                    xa = _xml_for_display(inspect.entry_content(da, e.name))
                    xb = _xml_for_display(inspect.entry_content(db, e.name))
                except ValueError:
                    continue
                if xa != xb:
                    diffs.append((f"XML {e.name}", text_diff(xa, xb, "A", "B")))
        return diffs

    def compare_with_original(self) -> None:
        tab = self.tab

        def done(data):
            CompareDialog(self, "Original frente a versión editada", compare_documents(tab.original, data),
                          self._diffs(tab.original, data, tab)).exec()

        self._build_async(done)

    def compare_with_file(self) -> None:
        tab = self.tab
        f, _ = QFileDialog.getOpenFileName(self, "Comparar con…", str(tab.path.parent), "Documentos TI-Nspire (*.tns)")
        if not f:
            return
        a = tab.original

        def work(p):
            b = Path(f).read_bytes()
            return compare_documents(a, b), self._diffs(a, b, None)

        run_task(work, lambda r: CompareDialog(self, f"{tab.path.name} frente a {Path(f).name}", *r).exec(),
                 lambda err: self.message.emit("error", f"No se pudo comparar: {err}"))

    def extract(self) -> None:
        tab = self.tab
        base = QFileDialog.getExistingDirectory(self, "Carpeta donde extraer", str(tab.path.parent))
        if not base:
            return
        out = unique_path(Path(base) / f"{tab.path.stem} (extraído)")
        run_task(lambda p: export_resources(tab.path, out),
                 lambda written: self.message.emit("ok", f"{len(written)} archivos extraídos en {out}"),
                 lambda err: self.message.emit("error", f"No se pudo extraer: {err}"))

    def save_new_version(self) -> None:
        tab = self.tab
        if tab is None or not (tab.dirty or tab.is_new):
            return

        def done(data):
            base = tab.path or Path(self.settings.workspace) / "nuevo.tns"
            suggestion = unique_path(base.with_name(f"{base.stem} (editado).tns") if tab.path else base)
            f, _ = QFileDialog.getSaveFileName(self, "Guardar como documento nuevo", str(suggestion),
                                               "Documentos TI-Nspire (*.tns)")
            if f:
                self.write_version(tab, data, Path(f if f.lower().endswith(".tns") else f + ".tns"))

        self._build_async(done)

    def write_version(self, tab: DocumentTab, data: bytes, target: Path) -> bool:
        """Write a rebuilt document; refuses the original path."""
        if tab.path and target.resolve() == tab.path.resolve():
            self.message.emit("error", "Por seguridad no se sobrescribe el documento original. Elige otro nombre.")
            return False
        try:
            # The save dialog already asked before replacing another existing file.
            atomic_write(target, data, overwrite=target.exists())
        except OSError as exc:
            self.message.emit("error", f"No se pudo guardar: {exc}")
            return False
        tab.last_saved = target
        self.message.emit("ok", f"Guardado {target.name} (el original no se ha modificado)")
        self._update_actions()
        return True

    def _send(self) -> None:
        tab = self.tab
        target = tab.last_saved or tab.path
        if tab.dirty and not confirm(self, "Enviar", "Hay cambios sin guardar; se enviará la última versión "
                                                     f"guardada ({target.name}). ¿Continuar?"):
            return
        self.send_to_calculator.emit(str(target))
