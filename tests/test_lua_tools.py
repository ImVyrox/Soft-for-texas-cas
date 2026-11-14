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


MESSY = """local function f(x)
if x > 1 then
return "a"
elseif x < 0 then
  return 'b'
else
for i=1,3 do x = x + i end
end
--[[ long
   comment ]]
local s = [[
  keep this
]]
return x
end
t = {
a = 1,
}
"""


def test_block_regions_and_functions():
    regions = lua_tools.block_regions(MESSY)
    assert regions == [(1, 15), (2, 8)]
    assert all(a < b for a, b in regions)
    assert lua_tools.functions(MESSY) == [("f", 1)]
    assert lua_tools.functions("obj.draw = function(gc) end\nfunction a:b() end") == [("obj.draw", 1), ("a:b", 2)]


def test_detect_indent_unit():
    assert lua_tools.detect_indent_unit("if a then\n    b()\n    if c then\n        d()\n    end\nend") == "    "
    assert lua_tools.detect_indent_unit("if a then\n\tb()\nend") == "\t"
    assert lua_tools.detect_indent_unit("x = 1") == "  "


def test_format_indents_and_keeps_long_strings():
    out = lua_tools.format_lua(MESSY, "  ").splitlines()
    assert out[1] == "  if x > 1 then" and out[2] == '    return "a"' and out[3] == "  elseif x < 0 then"
    assert out[5] == "  else" and out[7] == "  end" and out[13] == "  return x" and out[14] == "end"
    assert "  keep this" in out  # inside a long string: untouched


@pytest.mark.skipif(not lua_tools.find_luac(), reason="luac5.1 not installed")
def test_safe_format_keeps_bytecode_and_rejects_invalid():
    formatted = lua_tools.safe_format(MESSY)
    assert lua_tools.bytecode(formatted) == lua_tools.bytecode(MESSY)
    with pytest.raises(lua_tools.FormatError, match="sintaxis"):
        lua_tools.safe_format("function f(")


def test_ti_warnings():
    src = "local f = io.open('x')\nos.time()\ndofile('a')\nlocal io = 1\nprint(os)"
    assert [l for l, _ in lua_tools.ti_warnings(src)] == [1, 2, 3]
