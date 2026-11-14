"""Find / replace bar for a QPlainTextEdit (Ctrl+F, Ctrl+H)."""

from __future__ import annotations

import re

from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QWidget


class FindBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor: QPlainTextEdit | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        self.find = QLineEdit(placeholderText="Buscar…")
        self.replace = QLineEdit(placeholderText="Reemplazar por…")
        self.case = QCheckBox("Mayúsc./minúsc.")
        self.status = QLabel("")
        prev_b, next_b = QPushButton("↑"), QPushButton("↓")
        rep_b, all_b, close_b = QPushButton("Reemplazar"), QPushButton("Todo"), QPushButton("✕")
        for w in (self.find, prev_b, next_b, self.replace, rep_b, all_b, self.case, self.status, close_b):
            lay.addWidget(w)
        lay.setStretch(0, 2)
        lay.setStretch(3, 2)
        self.find.returnPressed.connect(lambda: self.search(True))
        next_b.clicked.connect(lambda: self.search(True))
        prev_b.clicked.connect(lambda: self.search(False))
        rep_b.clicked.connect(self.replace_one)
        all_b.clicked.connect(self.replace_all)
        close_b.clicked.connect(self.hide)
        self.hide()

    def attach(self, editor: QPlainTextEdit, with_replace: bool = True) -> None:
        self.editor = editor
        self.replace.setEnabled(with_replace and not editor.isReadOnly())

    def open(self, replace: bool = False) -> None:
        self.show()
        (self.replace if replace and self.replace.isEnabled() else self.find).setFocus()
        if self.editor and self.editor.textCursor().hasSelection():
            self.find.setText(self.editor.textCursor().selectedText())
        self.find.selectAll()

    def _flags(self, forward: bool):
        f = QTextDocument.FindFlag(0)
        if not forward:
            f |= QTextDocument.FindBackward
        if self.case.isChecked():
            f |= QTextDocument.FindCaseSensitively
        return f

    def search(self, forward: bool = True) -> bool:
        if not self.editor or not self.find.text():
            return False
        found = self.editor.find(self.find.text(), self._flags(forward))
        if not found:  # wrap around
            cursor = self.editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start if forward else cursor.MoveOperation.End)
            self.editor.setTextCursor(cursor)
            found = self.editor.find(self.find.text(), self._flags(forward))
        self.status.setText("" if found else "Sin resultados")
        return found

    def replace_one(self) -> None:
        if not self.editor or self.editor.isReadOnly():
            return
        cursor = self.editor.textCursor()
        same = (cursor.selectedText() == self.find.text() if self.case.isChecked()
                else cursor.selectedText().lower() == self.find.text().lower())
        if cursor.hasSelection() and same:
            cursor.insertText(self.replace.text())
        self.search(True)

    def replace_all(self) -> None:
        if not self.editor or self.editor.isReadOnly() or not self.find.text():
            return
        text = self.editor.toPlainText()
        pattern = re.compile(re.escape(self.find.text()), 0 if self.case.isChecked() else re.IGNORECASE)
        new, n = pattern.subn(lambda m: self.replace.text(), text)
        if n:
            cursor = self.editor.textCursor()
            cursor.beginEditBlock()  # a single undo step
            cursor.select(cursor.SelectionType.Document)
            cursor.insertText(new)
            cursor.endEditBlock()
        self.status.setText(f"{n} reemplazos")
