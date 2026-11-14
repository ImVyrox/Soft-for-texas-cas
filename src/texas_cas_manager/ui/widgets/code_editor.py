"""Plain-text code editor with line numbers and Lua syntax highlighting."""

from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextFormat
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

LUA_KEYWORDS = (
    "and break do else elseif end false for function goto if in local nil not or "
    "repeat return then true until while"
).split()
# TI-Nspire Lua API tables (TI-Nspire Lua Scripting API reference).
NSPIRE_GLOBALS = "on platform gc timer var cursor toolpalette image D2Editor math string table class require".split()


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    f.setFontItalic(italic)
    return f


class LuaHighlighter(QSyntaxHighlighter):
    """Keywords, TI globals, numbers, strings and comments (incl. long comments)."""

    COLORS = {
        "light": dict(kw="#7c3aed", glob="#0f8b8d", num="#b45309", str="#15803d", com="#8a94a3", fn="#1d4ed8"),
        "dark": dict(kw="#c4a5ff", glob="#4fd1cf", num="#fbbf24", str="#86efac", com="#6b7685", fn="#93c5fd"),
    }

    def __init__(self, document, theme: str = "light"):
        super().__init__(document)
        self.set_theme(theme)

    def set_theme(self, theme: str) -> None:
        c = self.COLORS.get(theme, self.COLORS["light"])
        self.rules = [
            (re.compile(r"\b(" + "|".join(LUA_KEYWORDS) + r")\b"), _fmt(c["kw"], bold=True)),
            (re.compile(r"\b(" + "|".join(NSPIRE_GLOBALS) + r")\b"), _fmt(c["glob"])),
            (re.compile(r"\b[A-Za-z_]\w*(?=\s*\()"), _fmt(c["fn"])),
            (re.compile(r"\b(0x[0-9A-Fa-f]+|\d+\.?\d*([eE][-+]?\d+)?)\b"), _fmt(c["num"])),
            (re.compile(r"\"(\\.|[^\"\\])*\"|'(\\.|[^'\\])*'"), _fmt(c["str"])),
        ]
        self.comment = _fmt(c["com"], italic=True)
        self.long_string = _fmt(c["str"])
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt API)
        for rx, fmt in self.rules:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
        # Block state 1: inside --[[ ]] comment, 2: inside [[ ]] string.
        self.setCurrentBlockState(0)
        pos = 0
        state = self.previousBlockState()
        while pos <= len(text):
            if state in (1, 2):
                end = text.find("]]", pos)
                fmt = self.comment if state == 1 else self.long_string
                if end < 0:
                    self.setFormat(pos, len(text) - pos, fmt)
                    self.setCurrentBlockState(state)
                    return
                self.setFormat(pos, end + 2 - pos, fmt)
                pos, state = end + 2, 0
                continue
            m = re.compile(r"--\[\[|--|\[\[").search(text, pos)
            if not m:
                return
            if m.group() == "--":
                if not self._in_string(text, m.start()):
                    self.setFormat(m.start(), len(text) - m.start(), self.comment)
                    return
                pos = m.end()
                continue
            state = 1 if m.group() == "--[[" else 2
            self.setFormat(m.start(), m.end() - m.start(), self.comment if state == 1 else self.long_string)
            pos = m.end()

    @staticmethod
    def _in_string(text: str, idx: int) -> bool:
        quote = None
        i = 0
        while i < idx:
            ch = text[i]
            if quote:
                if ch == "\\":
                    i += 1
                elif ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            i += 1
        return quote is not None


class _Gutter(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self.editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None, theme: str = "light"):
        super().__init__(parent)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSizeF(11)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 2)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.gutter = _Gutter(self)
        self.highlighter = LuaHighlighter(self.document(), theme)
        self._theme = theme
        self.blockCountChanged.connect(lambda _: self.setViewportMargins(self.gutter_width(), 0, 0, 0))
        self.updateRequest.connect(self._on_update)
        self.cursorPositionChanged.connect(self._highlight_line)
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.highlighter.set_theme(theme)
        self._highlight_line()

    def gutter_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def _on_update(self, rect, dy) -> None:
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event) -> None:
        dark = self._theme == "dark"
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor("#1a1f26" if dark else "#f1f4f7"))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        current = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            bottom = top + round(self.blockBoundingRect(block).height())
            if block.isVisible() and bottom >= event.rect().top():
                n = block.blockNumber()
                painter.setPen(QColor("#e6ebf1" if dark else "#1c2430") if n == current
                               else QColor("#5b6675" if dark else "#9aa4b1"))
                painter.drawText(0, top, self.gutter.width() - 8, self.fontMetrics().height(),
                                 Qt.AlignRight, str(n + 1))
            block = block.next()
            top = bottom

    def _highlight_line(self) -> None:
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor("#20262e" if self._theme == "dark" else "#f3f7f9"))
        sel.format.setProperty(QTextFormat.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])
