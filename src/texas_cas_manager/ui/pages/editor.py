"""Editor page: tabs of documents, internal explorer, viewers, rebuild and compare.

Workflow (the original file is never written): open -> analyse -> edit scripts
-> rebuild + validate -> save as a new file.
"""

from __future__ import annotations

import html
from pathlib import Path

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QLabel, QListWidget, QMenu, QPlainTextEdit, QScrollArea, QSplitter,
                               QStackedWidget, QTabWidget, QTextBrowser, QToolBar,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ...config import atomic_write, unique_path
from ...editor import lua_tools
from ...tns import container, images, inspect, notes, pages, xmldoc
from ...tns.edit import RebuildError, apply_edits, compare_documents, rebuild, text_diff
from ...tns.extract import export_resources
from ..widgets.code_editor import CodeEditor
from ..widgets.common import Card, confirm, human_size, icon, label
from ..widgets.find_bar import FindBar
from ..widgets.page_view import PageState, PageView
from ..workers import run_task

NEW_SCRIPT = """-- Nuevo script Lua para TI-Nspire (OS 3.0.2 o posterior)
function on.paint(gc)
  gc:drawString("Hola, TI-Nspire", 10, 10)
end
"""
ROLE = Qt.UserRole  # ("script", key) | ("page", (problem, card)) | ("xml", name) | ("resource", name) | ("entry", name)

# How the explorer marks content (shown with a colour and a label).
STATUS = {
    "editable": ("editable", "#15803d"),
    "readonly": ("solo lectura", "#5f6b7a"),
    "unknown": ("desconocido", "#b45309"),
    "protected": ("protegido", "#c2410c"),
}


# Short names for widget types seen in real documents; others are shown as stored.
WIDGET_NAMES = {"TI.Notepad": "Notas", "TI.ScriptApp": "Script Lua"}


def _mark(item: QTreeWidgetItem, status: str, why: str = "") -> None:
    label, colour = STATUS[status]
    item.setText(0, f"{item.text(0)}  [{label}]")
    item.setForeground(0, QBrush(QColor(colour)))
    item.setToolTip(0, why or label)


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


def rep_short(rep) -> str:
    return f"{rep.origin}, {len(rep.entries)} secciones, {len(rep.scripts)} scripts"


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
        self.pages: list[notes.NotesPage] = []
        self.problem_xml: dict[str, bytes] = {}
        self.summaries: dict[str, list] = {}
        self.state = PageState()
        self.current_page: tuple[str, int] | None = None

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
        self.code_page = QWidget()
        cpl = QVBoxLayout(self.code_page)
        cpl.setContentsMargins(0, 0, 0, 0)
        nav = QHBoxLayout()
        self.functions = QComboBox()
        self.functions.setToolTip("Ir a una función del script")
        self.functions.activated.connect(lambda i: self.code.go_to_line(self.functions.itemData(i))
                                         if self.functions.itemData(i) else None)
        nav.addWidget(QLabel("Funciones:"))
        nav.addWidget(self.functions, 1)
        cpl.addLayout(nav)
        self.code = CodeEditor(theme=theme_name)
        self.code.textChanged.connect(self._code_changed)
        cpl.addWidget(self.code, 1)
        self.lint = QLabel("")
        self.lint.setWordWrap(True)
        cpl.addWidget(self.lint)
        self._lint_timer = QTimer(self, singleShot=True, interval=1200)
        self._lint_timer.timeout.connect(self._lint)
        self.page_view = PageView()
        self.page_view.edited.connect(self._page_edited)
        self.page_view.rejected.connect(lambda msg: self.message.emit("error", msg))
        self.xml_view = CodeEditor(theme=theme_name, lua=False)
        self.xml_view.setReadOnly(True)
        self.info = QTextBrowser()
        self.image = QLabel(alignment=Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.image)
        scroll.setWidgetResizable(True)
        for w in (self.code_page, self.xml_view, self.info, scroll, self.page_view):
            self.stack.addWidget(w)
        self.image_page = scroll
        self.find_bar = FindBar()
        cl.addWidget(self.stack, 1)
        cl.addWidget(self.find_bar)
        split.addWidget(center)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        props_card = Card("Propiedades")
        self.props = QTextBrowser()
        props_card.body.addWidget(self.props)
        hist_card = Card("Historial")
        self.history = QListWidget()
        self.history.setMaximumHeight(170)
        hist_card.body.addWidget(self.history)
        rl.addWidget(props_card, 3)
        rl.addWidget(hist_card, 1)
        split.addWidget(right)
        split.setSizes([290, 600, 320])
        self._show_info("<h3>Cargando…</h3>")

    # -- state ------------------------------------------------------------------

    @property
    def title(self) -> str:
        name = self.path.name if self.path else "Nuevo documento Lua"
        return name + (" *" if self.dirty else "")

    @property
    def page_table(self):
        return self.page_view.table

    @property
    def note_edits(self) -> dict:
        return self.state.note_edits

    @note_edits.setter
    def note_edits(self, value: dict) -> None:
        self.state.note_edits = value

    @property
    def dirty(self) -> bool:
        return (any(self.edits.get(k, v) != v for k, v in self.originals.items()) or bool(self.changed_notes())
                or bool(self.state.layouts) or bool(self.state.orders))

    def changed_notes(self) -> dict[tuple[str, int], dict[int, str]]:
        out = {}
        for key, runs in self.note_edits.items():
            page = next(p for p in self.pages if (p.problem, p.card) == key)
            diff = {i: t for i, t in runs.items() if page.runs[i].text != t}
            if diff:
                out[key] = diff
        return out

    @property
    def editable(self) -> bool:  # noqa: F811 (scripts or notes)
        return bool(set(self.originals) - self.protected) or any(
            r.editable for p in self.pages for r in p.runs)

    def log(self, text: str) -> None:
        self.history.addItem(f"{time.strftime('%H:%M:%S')}  {text}")
        self.history.scrollToBottom()

    @property
    def is_new(self) -> bool:
        return self.original is None and bool(self.originals)

    def _code_changed(self) -> None:
        if self.current is not None and self.current not in self.protected:
            self.edits[self.current] = self.code.toPlainText()
            self.changed.emit()
            self._lint_timer.start()
        self._refresh_functions()

    def _refresh_functions(self) -> None:
        self.functions.blockSignals(True)
        self.functions.clear()
        self.functions.addItem("—", None)
        for name, line in lua_tools.functions(self.code.toPlainText()):
            self.functions.addItem(f"{name}  (línea {line})", line)
        self.functions.blockSignals(False)

    def _lint(self) -> None:
        """Background syntax check (luac5.1) plus TI-Nspire API warnings, after a pause in typing."""
        source = self.code.toPlainText()
        key = self.current

        def done(result):
            syntax, warnings = result
            if key != self.current:
                return
            self.code.set_warning_lines({line for line, _ in warnings})
            parts = []
            if syntax.available and not syntax.ok:
                self.code._error_line = syntax.line
                self.code._highlight_line()
                parts.append(f"✘ Línea {syntax.line}: {syntax.message}")
            elif syntax.available:
                parts.append("✔ Sintaxis Lua 5.1 correcta")
            else:
                parts.append(syntax.message)
            parts += [f"⚠ Línea {line}: {msg}" for line, msg in warnings[:5]]
            self.lint.setText("   ".join(parts))

        run_task(lambda p: (lua_tools.check_syntax(source), lua_tools.ti_warnings(source)), done)

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

        def work(p):
            data = self.path.read_bytes()
            rep = inspect.analyze(data)
            doc = container.parse(data)
            try:
                note_pages = notes.document_pages(doc)
            except ValueError:  # a protected problem: pages stay unknown
                note_pages = []
            xmls, summaries = {}, {}
            for name in notes.problem_names(doc):
                try:
                    xmls[name] = xmldoc.decode_entry(doc.entry(name))[1]
                    summaries[name] = pages.problem_summaries(xmls[name])
                except ValueError:
                    continue
            return data, rep, note_pages, xmls, summaries

        run_task(work, self._loaded, failed)

    def _loaded(self, result) -> None:
        self.original, self.report, self.pages, self.problem_xml, self.summaries = result
        self.doc = container.parse(self.original)
        self.log(f"Abierto {self.path.name} ({rep_short(self.report)})")
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
            it = QTreeWidgetItem([(s.title or f"Script {s.index + 1}") + f" — {s.problem}"])
            it.setIcon(0, icon("editor"))
            it.setData(0, ROLE, ("script", (s.problem, s.index)))
            scripts.append(it)
        pages_items = []
        protected_problems = {e.name for e in rep.entries if e.kind == "XML" and not e.readable}
        by_key = {(p.problem, p.card): p for p in self.pages}
        for problem, summaries in self.summaries.items():
            for summary in summaries:
                key = (problem, summary.card)
                note_page = by_key.get(key)
                it = QTreeWidgetItem([self._page_label(key, summary)])
                it.setData(0, ROLE, ("page", key))
                if note_page is not None and not note_page.readable:
                    _mark(it, "unknown", note_page.error)
                elif note_page is not None and note_page.is_notes and (
                        any(r.editable for r in note_page.runs) or notes.structure_allowed(
                            self.problem_xml[problem], summary.card)[0]):
                    _mark(it, "editable", "Texto y párrafos de notas")
                elif summary.widget == "TI.ScriptApp":
                    _mark(it, "readonly", "El script se edita en «Scripts»")
                elif not summary.understood:
                    _mark(it, "unknown", f"Tipo de página no reconocido: {summary.widget}")
                else:
                    _mark(it, "readonly", f"{summary.app}: solo lectura")
                pages_items.append(it)
        for name in sorted(protected_problems):
            it = QTreeWidgetItem([name])
            _mark(it, "protected", "No se puede descifrar")
            pages_items.append(it)
        pages = pages_items
        section("Páginas", pages, "Sin páginas")
        for it in scripts:
            key = it.data(0, ROLE)[1]
            _mark(it, "protected" if key in self.protected else "editable")
        section("Scripts", scripts, "Sin scripts Lua")

        xmls, resources, entries = [], [], []
        for e in rep.entries:
            it = QTreeWidgetItem([e.name])
            it.setIcon(0, icon("file"))
            it.setToolTip(0, f"{e.kind} · {e.method_name} · {e.status}")
            it.setData(0, ROLE, ("xml" if e.kind == "XML" else "resource", e.name))
            if e.status.startswith("protegido"):
                _mark(it, "protected", e.status)
            elif not e.readable:
                _mark(it, "unknown", e.status)
            else:
                _mark(it, "readonly")
            (xmls if e.kind == "XML" else resources).append(it)
            bin_item = QTreeWidgetItem([e.name])
            bin_item.setData(0, ROLE, ("entry", e.name))
            entries.append(bin_item)
        section("XML", xmls, "Sin XML")
        section("Recursos", resources, "Sin recursos")
        section("Secciones binarias", entries, "—")
        first = scripts[0] if scripts else (pages[0] if pages else (xmls[0] if xmls else None))
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
            self.functions.setEnabled(True)
            self.stack.setCurrentWidget(self.code_page)
            self._refresh_functions()
            self._lint_timer.start()
            self.find_bar.attach(self.code, with_replace=not locked)
            if self.report:
                self.props.setHtml(self._entry_props(key[0]) + (
                    "<p><b>Script protegido por TI (sc:cry): solo lectura.</b></p>" if locked else ""))
            return
        self.current = None
        if self.report is None:
            return
        if kind == "page":
            self._show_page(key)
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

    # -- pages -----------------------------------------------------------------------

    def _page_label(self, key: tuple[str, int], summary) -> str:
        problem, card = key
        order = self.state.orders.get(problem)
        moved = f" → {order.index(card) + 1}" if order and order.index(card) != card else ""
        name = WIDGET_NAMES.get(summary.widget, summary.app if summary.understood else summary.widget)
        prefix = f"{problem.removesuffix('.xml')} · " if len(self.summaries) > 1 else ""
        return f"{prefix}Pág. {card + 1}{moved} · {name}"

    def refresh_page_labels(self) -> None:
        root = next((self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())
                     if self.tree.topLevelItem(i).text(0).startswith("Páginas")), None)
        if root is None:
            return
        for i in range(root.childCount()):
            it = root.child(i)
            data = it.data(0, ROLE)
            if data and data[0] == "page":
                problem, card = data[1]
                status = it.text(0).rsplit("  [", 1)
                label = self._page_label(data[1], self.summaries[problem][card])
                it.setText(0, label + (f"  [{status[1]}" if len(status) == 2 else ""))

    def _show_page(self, key: tuple[str, int]) -> None:
        problem, card = key
        page = next((p for p in self.pages if (p.problem, p.card) == key), None)
        summary = self.summaries[problem][card]
        self.current_page = key
        self.page_view.show_page(self.state, key, self.problem_xml[problem], page, summary,
                                 len(self.summaries[problem]))
        self.stack.setCurrentWidget(self.page_view)
        variables = pages.problem_variables(self.problem_xml[problem])
        extra = ""
        if page is not None and page.is_notes:
            extra = (f"Párrafos: {page.paragraphs}<br>Fragmentos de texto: {len(page.runs)} "
                     f"({sum(r.editable for r in page.runs)} editables)<br>Cuadros matemáticos: {len(page.math)}"
                     f"<br>Imágenes: {len(page.images)}")
        self.props.setHtml(
            f"<h3>Página {card + 1} de {html.escape(problem)}</h3><p>Aplicación: {html.escape(summary.app)}"
            f"<br>Widget: {html.escape(summary.widget)}<br>{extra}</p>"
            + ("<p><b>Variables del problema</b> (compartidas por sus páginas): "
               + ", ".join(html.escape(f"{n}({p})={v}" if p else f"{n}={v}") for n, p, v in variables) + "</p>"
               if variables else "")
            + "<p>Doble clic en un texto editable para cambiarlo. Letras (incluidas á é í ó ú ü ñ), números, "
              "espacios, π y puntuación básica. Los párrafos con objetos y los cuadros matemáticos se conservan.</p>")

    def _page_edited(self, text: str) -> None:
        self.log(text)
        self.refresh_page_labels()
        self.changed.emit()

    def undo_pages(self) -> bool:
        if not self.state.undo():
            return False
        self._after_state_change("Deshecho")
        return True

    def redo_pages(self) -> bool:
        if not self.state.redo():
            return False
        self._after_state_change("Rehecho")
        return True

    def _after_state_change(self, text: str) -> None:
        if self.current_page is not None and self.stack.currentWidget() is self.page_view:
            self._show_page(self.current_page)
        self.refresh_page_labels()
        self.log(text)
        self.changed.emit()

    # -- build ---------------------------------------------------------------------

    def build(self) -> bytes:
        """Rebuilt document with every edited script (raises RebuildError/ValueError). Thread-safe."""
        if self.is_new:
            return rebuild(None, self.edits[("Problem1.xml", 0)])
        scripts = {k: v for k, v in self.edits.items() if v != self.originals.get(k)}
        return apply_edits(self.original, scripts, self.changed_notes(), self.state.layouts, self.state.orders)


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
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)  # ten actions must fit at 1280 px
        new_btn = QToolButton()
        new_btn.setText("Nuevo")
        new_btn.setIcon(icon("new"))
        new_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        new_btn.setPopupMode(QToolButton.InstantPopup)
        new_menu = QMenu(new_btn)
        new_menu.addAction(icon("new"), "Documento Lua vacío", self.new_document)
        new_menu.addAction(icon("import"), "Desde un archivo .lua…", self.import_lua)
        new_btn.setMenu(new_menu)
        tb.addWidget(new_btn)
        tb.addAction(icon("open"), "Abrir…", self.choose_file)
        tb.addSeparator()
        self.act_undo = tb.addAction(icon("edit-undo"), "Deshacer", self.undo)
        self.act_redo = tb.addAction(icon("edit-redo"), "Rehacer", self.redo)
        self.act_save = tb.addAction(icon("save"), "Guardar como…", self.save_new_version)
        self.act_extract = tb.addAction(icon("export"), "Extraer…", self.extract)
        self.act_rebuild = tb.addAction(icon("build"), "Reconstruir", self.rebuild_and_report)
        self.act_validate = tb.addAction(icon("check"), "Validar", self.validate)
        self.act_format = tb.addAction(icon("editor"), "Formatear", self.format_script)
        cmp_btn = QToolButton()
        cmp_btn.setText("Comparar")
        cmp_btn.setIcon(icon("diff"))
        cmp_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        cmp_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(cmp_btn)
        self.act_cmp_orig = menu.addAction("Vista previa de cambios (original frente a editado)",
                                           self.compare_with_original)
        self.act_cmp_file = menu.addAction("Con otro documento .tns…", self.compare_with_file)
        cmp_btn.setMenu(menu)
        self.cmp_btn = cmp_btn
        tb.addWidget(cmp_btn)
        self.act_send = tb.addAction(icon("upload"), "Enviar", self._send)
        self.act_send.setToolTip("Enviar la última versión guardada a la calculadora")
        root.addWidget(tb)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(lambda _: self._update_actions())
        self._format_timer = QTimer(self, interval=500)  # the current item can change without a signal here
        self._format_timer.timeout.connect(self._update_format_action)
        self._format_timer.start()
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
            t.state.clear()

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
        self._update_format_action()

    def _on_script(self) -> bool:
        t = self.tab
        return t is not None and t.current is not None and t.stack.currentWidget() is t.code_page

    def undo(self) -> None:
        if self._on_script():
            self.tab.code.undo()
        elif self.tab:
            self.tab.undo_pages()
        self._update_actions()

    def redo(self) -> None:
        if self._on_script():
            self.tab.code.redo()
        elif self.tab:
            self.tab.redo_pages()
        self._update_actions()

    def _update_undo_actions(self) -> None:
        t = self.tab
        if t is None:
            can_undo = can_redo = False
        elif self._on_script():
            can_undo, can_redo = t.code.document().isUndoAvailable(), t.code.document().isRedoAvailable()
        else:
            can_undo, can_redo = bool(t.state.undo_stack), bool(t.state.redo_stack)
        self.act_undo.setEnabled(can_undo)
        self.act_redo.setEnabled(can_redo)
        self.act_undo.setToolTip("Deshace el último cambio del script o de las páginas" if can_undo else "Nada que deshacer")
        self.act_redo.setToolTip("" if can_redo else "Nada que rehacer")

    def _update_format_action(self) -> None:
        self._update_undo_actions()
        t = self.tab
        if not self.luac:
            ok, why = False, "Formatear necesita luac5.1 para comprobar que el código no cambia"
        elif t is None or t.current is None or t.current in t.protected:
            ok, why = False, "Selecciona un script editable"
        else:
            ok, why = True, ""
        self.act_format.setEnabled(ok)
        self.act_format.setToolTip(why or "Reindenta el script; solo se aplica si el bytecode compilado no cambia")

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
            tab.log("Validado")
            self.message.emit("ok", "; ".join(parts) + ".")

        run_task(work, done, lambda err: self.message.emit("error", f"Validación fallida: {err}"))

    def format_script(self) -> None:
        tab = self.tab
        source = tab.code.toPlainText()

        def done(formatted):
            if formatted == source:
                self.message.emit("info", "El script ya tenía el formato esperado.")
                return
            cursor = tab.code.textCursor()
            cursor.beginEditBlock()  # one undo step
            cursor.select(cursor.SelectionType.Document)
            cursor.insertText(formatted)
            cursor.endEditBlock()
            tab.log("Script formateado (bytecode idéntico)")
            self.message.emit("ok", "Formato aplicado: el bytecode compilado es idéntico al original.")

        run_task(lambda p: lua_tools.safe_format(source, self.luac), done,
                 lambda err: self.message.emit("error", f"No se aplica el formato: {err}"))

    def rebuild_and_report(self) -> None:
        tab = self.tab

        def done(data):
            if tab.is_new:
                self.message.emit("ok", f"Documento nuevo válido ({human_size(len(data))}).")
                return
            cmp = compare_documents(tab.original, data)
            changed = [c.name for c in cmp.components if c.status != "igual"]
            tab.log(f"Reconstruido: cambia {', '.join(changed) or 'nada'}")
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
            for (problem, card), layout in tab.state.layouts.items():
                paras = notes.page_paragraphs(tab.problem_xml[problem], card)
                old = "\n".join(p.text if p.kind == "text" else "[párrafo con objetos]" for p in paras) + "\n"
                new = "\n".join(x if isinstance(x, str) else (paras[x].text if paras[x].kind == "text"
                                                             else "[párrafo con objetos]") for x in layout) + "\n"
                diffs.append((f"Párrafos {problem} pág. {card + 1}", text_diff(old, new)))
            for problem, order in tab.state.orders.items():
                diffs.append((f"Orden de páginas {problem}", "Nuevo orden: " + ", ".join(str(i + 1) for i in order)))
            for (problem, card), runs in tab.changed_notes().items():
                page = next(p for p in tab.pages if (p.problem, p.card) == (problem, card))
                lines = [f"- {page.runs[i].text}\n+ {t}" for i, t in sorted(runs.items())]
                diffs.append((f"Notas {problem} pág. {card + 1}", "\n".join(lines)))
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
            tab.log("Vista previa de cambios")
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
                 lambda written: (tab.log(f"Extraído en {out.name}"),
                                  self.message.emit("ok", f"{len(written)} archivos extraídos en {out}")),
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
        tab.log(f"Guardado como {target.name}")
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
