"""Home page: connection, device, storage, recent documents, quick actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QListWidget, QListWidgetItem, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from ...core.link import DeviceInfo
from ..widgets.common import Card, human_size, icon, label


class HomePage(QWidget):
    navigate = Signal(str)
    open_document = Signal(str)
    connect_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        root.addWidget(label("Inicio", "title"))
        root.addWidget(label("Gestiona tu TI-Nspire CX CAS y tus documentos .tns desde Linux.", "muted"))

        grid = QGridLayout()
        grid.setSpacing(16)
        root.addLayout(grid, 1)

        # Connection
        self.conn = Card("Conexión")
        self.conn_state = label("Buscando calculadora…", "big")
        self.conn_detail = label("Conecta la calculadora por USB y déjala encendida en la pantalla de inicio.",
                                 "muted", wrap=True)
        self.connect_btn = QPushButton(icon("connect"), "Conectar")
        self.connect_btn.setProperty("kind", "primary")
        self.connect_btn.clicked.connect(self.connect_requested)
        self.conn.body.addWidget(self.conn_state)
        self.conn.body.addWidget(self.conn_detail)
        self.conn.body.addStretch()
        self.conn.body.addWidget(self.connect_btn, 0, Qt.AlignLeft)
        grid.addWidget(self.conn, 0, 0)

        # Device + storage
        self.dev = Card("Calculadora")
        self.model = label("—", "big")
        self.os = label("", "muted")
        self.storage_lbl = label("Almacenamiento: —", "muted")
        self.storage = QProgressBar()
        self.storage.setTextVisible(False)
        self.ram_lbl = label("", "muted")
        for w in (self.model, self.os, self.storage_lbl, self.storage, self.ram_lbl):
            self.dev.body.addWidget(w)
        self.dev.body.addStretch()
        grid.addWidget(self.dev, 0, 1)

        # Recent documents
        self.recent_card = Card("Documentos recientes")
        self.recent = QListWidget()
        self.recent.itemActivated.connect(lambda it: self.open_document.emit(it.data(Qt.UserRole)))
        self.recent_card.body.addWidget(self.recent)
        grid.addWidget(self.recent_card, 1, 0)

        # Quick actions
        actions = Card("Acciones rápidas")
        for text, ic, target in (("Transferir archivos", "calculator", "calculator"),
                                 ("Abrir un documento .tns", "open", "editor:open"),
                                 ("Nuevo documento Lua", "new", "editor:new"),
                                 ("Archivos locales", "folder", "local")):
            b = QPushButton(icon(ic), text)
            b.setStyleSheet("text-align: left; padding: 9px 14px;")
            b.clicked.connect(lambda _=False, t=target: self.navigate.emit(t))
            actions.body.addWidget(b)
        actions.body.addStretch()
        grid.addWidget(actions, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(1, 1)

    def set_state(self, state: str, demo: bool = False) -> None:
        texts = {"connected": "Conectada", "busy": "Conectada (trabajando…)",
                 "connecting": "Conectando…", "disconnected": "No conectada"}
        self.conn_state.setText(texts.get(state, state) + (" · modo demostración" if demo else ""))
        self.connect_btn.setVisible(state == "disconnected")

    def set_device(self, info: DeviceInfo | None) -> None:
        if not info:
            self.model.setText("—")
            self.os.setText("")
            self.storage_lbl.setText("Almacenamiento: —")
            self.storage.setValue(0)
            self.ram_lbl.setText("")
            return
        self.model.setText(info.product_name or "TI-Nspire")
        self.os.setText(f"Sistema {info.os_version} · Boot2 {info.boot2_version} · "
                        f"Batería {'correcta' if info.battery_ok else 'baja'}")
        used = info.flash_total - info.flash_free
        self.storage_lbl.setText(f"Almacenamiento: {human_size(info.flash_free)} libres de {human_size(info.flash_total)}")
        self.storage.setMaximum(1000)
        self.storage.setValue(int(1000 * used / info.flash_total) if info.flash_total else 0)
        self.ram_lbl.setText(f"RAM: {human_size(info.ram_free)} libres de {human_size(info.ram_total)}")

    def set_recent(self, files: list[str]) -> None:
        self.recent.clear()
        for f in files:
            p = Path(f)
            it = QListWidgetItem(icon("file"), p.name)
            it.setToolTip(f)
            it.setData(Qt.UserRole, f)
            if not p.exists():
                it.setText(f"{p.name} (no encontrado)")
            self.recent.addItem(it)
        if not files:
            it = QListWidgetItem("Aún no has abierto documentos")
            it.setFlags(Qt.NoItemFlags)
            self.recent.addItem(it)
