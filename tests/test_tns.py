"""Container, encryption and Lua documents."""

import os
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import FIXTURES

from texas_cas_manager.tns import container, doccrypt, inspect, lua
from texas_cas_manager.tns.container import METHOD_DEFLATED, TnsEntry, TnsFormatError
from texas_cas_manager.tns.edit import compare_components, rebuild, text_diff
from texas_cas_manager.tns.extract import export_resources

HELLO = (FIXTURES / "hello.lua").read_text(encoding="utf-8")
LUNA_REF = (FIXTURES / "hello_luna.tns").read_bytes()  # produced by Luna 2.1 from hello.lua


def test_build_is_byte_identical_to_luna():
    assert lua.build_lua_document(HELLO) == LUNA_REF


def test_luna_document_parses_and_roundtrips():
    doc = container.parse(LUNA_REF)
    assert doc.version == "0500"
    assert doc.names() == ["Document.xml", "Problem1.xml"]
    assert container.write(doc) == LUNA_REF


def test_script_read_back_handles_cdata_end_and_unicode():
    src = 'x = "]]>" .. "ñandú €" -- ]]><![CDATA[ literal\n'
    data = lua.build_lua_document(src)
    assert lua.read_script(container.parse(data)) == src


def test_bom_is_dropped():
    data = lua.build_lua_document("\ufeffprint(1)\n")
    assert lua.read_script(container.parse(data)) == "print(1)\n"


def test_doccrypt_is_symmetric_and_periodic():
    data = os.urandom(20000)
    assert doccrypt.crypt(doccrypt.crypt(data)) == data
    ks = doccrypt.crypt(bytes(16384))
    assert ks[:8192] == ks[8192:]  # counter wraps after 1024 blocks


def _doc_with_resource() -> bytes:
    base = container.parse(lua.build_lua_document(HELLO))
    bmp = TnsEntry(name="IMG.BMP", method=METHOD_DEFLATED, raw=b"", crc32=0, uncompressed_size=0,
                   name_bytes=b"IMG.BMP").with_payload(b"BM" + bytes(range(256)) * 4)
    base.entries.append(bmp)
    return container.write(base)


def test_plain_entries_are_extracted_with_crc_check():
    doc = container.parse(_doc_with_resource())
    assert doc.entry("IMG.BMP").payload().startswith(b"BM")
    broken = replace(doc.entry("IMG.BMP"), crc32=1)
    with pytest.raises(TnsFormatError):
        broken.payload()


def test_replace_script_keeps_other_entries_byte_for_byte():
    original = _doc_with_resource()
    new = rebuild(original, "print('nuevo')\n")
    changes = {c.name: c.status for c in compare_components(original, new)}
    assert changes == {"Document.xml": "igual", "Problem1.xml": "modificado", "IMG.BMP": "igual"}
    assert lua.read_script(container.parse(new)) == "print('nuevo')\n"
    assert inspect.validate_bytes(new) == []


def test_unknown_key_documents_are_not_rewritten():
    doc = container.parse(LUNA_REF)
    p = doc.entry("Problem1.xml")
    doc.replace_entry(replace(p, raw=b"\x0f\xce\xd8\xd2\x81\x06\x86\x5b" + bytes(32) + p.raw[40:]))
    data = container.write(doc)
    rep = inspect.analyze(data)
    assert rep.lua_script is None and "desconocida" in rep.lua_status
    with pytest.raises(doccrypt.UnknownKeyError):
        rebuild(data, "print(1)")


@pytest.mark.parametrize("data,msg", [
    (b"PK\x03\x04" + bytes(40), "TIMLP"),
    (LUNA_REF[:-30], "end of central directory"),
    (LUNA_REF[:200] + LUNA_REF[400:], "central directory|local header|truncated"),
])
def test_corrupt_input_raises(data, msg):
    with pytest.raises(TnsFormatError, match=msg):
        container.parse(data)


def test_truncated_document_is_reported_by_validation():
    assert inspect.validate_bytes(LUNA_REF[:-1])


def test_new_document_rebuild_and_diff():
    data = rebuild(None, HELLO)
    assert data == LUNA_REF
    assert "+print" in text_diff("", "print(1)\n")


def test_export_resources(tmp_path):
    src = tmp_path / "doc.tns"
    src.write_bytes(_doc_with_resource())
    written = {p.name for p in export_resources(src, tmp_path / "out")}
    assert {"IMG.BMP", "Problem1.xml.tixc", "script.lua"} <= written
    assert (tmp_path / "out" / "script.lua").read_text(encoding="utf-8") == HELLO
    assert src.read_bytes() == _doc_with_resource()  # original untouched


SAMPLES = os.environ.get("TCM_SAMPLES")


@pytest.mark.skipif(not SAMPLES, reason="set TCM_SAMPLES to a folder of real .tns files")
def test_real_documents_roundtrip_identically():
    files = sorted(Path(SAMPLES).glob("*.tns"))
    assert files
    for f in files:
        data = f.read_bytes()
        rep = inspect.analyze(data)
        assert rep.roundtrip_identical, f
        assert not rep.problems, (f, rep.problems)
