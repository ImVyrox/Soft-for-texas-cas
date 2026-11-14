"""Lua helpers for the editor: completion words and syntax check (no Qt here).

The syntax check runs ``luac5.1 -p`` (TI-Nspire scripts are Lua 5.1) when it
is installed; otherwise it reports that the check is unavailable instead of
pretending the code is valid.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

LUA_KEYWORDS = (
    "and break do else elseif end false for function if in local nil not or "
    "repeat return then true until while"
).split()
LUA_STDLIB = (
    "assert error ipairs next pairs pcall print select tonumber tostring type unpack xpcall "
    "math.abs math.ceil math.cos math.floor math.huge math.max math.min math.pi math.random "
    "math.sin math.sqrt math.tan string.byte string.char string.find string.format string.gmatch "
    "string.gsub string.len string.lower string.rep string.sub string.upper table.concat "
    "table.insert table.remove table.sort"
).split()
# TI-Nspire Lua API names commonly used in scripts (TI-Nspire Lua Scripting API Reference).
NSPIRE_API = (
    "on.paint on.resize on.timer on.charIn on.enterKey on.escapeKey on.tabKey on.arrowKey "
    "on.mouseDown on.mouseUp on.mouseMove on.activate on.deactivate on.construction on.create "
    "on.save on.restore on.backspaceKey on.clearKey on.contextMenu on.help "
    "gc:drawString gc:drawLine gc:drawRect gc:fillRect gc:drawArc gc:fillArc gc:drawPolyLine "
    "gc:fillPolygon gc:drawImage gc:setColorRGB gc:setFont gc:setPen gc:getStringWidth "
    "gc:getStringHeight gc:clipRect "
    "platform.window:invalidate platform.window:width platform.window:height platform.apilevel "
    "platform.isColorDisplay platform.withGC "
    "timer.start timer.stop timer.getMilliSecCounter var.recall var.store var.list var.monitor "
    "image.new cursor.set cursor.show cursor.hide toolpalette.register toolpalette.enable "
    "D2Editor.newRichText class"
).split()
_ERROR_RE = re.compile(r":(\d+): (.*)")


def completion_words(source: str = "") -> list[str]:
    """Static vocabulary plus identifiers already used in ``source``."""
    words = set(LUA_KEYWORDS) | set(LUA_STDLIB) | set(NSPIRE_API)
    words |= {w for w in re.findall(r"\b[A-Za-z_]\w{2,}\b", source)}
    return sorted(words, key=str.lower)


def find_luac() -> str | None:
    return shutil.which("luac5.1") or None


@dataclass(frozen=True)
class SyntaxResult:
    available: bool
    ok: bool
    line: int | None = None
    message: str = ""


def check_syntax(source: str, luac: str | None = None) -> SyntaxResult:
    luac = luac or find_luac()
    if not luac:
        return SyntaxResult(False, False, message="luac5.1 no está instalado: no se puede comprobar la sintaxis")
    fd, path = tempfile.mkstemp(suffix=".lua")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(source)
        proc = subprocess.run([luac, "-p", path], capture_output=True, text=True, timeout=20)
    finally:
        os.unlink(path)
    if proc.returncode == 0:
        return SyntaxResult(True, True, message="Sintaxis Lua 5.1 correcta")
    err = (proc.stderr or proc.stdout).strip().replace(path, "script")
    m = _ERROR_RE.search(err)
    return SyntaxResult(True, False, int(m.group(1)) if m else None, m.group(2) if m else err)


_OPENERS = re.compile(r"(\bthen|\bdo|\belse|\brepeat|\bfunction\b[^)]*\)|\{|\()\s*(--.*)?$")


def next_indent(line: str, unit: str = "  ") -> str:
    """Indentation for the line after ``line`` (keeps it, adds one level after a block opener)."""
    current = line[: len(line) - len(line.lstrip())]
    code = line.strip()
    if code.startswith("--"):
        return current
    return current + unit if _OPENERS.search(code) and not re.search(r"\bend\s*$", code) else current
