"""Notes pages: reading, narrow text editing, preservation, rejection."""

import hashlib
import os
from pathlib import Path

import pytest
from native_fixture import MATH_BOX, notes_document, notes_problem_xml, problem_xml, word

from texas_cas_manager.tns import container, inspect, notes, xmldoc
from texas_cas_manager.tns.edit import compare_documents


def pages_of(data: bytes):
    return notes.document_pages(container.parse(data))


def test_reads_pages_runs_math_and_editability():
    p1, p2 = pages_of(notes_document())
    assert (p1.widget, p1.paragraphs, p2.paragraphs) == ("TI.Notepad", 2, 3)
    assert [(r.text, r.editable) for r in p1.runs] == [("hola", True), ("abc", True), ("", False)]
    assert p1.math == [notes.MathBox("2+3", "5")]
    assert [(r.text, r.editable) for r in p2.runs] == [("π", True), ("x", True), ("", False)]
    assert "elementos" in p2.runs[2].reason and "vacío" in p1.runs[2].reason


def test_edit_changes_only_the_run_and_its_length():
    data = notes_document()
    new = container.write(notes.edit_notes(container.parse(data), "Problem1.xml", 0, {0: "Hola ñandú 123"}))
    assert inspect.validate_bytes(new) == []
    p1, p2 = pages_of(new)
    assert [r.text for r in p1.runs] == ["Hola ñandú 123", "abc", ""]
    assert p1.math == [notes.MathBox("2+3", "5")] and [r.text for r in p2.runs] == ["π", "x", ""]
    old_xml = xmldoc.decode_entry(container.parse(data).entry("Problem1.xml"))[1]
    new_xml = xmldoc.decode_entry(container.parse(new).entry("Problem1.xml"))[1]
    assert new_xml == old_xml.replace(b"pp0=&quot;4&quot;&gt;hola&lt;", "pp0=&quot;14&quot;&gt;Hola ñandú 123&lt;".encode())
    cmp = compare_documents(data, new)
    assert [c.status for c in cmp.components] == ["igual", "modificado"]
    assert container.parse(data).entry("Problem1.xml").raw[:40] == container.parse(new).entry("Problem1.xml").raw[:40]


def test_several_edits_on_the_second_page():
    data = notes_document()
    new = container.write(notes.edit_notes(container.parse(data), "Problem1.xml", 1, {0: "π r", 1: "y"}))
    assert [r.text for r in pages_of(new)[1].runs] == ["π r", "y", ""]


@pytest.mark.parametrize("edits,msg", [
    ({2: "x"}, "no es editable"),  # empty run
    ({9: "x"}, "no existe"),
    ({0: "a<b"}, "no permitido"),
    ({0: 'say "hi"'}, "no permitido"),
    ({0: "日本"}, "no permitido"),
    ({0: ""}, "no permitido"),
])
def test_rejected_edits(edits, msg):
    with pytest.raises(notes.NotesError, match=msg):
        notes.edit_notes(container.parse(notes_document()), "Problem1.xml", 0, edits)


def test_multi_format_and_unverified_runs_are_read_only():
    data = notes_document([[word("ab", np="2"), word("a&amp;b")]])
    runs = pages_of(data)[0].runs
    assert not runs[0].editable and "formatos" in runs[0].reason
    assert runs[1].text == "a&b" and not runs[1].editable


def test_non_notes_pages_and_malformed_rich_text():
    assert pages_of(problem_xml_doc())[0].widget == "TI.ScriptApp"
    bad = notes_problem_xml([[word("ok")]]).replace(b"&lt;/r2dtotree&gt;", b"")
    page = notes.problem_pages("Problem1.xml", bad)[0]
    assert not page.readable and "no válido" in page.error
    with pytest.raises(notes.NotesError):
        notes.replace_texts(bad, 0, {0: "x"})


def problem_xml_doc():
    from native_fixture import encrypted_entry, DOCUMENT_XML
    return container.write(container.TnsDocument("0601", [encrypted_entry("Document.xml", DOCUMENT_XML),
                                                          encrypted_entry("Problem1.xml", problem_xml())]))


def test_math_box_attributes_survive():
    data = notes_document([[word("a") + MATH_BOX]])
    new = container.write(notes.edit_notes(container.parse(data), "Problem1.xml", 0, {0: "b"}))
    assert pages_of(new)[0].math == pages_of(data)[0].math


def test_original_bytes_untouched(tmp_path):
    data = notes_document()
    before = hashlib.sha256(data).hexdigest()
    notes.edit_notes(container.parse(data), "Problem1.xml", 0, {0: "x"})
    assert hashlib.sha256(data).hexdigest() == before


SAMPLES = os.environ.get("TCM_SAMPLES")


@pytest.mark.skipif(not SAMPLES, reason="set TCM_SAMPLES to a folder of real .tns files")
def test_real_notes_documents_edit_and_keep_structure():
    for f in sorted(Path(SAMPLES).glob("*.tns")):
        data = f.read_bytes()
        doc = container.parse(data)
        for page in notes.document_pages(doc):
            editable = [r for r in page.runs if r.editable]
            if not editable:
                continue
            new = container.write(notes.edit_notes(doc, page.problem, page.card, {editable[0].index: "TCM"}))
            assert inspect.validate_bytes(new) == [], f
            after = [p for p in notes.document_pages(container.parse(new)) if p.card == page.card][0]
            assert after.runs[editable[0].index].text == "TCM" and after.math == page.math


def test_apply_edits_scripts_and_notes_together():
    from native_fixture import encrypted_entry, DOCUMENT_XML
    from texas_cas_manager.tns.edit import apply_edits
    from texas_cas_manager.tns import lua
    doc = container.TnsDocument("0601", [encrypted_entry("Document.xml", DOCUMENT_XML),
                                         encrypted_entry("Problem1.xml", problem_xml()),
                                         encrypted_entry("Problem2.xml", notes_problem_xml())])
    data = container.write(doc)
    new = apply_edits(data, {("Problem1.xml", 0): "print(1)\n"}, {("Problem2.xml", 1): {1: "z"}})
    out = container.parse(new)
    assert lua.read_script(out) == "print(1)\n"
    pages2 = [p for p in notes.document_pages(out) if p.problem == "Problem2.xml"]
    assert pages2[1].runs[1].text == "z"
    assert container.parse(data).entry("Document.xml") == out.entry("Document.xml")


@pytest.mark.skipif(not SAMPLES, reason="set TCM_SAMPLES to a folder of real .tns files")
def test_real_notes_paragraph_insert_and_page_order():
    from texas_cas_manager.tns import pages
    from texas_cas_manager.tns.edit import apply_edits
    checked = 0
    for f in sorted(Path(SAMPLES).glob("*.tns")):
        data = f.read_bytes()
        doc = container.parse(data)
        for name in notes.problem_names(doc):
            xml = xmldoc.decode_entry(doc.entry(name))[1]
            for page in notes.problem_pages(name, xml):
                if not page.is_notes or not notes.structure_allowed(xml, page.card)[0]:
                    continue
                n = len(notes.page_paragraphs(xml, page.card))
                new = apply_edits(data, layouts={(name, page.card): list(range(n)) + ["TCM"]})
                paras = notes.page_paragraphs(xmldoc.decode_entry(container.parse(new).entry(name))[1], page.card)
                assert [p.text for p in paras][-1] == "TCM" and len(paras) == n + 1, f
                checked += 1
            n_cards = len(pages.problem_summaries(xml))
            if n_cards > 1:
                order = list(range(n_cards))[::-1]
                new = apply_edits(data, orders={name: order})
                assert [s.widget for s in pages.problem_summaries(xmldoc.decode_entry(
                    container.parse(new).entry(name))[1])] == [pages.problem_summaries(xml)[i].widget for i in order]
    assert checked
