"""Light and dark themes as Qt style sheets built from colour tokens."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

TOKENS = {
    "light": dict(bg="#f4f6f8", surface="#ffffff", surface2="#eef1f4", sidebar="#ffffff",
                  border="#dde2e8", text="#1c2430", muted="#5f6b7a", accent="#0f8b8d",
                  accent_text="#ffffff", accent_soft="#d7efef", danger="#c2410c",
                  ok="#15803d", warn="#b45309", selection="#cfe9e9"),
    "dark": dict(bg="#14181d", surface="#1c2128", surface2="#232a33", sidebar="#181d23",
                 border="#2e3742", text="#e6ebf1", muted="#97a3b2", accent="#2bb3b1",
                 accent_text="#0b1215", accent_soft="#173a3b", danger="#f97352",
                 ok="#4ade80", warn="#fbbf24", selection="#1f4a4b"),
}


def resolve(mode: str) -> str:
    if mode in TOKENS:
        return mode
    scheme = QGuiApplication.styleHints().colorScheme()
    return "dark" if scheme == Qt.ColorScheme.Dark else "light"


def stylesheet(t: dict) -> str:
    return f"""
* {{ font-size: 10.5pt; }}
QMainWindow, QWidget#Page, QStackedWidget {{ background: {t['bg']}; color: {t['text']}; }}
QWidget {{ color: {t['text']}; }}
QLabel[role="muted"] {{ color: {t['muted']}; }}
QLabel[role="title"] {{ font-size: 17pt; font-weight: 600; }}
QLabel[role="h2"] {{ font-size: 12pt; font-weight: 600; }}
QLabel[role="big"] {{ font-size: 15pt; font-weight: 600; }}
QFrame#TopBar {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
QLabel#AppName {{ font-size: 12.5pt; font-weight: 700; }}
QLabel#AppVersion {{ color: {t['muted']}; }}
QLabel#Pill {{ border-radius: 11px; padding: 3px 12px; font-weight: 600; }}
QLabel#Pill[state="on"] {{ background: {t['accent_soft']}; color: {t['accent']}; }}
QLabel#Pill[state="off"] {{ background: {t['surface2']}; color: {t['muted']}; }}
QLabel#Pill[state="busy"] {{ background: {t['surface2']}; color: {t['warn']}; }}
QListWidget#Sidebar {{ background: {t['sidebar']}; border: none; border-right: 1px solid {t['border']};
    padding: 10px 8px; outline: 0; }}
QListWidget#Sidebar::item {{ padding: 9px 12px; border-radius: 8px; margin: 2px 0; color: {t['muted']}; }}
QListWidget#Sidebar::item:hover {{ background: {t['surface2']}; color: {t['text']}; }}
QListWidget#Sidebar::item:selected {{ background: {t['accent_soft']}; color: {t['accent']}; font-weight: 600; }}
QFrame#Card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
QPushButton {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px;
    padding: 6px 14px; }}
QPushButton:hover {{ border-color: {t['accent']}; }}
QPushButton:pressed {{ background: {t['surface2']}; }}
QPushButton:disabled {{ color: {t['muted']}; background: {t['surface2']}; }}
QPushButton[kind="primary"] {{ background: {t['accent']}; color: {t['accent_text']}; border: none; font-weight: 600; }}
QPushButton[kind="primary"]:disabled {{ background: {t['surface2']}; color: {t['muted']}; }}
QPushButton[kind="danger"] {{ color: {t['danger']}; }}
QToolBar {{ background: transparent; border: none; spacing: 6px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 7px; padding: 5px 8px; }}
QToolButton:hover {{ background: {t['surface2']}; border-color: {t['border']}; }}
QToolButton:disabled {{ color: {t['muted']}; }}
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit, QTreeView, QTreeWidget, QTableView, QListView {{
    background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px;
    selection-background-color: {t['selection']}; selection-color: {t['text']}; }}
QLineEdit, QComboBox {{ padding: 5px 8px; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {t['accent']}; }}
QHeaderView::section {{ background: {t['surface2']}; color: {t['muted']}; border: none;
    border-bottom: 1px solid {t['border']}; padding: 5px 8px; }}
QTreeView::item, QTreeWidget::item {{ padding: 3px 2px; }}
QProgressBar {{ background: {t['surface2']}; border: none; border-radius: 5px; height: 10px; text-align: center; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 5px; }}
QStatusBar {{ background: {t['surface']}; border-top: 1px solid {t['border']}; color: {t['muted']}; }}
QSplitter::handle {{ background: {t['border']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: 8px; background: {t['surface']}; }}
QTabBar::tab {{ padding: 6px 14px; color: {t['muted']}; border: none; }}
QTabBar::tab:selected {{ color: {t['accent']}; border-bottom: 2px solid {t['accent']}; }}
QFrame#Toast {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
QFrame#Toast[level="error"] {{ border-left: 4px solid {t['danger']}; }}
QFrame#Toast[level="ok"] {{ border-left: 4px solid {t['ok']}; }}
QFrame#Toast[level="info"] {{ border-left: 4px solid {t['accent']}; }}
QFrame#DropZone {{ border: 2px dashed {t['accent']}; border-radius: 12px; background: {t['accent_soft']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QMenu {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['accent']}; }}
"""


def apply(app: QApplication, mode: str) -> dict:
    name = resolve(mode)
    t = TOKENS[name]
    pal = app.palette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "surface"), (QPalette.AlternateBase, "surface2"),
                      (QPalette.Text, "text"), (QPalette.WindowText, "text"), (QPalette.Button, "surface"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "selection"),
                      (QPalette.HighlightedText, "text"), (QPalette.PlaceholderText, "muted"),
                      (QPalette.ToolTipBase, "surface"), (QPalette.ToolTipText, "text")):
        pal.setColor(role, QColor(t[key]))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(t))
    return t
