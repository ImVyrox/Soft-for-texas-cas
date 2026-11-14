"""Phase 3: native documents, TIEN headers, TIXC, analysis, extraction, rebuild."""

import hashlib
import os
import zlib
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import FIXTURES
from native_fixture import DOCUMENT_XML, SCRIPT, native_document, problem_xml

from texas_cas_manager.tns import container, inspect, lua, tien, tixc, xmldoc
from texas_cas_manager.tns._luna_data import DOCCRYPT_IVEC_BASE, DOCCRYPT_KEYS, TIEN_CRYPTED_HEADER
from texas_cas_manager.tns.edit import RebuildError, compare_documents, rebuild
from texas_cas_manager.tns.extract import export_resources

LUNA_REF = (FIXTURES / "hello_luna.tns").read_bytes()
HELLO = (FIXTURES / "hello.lua").read_text(encoding="utf-8")


# --- signature / header --------------------------------------------------------------

def test_signature_detection():
    assert container.is_tns(LUNA_REF) and container.is_tns(native_document())
    assert not container.is_tns(b"PK\x03\x04" + bytes(20))
    assert container.parse(native_document()).version == "0601"


def test_luna_header_decrypts_to_lunas_keys_and_seed():
    h = tien.parse(TIEN_CRYPTED_HEADER)
    assert h.block_size == 0x400 and h.seed == DOCCRYPT_IVEC_BASE
    assert h.keys == tuple(DOCCRYPT_KEYS)  # two independent sources agree
    assert tien.build(h) == TIEN_CRYPTED_HEADER


def test_header_build_parse_roundtrip_and_rejects_garbage():
    h = tien.TienHeader(0x400, 0x12345678, os.urandom(21))
    assert tien.parse(tien.build(h)) == h
    with pytest.raises(tien.HeaderError):
        tien.parse(bytes(40))
    with pytest.raises(tien.HeaderError):
        tien.parse(b"short")


# --- sections, decompression, decryption ----------------------------------------------

def test_native_document_sections_and_counts():
    rep = inspect.analyze(native_document())
    assert [e.name for e in rep.entries] == ["Document.xml", "Problem1.xml", "A1B2.BMP"]
    assert (len(rep.entries), rep.xml_blocks, rep.compressed_blocks, rep.encrypted_blocks) == (3, 2, 3, 2)
    assert len(rep.resources) == 1 and rep.resources[0].kind == "Imagen"
    assert rep.origin.startswith("nativo") and rep.interpretation == inspect.FULL
    assert all(e.metadata == xmldoc.META_FINAL for e in rep.entries if e.encrypted)
    assert {e.header for e in rep.entries if e.encrypted} == {"propia del documento"}
    assert rep.roundtrip_identical and rep.valid


def test_decryption_gives_back_the_exact_xml():
    doc = container.parse(native_document())
    assert xmldoc.decode_entry(doc.entry("Document.xml"))[1] == DOCUMENT_XML
    assert xmldoc.decode_entry(doc.entry("Problem1.xml"))[1] == problem_xml()


def test_luna_documents_use_legacy_metadata():
    rep = inspect.analyze(LUNA_REF)
    assert [e.metadata for e in rep.entries] == [xmldoc.META_LEGACY] * 2
    assert rep.origin.startswith("Luna")


def test_protected_entry_is_reported_not_guessed():
    doc = container.parse(native_document())
    p = doc.entry("Problem1.xml")
    doc.replace_entry(replace(p, raw=os.urandom(40) + p.raw[40:]))
    rep = inspect.analyze(container.write(doc))
    entry = next(e for e in rep.entries if e.name == "Problem1.xml")
    assert not entry.readable and entry.status.startswith("protegido")
    assert rep.interpretation == inspect.PARTIAL and rep.scripts == []
    other = next(e for e in rep.entries if e.name == "Document.xml")
    assert other.readable  # the rest is still interpretable


def test_corrupt_encrypted_body_is_detected():
    doc = container.parse(native_document())
    p = doc.entry("Problem1.xml")
    body = bytearray(p.raw)
    body[60] ^= 0xFF
    doc.replace_entry(replace(p, raw=bytes(body)))
    rep = inspect.analyze(container.write(doc))
    entry = next(e for e in rep.entries if e.name == "Problem1.xml")
    assert entry.status.startswith("error") and not rep.valid


def test_truncated_and_unknown_data():
    data = native_document()
    with pytest.raises(container.TnsFormatError):
        container.parse(data[: len(data) // 2])
    doc = container.parse(data)
    doc.entries.append(container.TnsEntry(name="datos.bin", method=0, raw=b"\x00\x01", crc32=zlib.crc32(b"\x00\x01"),
                                          uncompressed_size=2, name_bytes=b"datos.bin"))
    doc.entries.append(container.TnsEntry(name="raro.dat", method=99, raw=b"xyz", crc32=0, uncompressed_size=3,
                                          name_bytes=b"raro.dat"))
    rep = inspect.analyze(container.write(doc))
    by = {e.name: e for e in rep.entries}
    assert by["datos.bin"].readable and by["datos.bin"].kind == "Recurso"
    assert not by["raro.dat"].readable and "0x63" in by["raro.dat"].status


# --- XML / Lua reading -------------------------------------------------------------------

def test_xml_properties_widgets_variables_scripts():
    rep = inspect.analyze(native_document())
    assert rep.properties["properties.swver"].strip() == "6.3.0.119 SE CAS Win"
    assert rep.properties["settings.lang"] == "es"
    info = rep.problems_info[0]
    assert info.widgets == [("TI.ScriptApp", "1.0"), ("TI.Notepad", "2.0")]
    assert info.variables == [("reloj", "{}")]
    s = rep.scripts[0]
    assert (s.title, s.version, s.protected, s.source) == ("Reloj", "34013703", False, SCRIPT)
    assert "TI.Notepad" in rep.kind and "TI.ScriptApp" in rep.kind


def test_lua_reading_on_both_kinds():
    assert lua.read_script(container.parse(LUNA_REF)) == HELLO
    assert lua.read_script(container.parse(native_document())) == SCRIPT


# --- TIXC ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "plain ascii and some long words with etaoin letters",
    "digits 0123456789 3.14159 (x+1)*[y-2]",
    "acentos ñ á é — € 日本 😀 mixtos",
    "<![CDATA[ if a < b and c ]]> fuera",
])
def test_tixc_roundtrip(text):
    escaped = text.replace("&", "&amp;") if "CDATA" in text else text.replace("&", "&amp;").replace("<", "&lt;")
    xml = (b'<?xml version="1.0" encoding="UTF-8" ?><r a="v &quot;1&quot;"><t x="1">'
           + escaped.encode() + b"</t><t/><t x=\"2\">otra</t></r>")
    assert tixc.decode(tixc.encode(xml)) == xml


@pytest.mark.parametrize("bad", [b"XXXX0100-1.0?><r></r>", b"TIXC0100-2.0?><r></r>", b"TIXC0100-1.0?><r>",
                                 b"TIXC0100-1.0?><r></x>", b"TIXC0100-1.0?>\x0e\x05"])
def test_tixc_rejects_malformed(bad):
    with pytest.raises(tixc.TixcError):
        tixc.decode(bad)


# --- extraction / rebuild ---------------------------------------------------------------

def test_extraction_never_touches_the_original(tmp_path):
    src = tmp_path / "nativo.tns"
    src.write_bytes(native_document())
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    names = {p.name for p in export_resources(src, tmp_path / "out")}
    assert {"Document.xml", "Problem1.xml", "Problem1.lua", "A1B2.BMP", "informe.txt"} <= names
    assert (tmp_path / "out" / "Problem1.lua").read_text(encoding="utf-8") == SCRIPT
    assert (tmp_path / "out" / "Problem1.xml").read_bytes() == problem_xml()
    assert "Estado: completamente interpretable" in (tmp_path / "out" / "informe.txt").read_text(encoding="utf-8")
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before
    with pytest.raises(FileExistsError):
        export_resources(src, tmp_path / "out")  # never into an existing folder


def test_native_rebuild_changes_only_the_script():
    original = native_document()
    new_script = "-- editado\nfunction on.paint(gc) gc:drawString(\"]]> ok\", 1, 1) end\n"
    data = rebuild(original, new_script)
    a, b = container.parse(original), container.parse(data)
    assert a.entry("Document.xml") == b.entry("Document.xml")
    assert a.entry("A1B2.BMP") == b.entry("A1B2.BMP")
    pa, pb = a.entry("Problem1.xml"), b.entry("Problem1.xml")
    assert pa.raw[:40] == pb.raw[:40]  # same TIEN header: same keys and seed
    new_xml = xmldoc.decode_entry(pb)[1]
    assert pb.crc32 == zlib.crc32(new_xml) and pb.uncompressed_size == len(new_xml)  # TI's convention kept
    assert lua.read_script(b) == new_script
    old_xml = xmldoc.decode_entry(pa)[1]
    # Only the script bytes differ in the XML.
    head = old_xml.index(b"<![CDATA[")
    assert new_xml[:head] == old_xml[:head]
    assert new_xml.endswith(old_xml[old_xml.index(b"]]></sc:script>") + 3:])
    cmp = compare_documents(original, data)
    assert [c.status for c in cmp.components] == ["igual", "modificado", "igual"]


def test_roundtrip_pipeline_equality_levels(tmp_path):
    """.tns -> analysis -> extraction -> rebuild -> validation, per document kind."""
    # Both rebuild byte-identically here: the synthetic native TIXC comes from our own encoder.
    # Documents saved by TI re-encode differently (structural equality, see the TCM_SAMPLES test).
    for i, (data, expected) in enumerate(((LUNA_REF, "igualdad byte a byte"),
                                          (native_document(), "igualdad byte a byte"))):
        rep = inspect.analyze(data)
        src = tmp_path / f"doc{i}.tns"
        src.write_bytes(data)
        out = tmp_path / f"out{i}"
        export_resources(src, out)
        script = (out / "Problem1.lua").read_text(encoding="utf-8")
        rebuilt = rebuild(data, script)
        assert inspect.validate_bytes(rebuilt) == []
        cmp = compare_documents(data, rebuilt)
        assert cmp.level == expected, (expected, cmp)
        assert cmp.content and cmp.verifiable
        assert inspect.analyze(rebuilt).scripts[0].source == rep.scripts[0].source


def test_equality_levels_structural_content_unverifiable():
    a = native_document(with_image=False)
    doc = container.parse(a)
    from native_fixture import encrypted_entry
    # Same XML under a different TIEN header: stored bytes differ, content is equal.
    doc.replace_entry(encrypted_entry("Problem1.xml", problem_xml()))
    b = container.write(doc)
    cmp = compare_documents(a, b)
    assert not cmp.byte_identical and cmp.level == "igualdad estructural"
    # Same content but a different container version: content equality only.
    doc.version = "0500"
    assert compare_documents(a, container.write(doc)).level == "igualdad de contenido"
    # A component that cannot be decoded on one side: not verifiable.
    p = doc.entry("Problem1.xml")
    doc.replace_entry(replace(p, raw=os.urandom(40) + p.raw[40:]))
    assert compare_documents(a, container.write(doc)).level == "reconstrucción no verificable"


def test_protected_script_is_not_modified():
    with pytest.raises(lua.ProtectedScriptError):
        rebuild(native_document(cry="1"), "print(1)")


def test_rebuild_refuses_documents_without_script():
    doc = container.parse(native_document())
    from native_fixture import encrypted_entry
    doc.replace_entry(encrypted_entry("Problem1.xml", problem_xml().replace(b"sc:script", b"sc:other")))
    with pytest.raises(lua.NotLuaDocumentError):
        rebuild(container.write(doc), "print(1)")


def test_sha256_in_report():
    data = native_document()
    assert inspect.analyze(data).sha256 == hashlib.sha256(data).hexdigest()
    assert "SHA-256: " + hashlib.sha256(data).hexdigest() in inspect.text_report("x.tns", inspect.analyze(data))


def test_rebuild_error_type_exported():
    assert issubclass(RebuildError, ValueError)


# --- optional: personal documents (never in Git) -----------------------------------------

SAMPLES = os.environ.get("TCM_SAMPLES")


@pytest.mark.skipif(not SAMPLES, reason="set TCM_SAMPLES to a folder of real .tns files")
def test_real_documents_decode_and_rebuild():
    for f in sorted(Path(SAMPLES).glob("*.tns")):
        data = f.read_bytes()
        rep = inspect.analyze(data)
        assert rep.roundtrip_identical and rep.valid, (f, rep.problems)
        for e in rep.entries:
            if e.encrypted:
                assert e.readable and e.metadata in (xmldoc.META_FINAL, xmldoc.META_LEGACY), (f, e)
        if rep.scripts and not rep.scripts[0].protected:
            cmp = compare_documents(data, rebuild(data, rep.scripts[0].source))
            assert cmp.content and cmp.level in ("igualdad byte a byte", "igualdad estructural"), (f, cmp.level)


# --- images ------------------------------------------------------------------------------

def _bmp16(masks, w=3, h=2, pixels=(0xF800, 0x07E0, 0x001F, 0xFFFF, 0x0000, 0xF81F)):
    import struct
    stride = ((w * 16 + 31) // 32) * 4
    rows = [pixels[i * w:(i + 1) * w] for i in range(h)]
    data = b"".join(struct.pack(f"<{w}H", *r).ljust(stride, b"\0") for r in reversed(rows))  # bottom-up
    header = struct.pack("<IiiHHIIiiII", 52, w, h, 1, 16, 3, len(data), 0, 0, 0, 0) + struct.pack("<III", *masks)
    off = 14 + len(header)
    return b"BM" + struct.pack("<IHHI", off + len(data), 0, 0, off) + header + data


@pytest.mark.parametrize("masks", [(0xF800, 0x07E0, 0x001F), (0xF8000000, 0x07E00000, 0x001F0000)])
def test_bmp16_decoder_standard_and_ti_shifted_masks(masks):
    from texas_cas_manager.tns import images
    w, h, rgb = images.decode_bmp16(_bmp16(masks))
    assert (w, h) == (3, 2)
    px = [tuple(rgb[i:i + 3]) for i in range(0, len(rgb), 3)]
    assert px == [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0), (255, 0, 255)]


def test_bmp16_decoder_rejects_other_layouts():
    from texas_cas_manager.tns import images
    with pytest.raises(images.UnsupportedImage):
        images.decode_bmp16(_bmp16((0x7C00, 0x03E0, 0x001F)))
    with pytest.raises(images.UnsupportedImage):
        images.decode_bmp16(b"PNG...")
