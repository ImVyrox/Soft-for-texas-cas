"""Main window: top bar, side navigation, pages, status bar."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMainWindow, QStackedWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..config import APP_NAME, Settings
from . import theme
from .pages.calculator import CalculatorPage
from .pages.editor import EditorPage
from .pages.home import HomePage
from .pages.local_files import LocalFilesPage
from .pages.tools_settings import SettingsPage, ToolsPage
from .widgets.common import ToastHost, icon
from .workers import LinkService

PAGES = [("home", "Inicio", "home"), ("calculator", "Calculadora", "calculator"),
         ("local", "Archivos locales", "folder"), ("editor", "Editor .tns", "editor"),
         ("tools", "Herramientas", "tools"), ("settings", "Configuración", "settings")]


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)
        self.tokens = theme.apply(QApplication.instance(), settings.theme)
        theme_name = theme.resolve(settings.theme)

        self.service = LinkService(demo=settings.demo_mode, parent=self)
        self.service.auto_connect = settings.auto_connect

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._top_bar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        self.nav = QListWidget()
        self.nav.setObjectName("Sidebar")
        self.nav.setFixedWidth(220)
        self.nav.setIconSize(QSize(20, 20))
        body.addWidget(self.nav)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)

        self.home = HomePage()
        self.calc = CalculatorPage(self.service, settings)
        self.local = LocalFilesPage(settings)
        self.editor = EditorPage(settings, theme_name)
        self.tools = ToolsPage(settings)
        self.settings_page = SettingsPage(settings)
        self.pages = {"home": self.home, "calculator": self.calc, "local": self.local,
                      "editor": self.editor, "tools": self.tools, "settings": self.settings_page}
        for key, text, ic in PAGES:
            it = QListWidgetItem(icon(ic), text)
            it.setData(Qt.UserRole, key)
            self.nav.addItem(it)
            self.stack.addWidget(self.pages[key])
        self.nav.currentRowChanged.connect(self._switch)
        self.nav.setCurrentRow(0)
        self.setCentralWidget(central)

        self.conn_status = QLabel("")
        self.statusBar().addPermanentWidget(self.conn_status)
        self.toasts = ToastHost(central)

        # wiring
        self.service.state.connect(self._on_state)
        self.service.info.connect(self.home.set_device)
        self.service.message.connect(self.notify)
        self.home.navigate.connect(self.go)
        self.home.open_document.connect(self.open_document)
        self.home.connect_requested.connect(self.service.connect_link)
        for page in (self.local, self.editor, self.tools):
            page.message.connect(self.notify)
        self.local.open_document.connect(self.open_document)
        self.calc.open_document.connect(self.open_document)
        self.editor.opened.connect(self._remember)
        self.editor.send_to_calculator.connect(self._send_to_calculator)
        self.settings_page.changed.connect(self._settings_changed)
        self.home.set_recent(settings.recent)
        self._on_state("disconnected")
        self.service.start()

    def _top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(54)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)
        name = QLabel(APP_NAME)
        name.setObjectName("AppName")
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("AppVersion")
        lay.addWidget(name)
        lay.addWidget(ver)
        lay.addStretch()
        self.pill = QLabel()
        self.pill.setObjectName("Pill")
        lay.addWidget(self.pill, 0, Qt.AlignVCenter)
        return bar

    # -- navigation ------------------------------------------------------------

    def _switch(self, row: int) -> None:
        page = self.stack.widget(row)
        self.stack.setCurrentIndex(row)
        fx = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(fx)
        anim = QPropertyAnimation(fx, b"opacity", page)
        anim.setDuration(160)
        anim.setStartValue(0.4)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: page.setGraphicsEffect(None))
        anim.start()

    def go(self, target: str) -> None:
        key, _, action = target.partition(":")
        self.nav.setCurrentRow([p[0] for p in PAGES].index(key))
        if action == "open":
            self.editor.choose_file()
        elif action == "new":
            self.editor.new_document()

    def open_document(self, path: str) -> None:
        self.go("editor")
        self.editor.open_file(path)

    def _remember(self, path: str) -> None:
        self.settings.add_recent(path)
        self.settings.save()
        self.home.set_recent(self.settings.recent)

    def _send_to_calculator(self, path: str) -> None:
        if not self.service.connected:
            self.notify("error", "La calculadora no está conectada.")
            return
        self.go("calculator")
        self.calc.upload([path], "/")

    # -- state -----------------------------------------------------------------

    def _on_state(self, state: str) -> None:
        texts = {"connected": "● Conectada", "busy": "● Transfiriendo…", "connecting": "● Conectando…",
                 "disconnected": "○ Sin calculadora"}
        self.pill.setText(texts.get(state, state) + (" (demo)" if self.service.demo else ""))
        self.pill.setProperty("state", {"connected": "on", "busy": "busy", "connecting": "busy"}.get(state, "off"))
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)
        dev = self.service.device
        self.conn_status.setText(f"{dev.product_name} · OS {dev.os_version}" if dev and state != "disconnected"
                                 else "USB: sin conexión")
        self.home.set_state(state, self.service.demo)

    def notify(self, level: str, text: str) -> None:
        self.statusBar().showMessage(text.splitlines()[0], 8000)
        self.toasts.show(text, level)

    def _settings_changed(self) -> None:
        self.tokens = theme.apply(QApplication.instance(), self.settings.theme)
        self.editor.set_theme(theme.resolve(self.settings.theme))
        self.service.auto_connect = self.settings.auto_connect
        self.service.set_demo(self.settings.demo_mode)
        self.calc.set_local_root(self.settings.workspace)
        self.local.set_root(self.settings.workspace)
        self._on_state("disconnected" if not self.service.connected else "connected")

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self.toasts.reposition()

    def closeEvent(self, e) -> None:  # noqa: N802
        if self.editor.dirty and not self.editor._confirm_discard():
            e.ignore()
            return
        self.service.shutdown()
        super().closeEvent(e)
