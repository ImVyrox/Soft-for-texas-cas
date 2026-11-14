"""Tools page (batch conversion and validation) and settings page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from ... import __version__
from ...config import LOG_DIR, atomic_write, unique_path
from ...core.link import find_helper
from ...tns.inspect import validate_bytes
from ...tns.lua import build_lua_document
from ..widgets.common import Card, icon, label
from ..workers import run_task


class ToolsPage(QWidget):
    message = Signal(str, str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.settings = settings
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 18)
        root.setSpacing(14)
        root.addWidget(label("Herramientas", "title"))
        row = QHBoxLayout()
        root.addLayout(row)

        conv = Card("Convertir Lua → .tns")
        conv.body.addWidget(label("Crea documentos .tns a partir de scripts .lua (formato Luna 2.1). "
                                  "Los .tns se guardan junto a cada script, sin reemplazar nada.", "muted", wrap=True))
        b = QPushButton(icon("build"), "Elegir scripts .lua…")
        b.setProperty("kind", "primary")
        b.clicked.connect(self._convert)
        conv.body.addWidget(b, 0, Qt.AlignLeft)
        conv.body.addStretch()
        row.addWidget(conv)

        val = Card("Validar documentos")
        val.body.addWidget(label("Comprueba la estructura, los CRC y que el contenedor se pueda reescribir "
                                 "de forma idéntica.", "muted", wrap=True))
        b2 = QPushButton(icon("check"), "Elegir documentos .tns…")
        b2.clicked.connect(self._validate)
        val.body.addWidget(b2, 0, Qt.AlignLeft)
        val.body.addStretch()
        row.addWidget(val)

        out = Card("Resultado")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        out.body.addWidget(self.log)
        root.addWidget(out, 1)

    def _convert(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Scripts Lua", self.settings.workspace, "Lua (*.lua)")
        if not files:
            return

        def work(p):
            lines = []
            for f in files:
                src = Path(f)
                try:
                    data = build_lua_document(src.read_text(encoding="utf-8"))
                    problems = validate_bytes(data)
                    if problems:
                        raise ValueError("; ".join(problems))
                    target = unique_path(src.with_suffix(".tns"))
                    atomic_write(target, data)
                    lines.append(f"✔ {src.name} → {target.name}")
                except (OSError, ValueError, UnicodeDecodeError) as exc:
                    lines.append(f"✘ {src.name}: {exc}")
            return lines

        run_task(work, lambda lines: self.log.appendPlainText("\n".join(lines)),
                 lambda err: self.message.emit("error", err))

    def _validate(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Documentos", self.settings.workspace, "TI-Nspire (*.tns)")
        if not files:
            return

        def work(p):
            out = []
            for f in files:
                try:
                    problems = validate_bytes(Path(f).read_bytes())
                except OSError as exc:
                    problems = [str(exc)]
                out.append(f"{'✔' if not problems else '✘'} {Path(f).name}" +
                           ("" if not problems else ": " + "; ".join(problems)))
            return out

        run_task(work, lambda lines: self.log.appendPlainText("\n".join(lines)),
                 lambda err: self.message.emit("error", err))


class SettingsPage(QWidget):
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.settings = settings
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 18)
        root.setSpacing(14)
        root.addWidget(label("Configuración", "title"))

        card = Card("General")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.theme = QComboBox()
        for key, text in (("system", "Según el sistema"), ("light", "Claro"), ("dark", "Oscuro")):
            self.theme.addItem(text, key)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        self.theme.currentIndexChanged.connect(self._save)
        form.addRow("Tema", self.theme)
        ws = QHBoxLayout()
        self.workspace = QLineEdit(settings.workspace)
        self.workspace.setReadOnly(True)
        pick = QPushButton("Cambiar…")
        pick.clicked.connect(self._pick_workspace)
        ws.addWidget(self.workspace, 1)
        ws.addWidget(pick)
        form.addRow("Carpeta de trabajo", ws)
        self.auto = QCheckBox("Conectar automáticamente al detectar la calculadora")
        self.auto.setChecked(settings.auto_connect)
        self.auto.toggled.connect(self._save)
        form.addRow("", self.auto)
        self.demo = QCheckBox("Modo demostración (calculadora simulada, sin USB)")
        self.demo.setChecked(settings.demo_mode)
        self.demo.toggled.connect(self._save)
        form.addRow("", self.demo)
        card.body.addLayout(form)
        root.addWidget(card)

        about = Card("Acerca de")
        helper = find_helper()
        about.body.addWidget(label(
            f"Texas CAS Manager {__version__}<br>Programa auxiliar USB: "
            f"{helper or '<b>no compilado</b> (ejecuta scripts/build-helper.sh)'}<br>"
            f"Registro: {LOG_DIR / 'app.log'}<br>"
            "Comunicación USB mediante libticalcs2 (TiLP). Formato de documentos Lua compatible con Luna 2.1.",
            "muted", wrap=True))
        root.addWidget(about)
        root.addStretch()

    def _pick_workspace(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Carpeta de trabajo", self.settings.workspace)
        if d:
            self.workspace.setText(d)
            self._save()

    def _save(self) -> None:
        self.settings.theme = self.theme.currentData()
        self.settings.workspace = self.workspace.text()
        self.settings.auto_connect = self.auto.isChecked()
        self.settings.demo_mode = self.demo.isChecked()
        self.settings.save()
        self.changed.emit()
