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


# ---------------------------------------------------------------------------- lexer

_TOKEN_RE = re.compile(
    r"""(?P<comment>--\[(?P<ceq>=*)\[.*?\](?P=ceq)\]|--[^\n]*)"""
    r"""|(?P<long>\[(?P<leq>=*)\[.*?\](?P=leq)\])"""
    r"""|(?P<str>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')"""
    r"""|(?P<name>[A-Za-z_]\w*)""", re.S)
_OPEN_KW = {"function", "do", "then", "repeat"}  # 'if'/'while'/'for' open via then/do
_CLOSE_KW = {"end", "until"}


def _code_tokens(source: str):
    """(name, start offset) of identifiers/keywords outside strings and comments."""
    for m in _TOKEN_RE.finditer(source):
        if m.lastgroup == "name":
            yield m.group("name"), m.start()


def _line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _block_events(source: str):
    """('open'|'close'|'mid', name, offset): block structure, with 'elseif ... then' as one middle part."""
    after_elseif = False
    for name, pos in _code_tokens(source):
        if name == "elseif":
            after_elseif = True
            yield "mid", name, pos
        elif name == "then" and after_elseif:
            after_elseif = False
        elif name == "else":
            yield "mid", name, pos
        elif name in _OPEN_KW:
            yield "open", name, pos
        elif name in _CLOSE_KW:
            yield "close", name, pos


def block_regions(source: str) -> list[tuple[int, int]]:
    """(first line, last line) of every multi-line block (function/do/then/repeat ... end/until), 1-based."""
    stack, regions = [], []
    for kind, _name, pos in _block_events(source):
        if kind == "open":
            stack.append(_line_of(source, pos))
        elif kind == "close" and stack:
            start, end = stack.pop(), _line_of(source, pos)
            if end > start:
                regions.append((start, end))
    return sorted(regions)


_FUNC_RE = re.compile(r"^[ \t]*(?:local[ \t]+)?function[ \t]+([\w.:]+)|^[ \t]*(?:local[ \t]+)?([\w.:]+)[ \t]*=[ \t]*function\b",
                      re.M)


def functions(source: str) -> list[tuple[str, int]]:
    """(name, line) of named function definitions, for navigation."""
    out = []
    for m in _FUNC_RE.finditer(source):
        out.append((m.group(1) or m.group(2), _line_of(source, m.start())))
    return out


# TI-Nspire Lua API Reference Guide, "Unimplemented libraries and functions".
UNAVAILABLE_LIBS = ("io", "os", "debug", "file")
UNAVAILABLE_FUNCS = ("dofile", "loadfile", "module")


def ti_warnings(source: str) -> list[tuple[int, str]]:
    """(line, message) for standard Lua APIs that TI-Nspire does not provide."""
    out = []
    for name, pos in _code_tokens(source):
        after = source[pos + len(name):pos + len(name) + 1]
        if (name in UNAVAILABLE_LIBS and after in (".", ":")) or name in UNAVAILABLE_FUNCS:
            out.append((_line_of(source, pos), f"«{name}» no está disponible en TI-Nspire"))
    return out


# ---------------------------------------------------------------------------- format

def _depth_changes(line: str) -> tuple[int, int]:
    """(levels to dedent this line, net depth change after it) for one line of code."""
    depth = lowest = 0
    for kind, _name, _pos in _block_events(line):
        if kind == "open":
            depth += 1
        elif kind == "close":
            depth -= 1
        else:  # else / elseif: this part sits one level out
            depth -= 1
            lowest = min(lowest, depth)
            depth += 1
            continue
        lowest = min(lowest, depth)
    return -lowest, depth


def detect_indent_unit(source: str) -> str:
    """The script's own indentation unit: a tab, or the most common step between indented lines."""
    lines = [ln for ln in source.split("\n") if ln.strip()]
    if sum(ln.startswith("\t") for ln in lines) > sum(ln.startswith(" ") for ln in lines):
        return "\t"
    steps: dict[int, int] = {}
    prev = 0
    for ln in lines:
        width = len(ln) - len(ln.lstrip(" "))
        if width > prev:
            steps[width - prev] = steps.get(width - prev, 0) + 1
        prev = width
    best = max(steps, key=steps.get) if steps else 2
    return " " * (best if best in (2, 3, 4, 8) else 2)


def format_lua(source: str, unit: str | None = None) -> str:
    """Re-indent code lines by block depth; lines inside long comments/strings are kept as they are."""
    unit = unit or detect_indent_unit(source)
    protected = set()
    for m in _TOKEN_RE.finditer(source):
        if m.lastgroup == "long" or (m.lastgroup == "comment" and m.group("comment").startswith("--[")):
            protected.update(range(_line_of(source, m.start()) + 1, _line_of(source, m.end()) + 1))
    depth, out = 0, []
    for no, line in enumerate(source.split("\n"), 1):
        if no in protected:
            out.append(line)
            continue
        code = line.strip()
        dedent, change = _depth_changes(code)
        out.append(unit * max(0, depth - dedent) + code if code else "")
        depth = max(0, depth + change)
    return "\n".join(out)


def bytecode(source: str, luac: str | None = None) -> bytes | None:
    """Stripped Lua 5.1 bytecode (no line info), or None if luac5.1 is missing or the code is invalid."""
    luac = luac or find_luac()
    if not luac:
        return None
    with tempfile.TemporaryDirectory() as d:
        src, out = os.path.join(d, "s.lua"), os.path.join(d, "s.luac")
        with open(src, "w", encoding="utf-8") as f:
            f.write(source)
        if subprocess.run([luac, "-s", "-o", out, src], capture_output=True, timeout=30).returncode:
            return None
        with open(out, "rb") as f:
            return f.read()


class FormatError(ValueError):
    pass


def safe_format(source: str, luac: str | None = None) -> str:
    """Formatted source, accepted only if luac5.1 compiles both to identical stripped bytecode."""
    luac = luac or find_luac()
    if not luac:
        raise FormatError("luac5.1 no está instalado: no se puede garantizar que el formato no cambie el código")
    before = bytecode(source, luac)
    if before is None:
        raise FormatError("el script tiene errores de sintaxis; corrígelos antes de formatear")
    formatted = format_lua(source)
    if bytecode(formatted, luac) != before:
        raise FormatError("el formato cambiaría el código compilado; no se aplica")
    return formatted
