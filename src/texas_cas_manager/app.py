"""Application entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .config import APP_ID, APP_NAME, Settings, setup_logging


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    logfile = setup_logging()
    logging.getLogger(APP_ID).info("%s %s (registro en %s)", APP_NAME, __version__, logfile)
    app = QApplication(argv)
    translator = QTranslator(app)
    if translator.load(QLocale.system(), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(QIcon.fromTheme("accessories-calculator"))
    from .ui.main_window import MainWindow

    win = MainWindow(Settings.load())
    win.show()
    for arg in argv[1:]:
        if arg.lower().endswith((".tns", ".lua")):
            win.open_document(arg)
            break
    return app.exec()
