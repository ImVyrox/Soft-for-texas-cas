"""Simulated calculator content for the demo mode (no USB involved)."""

from __future__ import annotations

from ..tns.lua import build_lua_document
from .link import MockLink

DEMO_SCRIPT = """-- Documento de demostración generado por Texas CAS Manager
function on.paint(gc)
  gc:setColorRGB(15, 139, 141)
  gc:drawString("Hola desde Texas CAS Manager", 20, 40)
end
"""


def demo_link() -> MockLink:
    doc = build_lua_document(DEMO_SCRIPT)
    return MockLink({
        "/Ejemplos/hola.tns": doc,
        "/Ejemplos/Lua/reloj.tns": build_lua_document('function on.paint(gc) gc:drawString(timer.getMilliSecCounter(), 10, 10) end\n'),
        "/demo.tns": doc,
    })
