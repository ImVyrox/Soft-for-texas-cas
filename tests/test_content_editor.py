"""Phase 5: paragraphs, maths boxes, page types, page order, TIXC overflow, combined edits."""

import xml.etree.ElementTree as ET

import pytest
from native_fixture import (DOCUMENT_XML, MATH_SAMPLES, encrypted_entry, mbox, multi_page_xml, notes_document,
                            notes_problem_xml, word)

from texas_cas_manager.tns import container, inspect, mathbox, notes, pages, tixc, xmldoc
from texas_cas_manager.tns.edit import RebuildError, apply_edits, compare_documents


def problem_xml(data: bytes) -> bytes:
    return xmldoc.decode_entry(container.parse(data).entry("Problem1.xml"))[1]


# --- paragraphs -------------------------------------------------------------------------

def three_para_doc() -> bytes:
    return notes_document([[word("uno"), word("dos"), word("tres")], [word("otra página")]])


def test_paragraph_classification():
    data = notes_document([[word("uno"), word("abc") + mbox(el_text("4"), "4"), word("", children='<cursor index="0"/>')]])
    paras = notes.page_paragraphs(problem_xml(data), 0)
    assert [(p.kind, p.text) for p in paras] == [("text", "uno"), ("complex", "abc"), ("complex", "")]
    assert "matemáticos" in paras[1].reason and "cursor" in paras[2].reason


def el_text(s):
    return f'<leaf name="0text" np="1" id0="2" pp0="{len(s)}">{s}</leaf>'


@pytest.mark.parametrize("layout,expected", [
    ([0, "nuevo", 1, 2], ["uno", "nuevo", "dos", "tres"]),          # insert
    ([0, 2], ["uno", "tres"]),                                      # delete
    ([2, 1, 0], ["tres", "dos", "uno"]),                            # reorder
    (["UNO editado ñ", 1, 2], ["UNO editado ñ", "dos", "tres"]),    # replace text
    ([0, "", 1, 2], ["uno", "", "dos", "tres"]),                    # empty line (line break)
])
def test_set_paragraphs_text_only(layout, expected):
    data = three_para_doc()
    new = container.write(notes.edit_paragraphs(container.parse(data), "Problem1.xml", 0, layout))
    assert inspect.validate_bytes(new) == []
    paras = notes.page_paragraphs(problem_xml(new), 0)
    assert [p.text for p in paras] == expected and all(p.kind == "text" for p in paras)
    page = notes.document_pages(container.parse(new))[0]
    assert [r.text for r in page.runs] == expected  # pp0 consistent: runs stay editable
    assert all(r.editable for r in page.runs if r.text)
    # the second page and Document.xml are untouched
    assert notes.page_paragraphs(problem_xml(new), 1) == notes.page_paragraphs(problem_xml(data), 1)
    assert [c.status for c in compare_documents(data, new).components] == ["igual", "modificado"]


def test_complex_paragraphs_must_be_kept_in_order():
    data = notes_document([[word("a"), word("b") + mbox(el_text("4"), "4"), word("c"),
                            word("d") + mbox(el_text("5"), "5")]])
    doc = container.parse(data)
    for bad in ([0, 2, 3], [3, 1], [0, 1, 1, 3], [0, 9]):
        with pytest.raises(notes.NotesError):
            notes.edit_paragraphs(doc, "Problem1.xml", 0, bad)
    new = container.write(notes.edit_paragraphs(doc, "Problem1.xml", 0, [1, "x", 3]))
    paras = notes.page_paragraphs(problem_xml(new), 0)
    assert [(p.kind, p.text) for p in paras] == [("complex", "b"), ("text", "x"), ("complex", "d")]
    def spans(x):
        inner = notes._page_inner(x, 0)[2]
        return [inner[a:b] for a, b in notes._paragraph_spans(inner)[2]]
    old, now = spans(problem_xml(data)), spans(problem_xml(new))
    assert now[0] == old[1] and now[2] == old[3]  # complex paragraphs byte-identical


def test_structure_refused_when_format_zero_is_counted():
    xml = notes_problem_xml([[word("a")]]).replace(b"entryRefCnt=&quot;2147483647&quot;", b"entryRefCnt=&quot;4&quot;")
    ok, why = notes.structure_allowed(xml, 0)
    assert not ok and "contador" in why
    with pytest.raises(notes.NotesError):
        notes.set_paragraphs(xml, 0, [0, "b"])


@pytest.mark.parametrize("bad", ["a<b", 'x"y', "日本", "a&b"])
def test_new_paragraph_text_validated(bad):
    with pytest.raises(notes.NotesError):
        notes.set_paragraphs(problem_xml(three_para_doc()), 0, [0, bad])


def test_unexpected_escaping_is_refused():
    xml = notes_problem_xml([[word("a")]]).replace(b"&gt;", b">", 1)  # valid XML, but not TI's escaping
    with pytest.raises(notes.NotesError, match="escapado"):
        notes.page_paragraphs(xml, 0)


# --- maths boxes --------------------------------------------------------------------------

@pytest.mark.parametrize("tree,full,expected", MATH_SAMPLES)
def test_math_linear_forms(tree, full, expected):
    box = ET.fromstring(mbox(tree, full))
    info = mathbox.read_box(box)
    assert (info.input, info.output, info.unknown) == (expected, full, [])


def test_math_error_and_unknown_template():
    err_box = mbox(el_text("x"), None, err=140).replace(
        '<leaf name="0text" readonly="1" np="1" id0="3" pp0="1">r</leaf>',
        '<node name="0mline" id0="3">"<node name="0el" id0="3"><leaf name="0text" np="1" id0="3" pp0="5">Error</leaf>'
        '</node></node>')
    info = mathbox.read_box(ET.fromstring(err_box))
    assert info.error == 140 and info.output == '"Error"'
    weird = mathbox.read_box(ET.fromstring(mbox('<node name="0nuevo" id0="2">x</node>', "1")))
    assert weird.unknown == ["0nuevo"] and "?" in weird.input
    bad_frac = mathbox.read_box(ET.fromstring(mbox('<node name="0fraction" id0="2">((<node name="0el" id0="2"/></node>', "1")))
    assert bad_frac.unknown == ["0fraction con 1 partes"]


def test_math_boxes_are_read_only_and_preserved():
    data = notes_document([[word("a") + mbox(MATH_SAMPLES[0][0], "5/6")]])
    page = notes.document_pages(container.parse(data))[0]
    assert page.math[0].input == "(1)/(2)+(1)/(3)" and page.math[0].templates == ["0fraction", "0fraction"]
    new = container.write(notes.edit_notes(container.parse(data), "Problem1.xml", 0, {0: "b"}))
    assert notes.document_pages(container.parse(new))[0].math == page.math


# --- page types and order -----------------------------------------------------------------

def test_page_summaries_and_variables():
    xml = multi_page_xml()
    summaries = pages.problem_summaries(xml)
    assert [(s.widget, s.app) for s in summaries] == [
        ("TI.Notepad", "Notas"), ("TI.Scratchpad", "Calculadora"),
        ("tabulator", "Listas y hojas de cálculo"), ("TI.GeoGrapher", "Gráficos y geometría")]
    assert summaries[1].details == [("Entrada", "2+3  →  5")]
    assert summaries[2].details == [("Columna 1", "=datos; 1 celdas")]
    assert summaries[3].details == [("Objeto", "axis × 2"), ("Objeto", "point × 1")]
    assert pages.problem_variables(xml) == [("f1", "x", "x^2")]


def test_unknown_page_type():
    xml = multi_page_xml().replace(b'type="tabulator"', b'type="TI.Nuevo"')
    s = pages.problem_summaries(xml)[2]
    assert not s.understood and s.app == "desconocida"


def doc_with(xml: bytes) -> bytes:
    return container.write(container.TnsDocument("0601", [encrypted_entry("Document.xml", DOCUMENT_XML),
                                                          encrypted_entry("Problem1.xml", xml)]))


def test_reorder_pages_keeps_each_page_byte_for_byte():
    data = doc_with(multi_page_xml())
    new = container.write(pages.reorder_pages(container.parse(data), "Problem1.xml", [3, 0, 2, 1]))
    old_xml, new_xml = problem_xml(data), problem_xml(new)
    _, _, old_cards = pages._card_blocks(old_xml)
    _, _, new_cards = pages._card_blocks(new_xml)
    assert new_cards == [old_cards[i] for i in (3, 0, 2, 1)]
    assert new_xml[:new_xml.index(b"<card")] == old_xml[:old_xml.index(b"<card")]  # <sym> intact
    assert [s.widget for s in pages.problem_summaries(new_xml)] == ["TI.GeoGrapher", "TI.Notepad", "tabulator",
                                                                    "TI.Scratchpad"]
    assert inspect.validate_bytes(new) == []
    with pytest.raises(notes.NotesError):
        pages.reorder(old_xml, [0, 1, 1, 2])


# --- TIXC dictionary overflow -------------------------------------------------------------

def test_tixc_more_than_256_tag_names():
    body = "".join(f"<t{i}>{i}</t{i}>" for i in range(300))
    xml = b'<?xml version="1.0" encoding="UTF-8" ?><r>' + body.encode() + b"<t5>again</t5><t290>x</t290></r>"
    stream = tixc.encode(xml)
    assert b"</t290>" in stream and b"</t5>" not in stream  # literal close only beyond the dictionary
    assert tixc.decode(stream) == xml


def test_tixc_literal_close_must_match():
    with pytest.raises(tixc.TixcError):
        tixc.decode(b"TIXC0100-1.0?><r><a>1</b></r>")


# --- combined edits ------------------------------------------------------------------------

def test_apply_edits_runs_layouts_and_order_together():
    two = notes_problem_xml([[word("uno"), word("dos")], [word("x")]])
    data = doc_with(two)
    new = apply_edits(data, notes_edits={("Problem1.xml", 1): {0: "y"}},
                      layouts={("Problem1.xml", 0): [1, "medio", 0]}, orders={"Problem1.xml": [1, 0]})
    pg = notes.document_pages(container.parse(new))
    assert [r.text for r in pg[0].runs] == ["y"] and [r.text for r in pg[1].runs] == ["dos", "medio", "uno"]
    assert container.parse(data).entry("Document.xml") == container.parse(new).entry("Document.xml")


def test_apply_edits_rejects_invalid_layout():
    with pytest.raises(notes.NotesError):
        apply_edits(three_para_doc(), layouts={("Problem1.xml", 0): [0, 0]})
    assert issubclass(RebuildError, ValueError)
