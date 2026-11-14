"""Page view of the editor: paragraphs of a Notes page, read-only views of other pages.

State lives in :class:`PageState` (no Qt), so edits, undo/redo and the rebuild
use the same data. The widget only shows it and turns user actions into
state changes; it never writes documents.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...tns import notes

STATUS_COLOURS = {"editable": "#15803d", "solo lectura": "#5f6b7a", "desconocido": "#b45309", "protegido": "#c2410c"}


@dataclass
class PageState:
    """Pending edits of one document: runs, paragraph layouts, page orders, with undo/redo."""

    note_edits: dict[tuple[str, int], dict[int, str]] = field(default_factory=dict)
    layouts: dict[tuple[str, int], list[int | str]] = field(default_factory=dict)
    orders: dict[str, list[int]] = field(default_factory=dict)
    undo_stack: list[tuple] = field(default_factory=list)
    redo_stack: list[tuple] = field(default_factory=list)

    def _snap(self) -> tuple:
        return copy.deepcopy((self.note_edits, self.layouts, self.orders))

    def checkpoint(self) -> None:
        self.undo_stack.append(self._snap())
        self.redo_stack.clear()

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(self._snap())
        self.note_edits, self.layouts, self.orders = self.undo_stack.pop()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(self._snap())
        self.note_edits, self.layouts, self.orders = self.redo_stack.pop()
        return True

    def clear(self) -> None:
        self.note_edits, self.layouts, self.orders = {}, {}, {}
        self.undo_stack.clear()
        self.redo_stack.clear()


@dataclass
class ParaInfo:
    """Original paragraph with the runs and maths boxes it contains (page-wide indexes)."""

    para: notes.Paragraph
    runs: list[int]
    math: list[int]
    images: list[str]


def paragraph_infos(xml: bytes, card: int) -> list[ParaInfo]:
    _, _, inner = notes._page_inner(xml, card)
    _, _, spans = notes._paragraph_spans(inner)
    paras = notes.page_paragraphs(xml, card)
    out, run_i, math_i = [], 0, 0
    for p, (a, b) in zip(paras, spans):
        el = ET.fromstring(inner[a:b])
        n_runs = sum(1 for x in el.iter("leaf") if x.get("name") == "1word")
        n_math = sum(1 for x in el.iter("node") if x.get("name") == "0el" and x.find("mbox") is not None)
        imgs = [w.findtext("name") for w in el.iter("wdgt") if w.get("type") == "Image"]
        out.append(ParaInfo(p, list(range(run_i, run_i + n_runs)), list(range(math_i, math_i + n_math)), imgs))
        run_i += n_runs
        math_i += n_math
    return out


class PageView(QWidget):
    """Table of one page plus the paragraph/page actions that are actually implemented."""

    edited = Signal(str)  # history text
    rejected = Signal(str)  # error message

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        # Short labels keep the bar narrow; the full action is in the tooltip/accessible name.
        self.btn_insert = QPushButton("＋ Párrafo")
        self.btn_delete = QPushButton("－ Párrafo")
        self.btn_up = QPushButton("▲")
        self.btn_down = QPushButton("▼")
        self.btn_page_up = QPushButton("◀ Página")
        self.btn_page_down = QPushButton("Página ▶")
        names = {self.btn_insert: "Insertar párrafo", self.btn_delete: "Eliminar párrafo",
                 self.btn_up: "Subir párrafo", self.btn_down: "Bajar párrafo",
                 self.btn_page_up: "Mover la página hacia atrás", self.btn_page_down: "Mover la página hacia delante"}
        for b, name in names.items():
            b.setAccessibleName(name)
            b.setMinimumWidth(0)
        self._names = names
        for b in (self.btn_insert, self.btn_delete, self.btn_up, self.btn_down):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(self.btn_page_up)
        bar.addWidget(self.btn_page_down)
        lay.addLayout(bar)
        self.reason = QLabel("")
        self.reason.setWordWrap(True)
        lay.addWidget(self.reason)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Elemento", "Contenido", "Estado"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.itemChanged.connect(self._changed)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        lay.addWidget(self.table, 1)
        self.btn_insert.clicked.connect(self._insert)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down.clicked.connect(lambda: self._move(1))
        self.btn_page_up.clicked.connect(lambda: self._move_page(-1))
        self.btn_page_down.clicked.connect(lambda: self._move_page(1))
        self.state: PageState | None = None
        self.key: tuple[str, int] | None = None
        self.xml: bytes = b""
        self.page: notes.NotesPage | None = None
        self.summary = None
        self.n_pages = 0
        self.infos: list[ParaInfo] = []
        self.structure_ok, self.structure_why = False, ""

    # -- showing -------------------------------------------------------------------

    def show_page(self, state: PageState, key, xml: bytes, page, summary, n_pages: int) -> None:
        self.state, self.key, self.xml, self.page, self.summary, self.n_pages = state, key, xml, page, summary, n_pages
        self.infos = []
        self.structure_ok, self.structure_why = False, "solo las páginas de notas tienen párrafos"
        if page is not None and page.is_notes and page.readable:
            try:
                self.infos = paragraph_infos(xml, key[1])
                self.structure_ok, self.structure_why = notes.structure_allowed(xml, key[1])
            except notes.NotesError as exc:
                self.structure_why = str(exc)
        self._fill()

    def layout(self) -> list[int | str]:
        return self.state.layouts.get(self.key, list(range(len(self.infos))))

    def _add_row(self, kind: str, content: str, status: str, why: str = "", data=None, editable=False) -> None:
        t = self.table
        r = t.rowCount()
        t.insertRow(r)
        for c, text in enumerate((kind, content, status)):
            item = QTableWidgetItem(text)
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if c == 1 and editable:
                flags |= Qt.ItemIsEditable
            item.setFlags(flags)
            item.setData(Qt.UserRole, data)
            if why:
                item.setToolTip(why)
            if c == 2:
                item.setForeground(QBrush(QColor(STATUS_COLOURS.get(status, "#5f6b7a"))))
            t.setItem(r, c, item)

    def _fill(self) -> None:
        t = self.table
        t.blockSignals(True)
        t.setRowCount(0)
        if self.infos:
            edits = self.state.note_edits.get(self.key, {})
            for pos, item in enumerate(self.layout()):
                if isinstance(item, str):
                    self._add_row("Párrafo", item, "editable", data=("para", pos), editable=self.structure_ok)
                    continue
                info = self.infos[item]
                if info.para.kind == "text":
                    self._add_row("Párrafo", info.para.text, "editable" if self.structure_ok else "solo lectura",
                                  "" if self.structure_ok else self.structure_why, ("para", pos), self.structure_ok)
                    continue
                self._add_row("Párrafo con objetos", "", "solo lectura", info.para.reason, ("para", pos))
                for run_i in info.runs:
                    run = self.page.runs[run_i]
                    if run.text or run.editable:
                        self._add_row("   ↳ Texto", edits.get(run_i, run.text),
                                      "editable" if run.editable else "solo lectura",
                                      "" if run.editable else run.reason, ("run", run_i), run.editable)
                for m_i in info.math:
                    m = self.page.math[m_i]
                    status = "desconocido" if m.unknown else "solo lectura"
                    why = ("plantillas no reconocidas: " + ", ".join(m.unknown)) if m.unknown else \
                        "cuadro matemático: el resultado está guardado en caché y no se recalcula aquí"
                    shown = f"{m.input or '(vacío)'}  →  {m.output}" if m.output else (m.input or "(vacío)")
                    self._add_row("   ↳ Matemáticas", shown + (f"   [error {m.error}]" if m.error else ""), status, why)
                for img in info.images:
                    self._add_row("   ↳ Imagen", img, "solo lectura", "recurso del documento")
        elif self.page is not None and not self.page.readable:
            self._add_row("Página", "No se pudo interpretar", "desconocido", self.page.error)
        elif self.summary is not None:
            status = "solo lectura" if self.summary.understood else "desconocido"
            for label, value in self.summary.details or [("Aplicación", self.summary.app)]:
                self._add_row(label, value, status, "este tipo de página todavía no se edita")
        t.blockSignals(False)
        header = t.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._update_buttons()

    # -- actions -------------------------------------------------------------------

    def _selected(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def _para_kind(self, pos: int) -> str:
        item = self.layout()[pos]
        return "text" if isinstance(item, str) else self.infos[item].para.kind

    def _update_buttons(self) -> None:
        sel = self._selected()
        on_para = bool(self.infos) and sel is not None and sel[0] == "para"
        text_para = on_para and self._para_kind(sel[1]) == "text"
        n = len(self.layout()) if self.infos else 0
        rules = {
            self.btn_insert: (self.structure_ok, self.structure_why),
            self.btn_delete: (self.structure_ok and text_para and n > 1,
                              self.structure_why or "Selecciona un párrafo de texto (los párrafos con objetos se conservan)"),
            self.btn_up: (self.structure_ok and on_para and sel[1] > 0 and
                          (text_para or self._para_kind(sel[1] - 1) == "text"),
                          self.structure_why or "Selecciona un párrafo; dos párrafos con objetos no se intercambian"),
            self.btn_down: (self.structure_ok and on_para and sel[1] < n - 1 and
                            (text_para or self._para_kind(sel[1] + 1) == "text"),
                            self.structure_why or "Selecciona un párrafo; dos párrafos con objetos no se intercambian"),
            self.btn_page_up: (self.key is not None and self._page_pos() > 0, "Ya es la primera página"),
            self.btn_page_down: (self.key is not None and self._page_pos() < self.n_pages - 1, "Ya es la última página"),
        }
        for b, (ok, why) in rules.items():
            b.setEnabled(bool(ok))
            b.setToolTip(self._names[b] if ok else f"{self._names[b]}: {why}")
        self.reason.setText("" if self.structure_ok or not self.infos else f"Estructura de párrafos bloqueada: {self.structure_why}")

    def _set_layout(self, layout: list[int | str], history: str) -> None:
        try:
            notes.set_paragraphs(self.xml, self.key[1], layout)  # validate now, not at rebuild time
        except notes.NotesError as exc:
            self.rejected.emit(str(exc))
            self._fill()
            return
        self.state.checkpoint()
        if layout == list(range(len(self.infos))):
            self.state.layouts.pop(self.key, None)
        else:
            self.state.layouts[self.key] = layout
        self._fill()
        self.edited.emit(history)

    def _insert(self) -> None:
        sel = self._selected()
        layout = list(self.layout())
        pos = sel[1] + 1 if sel and sel[0] == "para" else len(layout)
        layout.insert(pos, "")
        self._set_layout(layout, f"Párrafo insertado en la posición {pos + 1}")
        self.table.selectRow(self._row_of(("para", pos)))

    def _delete(self) -> None:
        sel = self._selected()
        layout = list(self.layout())
        del layout[sel[1]]
        self._set_layout(layout, f"Párrafo {sel[1] + 1} eliminado")

    def _move(self, step: int) -> None:
        sel = self._selected()
        layout = list(self.layout())
        i, j = sel[1], sel[1] + step
        layout[i], layout[j] = layout[j], layout[i]
        self._set_layout(layout, f"Párrafo {i + 1} movido a la posición {j + 1}")
        self.table.selectRow(self._row_of(("para", j)))

    def _row_of(self, data) -> int:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == data:
                return r
        return -1

    def _page_pos(self) -> int:
        problem, card = self.key
        order = self.state.orders.get(problem, list(range(self.n_pages)))
        return order.index(card)

    def _move_page(self, step: int) -> None:
        problem, card = self.key
        order = list(self.state.orders.get(problem, list(range(self.n_pages))))
        i = order.index(card)
        order[i], order[i + step] = order[i + step], order[i]
        self.state.checkpoint()
        if order == list(range(self.n_pages)):
            self.state.orders.pop(problem, None)
        else:
            self.state.orders[problem] = order
        self._update_buttons()
        self.edited.emit(f"Página {card + 1} movida a la posición {i + step + 1}")

    def _changed(self, item: QTableWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if item.column() != 1 or data is None:
            return
        text = item.text()
        if data[0] == "run":
            if not text or not notes.ALLOWED.match(text):
                self.rejected.emit("Texto no permitido: usa letras (incluidas á é í ó ú ü ñ), números, espacios, π y "
                                   "puntuación básica (sin < > & \").")
                self._fill()
                return
            self.state.checkpoint()
            self.state.note_edits.setdefault(self.key, {})[data[1]] = text
            self._fill()
            self.edited.emit(f"Texto editado: página {self.key[1] + 1}, fragmento {data[1] + 1}")
        elif data[0] == "para":
            layout = list(self.layout())
            layout[data[1]] = text
            self._set_layout(layout, f"Párrafo {data[1] + 1} editado")
