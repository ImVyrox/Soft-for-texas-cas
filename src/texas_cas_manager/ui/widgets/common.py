"""Small shared widgets: cards, icons, toasts, size formatting."""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QMessageBox, QStyle, QVBoxLayout, QWidget)

# Freedesktop icon names (Breeze on KDE) with a Qt standard icon as fallback.
_ICONS = {
    "home": ("go-home", QStyle.SP_DirHomeIcon),
    "calculator": ("accessories-calculator", QStyle.SP_DriveHDIcon),
    "folder": ("folder", QStyle.SP_DirIcon),
    "folder-new": ("folder-new", QStyle.SP_FileDialogNewFolder),
    "file": ("text-x-generic", QStyle.SP_FileIcon),
    "editor": ("document-edit", QStyle.SP_FileDialogDetailedView),
    "tools": ("tools", QStyle.SP_FileDialogContentsView),
    "settings": ("configure", QStyle.SP_FileDialogInfoView),
    "refresh": ("view-refresh", QStyle.SP_BrowserReload),
    "download": ("download", QStyle.SP_ArrowDown),
    "upload": ("upload-media", QStyle.SP_ArrowUp),
    "delete": ("edit-delete", QStyle.SP_TrashIcon),
    "rename": ("edit-rename", QStyle.SP_FileDialogDetailedView),
    "open": ("document-open", QStyle.SP_DialogOpenButton),
    "save": ("document-save-as", QStyle.SP_DialogSaveButton),
    "new": ("document-new", QStyle.SP_FileIcon),
    "copy": ("edit-copy", QStyle.SP_FileLinkIcon),
    "check": ("dialog-ok-apply", QStyle.SP_DialogApplyButton),
    "diff": ("document-compare", QStyle.SP_FileDialogContentsView),
    "export": ("document-export", QStyle.SP_DialogSaveButton),
    "import": ("document-import", QStyle.SP_DialogOpenButton),
    "build": ("run-build", QStyle.SP_MediaPlay),
    "connect": ("network-connect", QStyle.SP_DriveNetIcon),
    "info": ("dialog-information", QStyle.SP_MessageBoxInformation),
    "edit-undo": ("edit-undo", QStyle.SP_ArrowBack),
    "edit-redo": ("edit-redo", QStyle.SP_ArrowForward),
}


def icon(name: str) -> QIcon:
    theme_name, fallback = _ICONS.get(name, (name, QStyle.SP_FileIcon))
    ic = QIcon.fromTheme(theme_name)
    return ic if not ic.isNull() else QApplication.style().standardIcon(fallback)


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if role:
        lab.setProperty("role", role)
    lab.setWordWrap(wrap)
    return lab


class Card(QFrame):
    def __init__(self, title: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(8)
        if title:
            self.body.addWidget(label(title, "h2"))


def confirm(parent: QWidget, title: str, text: str, danger: bool = False) -> bool:
    box = QMessageBox(QMessageBox.Warning if danger else QMessageBox.Question, title, text,
                      QMessageBox.Yes | QMessageBox.Cancel, parent)
    box.setDefaultButton(QMessageBox.Cancel)
    return box.exec() == QMessageBox.Yes


class Toast(QFrame):
    """Transient notification in the bottom-right corner of its parent."""

    def __init__(self, parent: QWidget, text: str, level: str = "info", ms: int = 4500):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("level", level)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setMaximumWidth(380)
        lay.addWidget(lab)
        self.adjustSize()
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self.show()
        self.raise_()
        self._anim.start()
        QTimer.singleShot(ms, self._fade_out)

    def _fade_out(self) -> None:
        self._anim.setDirection(QPropertyAnimation.Backward)
        self._anim.finished.connect(self.deleteLater)
        self._anim.start()


class ToastHost:
    """Stacks toasts on a widget; call ``reposition`` on resize."""

    def __init__(self, host: QWidget):
        self.host = host
        self.toasts: list[Toast] = []

    def show(self, text: str, level: str = "info") -> None:
        t = Toast(self.host, text, level)
        t.destroyed.connect(lambda *_: self._remove(t))
        self.toasts.append(t)
        self.reposition()

    def _remove(self, t) -> None:
        if t in self.toasts:
            self.toasts.remove(t)
        self.reposition()

    def reposition(self) -> None:
        if not shiboken6.isValid(self.host):  # window already destroyed
            return
        y = self.host.height() - 44
        for t in reversed(self.toasts):
            try:
                t.adjustSize()
                y -= t.height() + 8
                t.move(self.host.width() - t.width() - 20, y)
            except RuntimeError:  # already deleted by Qt
                pass


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: palette(mid);")
    return f


ALIGN_TOP = Qt.AlignTop
