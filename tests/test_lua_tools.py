"""Editor helpers: completion vocabulary, indentation, syntax check."""

import pytest

from texas_cas_manager.editor import lua_tools


def test_completion_includes_keywords_api_and_document_identifiers():
    words = lua_tools.completion_words("local miVariable = 1")
    assert {"function", "gc:drawString", "platform.window:invalidate", "miVariable"} <= set(words)


@pytest.mark.parametrize("line,expected", [
    ("if a then", "  "), ("  for i=1,3 do", "    "), ("function f(x)", "  "), ("x = 1", ""),
    ("  return", "  "), ("function f() return 1 end", ""), ("-- if comment then", ""), ("t = {", "  "),
])
def test_next_indent(line, expected):
    assert lua_tools.next_indent(line) == expected


@pytest.mark.skipif(not lua_tools.find_luac(), reason="luac5.1 not installed")
def test_syntax_check_with_luac():
    assert lua_tools.check_syntax("function f() return 1 end").ok
    bad = lua_tools.check_syntax("function f(\nreturn 1\nend")
    assert bad.available and not bad.ok and bad.line == 2


def test_syntax_check_reports_missing_luac(monkeypatch):
    monkeypatch.setattr(lua_tools, "find_luac", lambda: None)
    r = lua_tools.check_syntax("x=1")
    assert not r.available and not r.ok and "luac5.1" in r.message
