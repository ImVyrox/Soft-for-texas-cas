"""Synthetic documents with the *native* layout (no personal files involved).

They follow what was measured on documents saved by a CX CAS: every encrypted
entry has its own TIEN0100 header (random keys and seed) and the directory
CRC/size describe the decoded XML. Built only with the project's own code.
"""

import os
import zlib

from texas_cas_manager.tns import doccrypt, tien, tixc
from texas_cas_manager.tns.container import METHOD_DEFLATED, METHOD_TI_ENCRYPTED, TnsDocument, TnsEntry, write

DECL = b'<?xml version="1.0" encoding="UTF-8" ?>'
DOCUMENT_XML = DECL + (b'<doc ver="1.0"><properties><product>28</product><platform>2</platform>'
                       b'<swver>6.3.0.119 SE CAS Win </swver><date>2017-6-0</date></properties>'
                       b'<settings><lang>es</lang><angf>2</angf></settings></doc>')
SCRIPT = "-- reloj ñ\nfunction on.paint(gc)\n  gc:drawString(\"t = \" .. tostring(1 < 2), 10, 10)\nend\n"


def problem_xml(script: str = SCRIPT, cry: str = "0") -> bytes:
    return DECL + (
        b'<prob xmlns="urn:TI.Problem" ver="1.0" pbname=""><sym><e t="1" f="0" c="0"><n>reloj</n><v>{}</v></e></sym>'
        b'<card clay="0" h1="10000" h2="10000" w1="10000" w2="10000"><isDummyCard>0</isDummyCard><flag>0</flag>'
        b'<wdgt xmlns:sc="urn:TI.ScriptApp" type="TI.ScriptApp" ver="1.0"><sc:mFlags>0</sc:mFlags>'
        b'<sc:value>0</sc:value><sc:cry>' + cry.encode() + b'</sc:cry><sc:md>'
        b'<sc:mde name="TITLE" prop="2147549184">Reloj</sc:mde></sc:md>'
        b'<sc:script version="34013703" id="0"><![CDATA[' + script.encode() + b']]></sc:script></wdgt></card>'
        b'<card clay="0" h1="10000" h2="10000" w1="10000" w2="10000"><isDummyCard>0</isDummyCard><flag>0</flag>'
        b'<wdgt xmlns:np="urn:TI.Notepad" type="TI.Notepad" ver="2.0"><np:mFlags>1024</np:mFlags>'
        b'<np:value>3</np:value><np:fmtxt>&lt;r2dtotree/&gt;</np:fmtxt></wdgt></card></prob>')


def encrypted_entry(name: str, xml: bytes, seed: int | None = None) -> TnsEntry:
    header = tien.build(tien.TienHeader(tien.BLOCK_SIZE, seed if seed is not None else int.from_bytes(os.urandom(4), "little"),
                                        os.urandom(21)))
    raw = doccrypt.encrypt_entry(tixc.encode(xml), header=header)
    return TnsEntry(name=name, method=METHOD_TI_ENCRYPTED, raw=raw, crc32=zlib.crc32(xml),
                    uncompressed_size=len(xml), name_bytes=name.encode())


def native_document(cry: str = "0", with_image: bool = True) -> bytes:
    entries = [encrypted_entry("Document.xml", DOCUMENT_XML), encrypted_entry("Problem1.xml", problem_xml(cry=cry))]
    if with_image:
        bmp = b"BM" + bytes(range(256)) * 8
        entries.append(TnsEntry(name="A1B2.BMP", method=METHOD_DEFLATED, raw=b"", crc32=0, uncompressed_size=0,
                                name_bytes=b"A1B2.BMP").with_payload(bmp))
    return write(TnsDocument(version="0601", entries=entries))


# --- Notes pages (structure observed in a document saved by a CX CAS, OS 4.5.5) --------

FORMAT_MANAGER = (
    '<formatManager tableSize="3" capacity="10">'
    '<formatEntry entryIndex="0" entryID="0" entryRefCnt="2147483647" tc="0" fc="268435199" fs="10" fst="0" cc="0" '
    'fest="0" feun="0" fesub="0" fesup="0" fn0="TI-Nspire Sans"></formatEntry>'
    '<formatEntry entryIndex="1" entryID="1" entryRefCnt="1" tc="0" fc="268435199" fs="10" fst="0" cc="0" '
    'fest="0" feun="0" fesub="0" fesup="0" fn0="TI-Nspire"></formatEntry>'
    '<formatEntry entryIndex="2" entryID="2" entryRefCnt="1" tc="254" fc="268435199" fs="10" fst="0" cc="0" '
    'fest="0" feun="0" fesub="0" fesup="0" fn0="TI-Nspire"></formatEntry></formatManager>')


def word(text: str, np: str = "1", children: str = "") -> str:
    if not text and not children:
        return f'<leaf name="1word" np="{np}" id0="0" pp0="0"/>'
    return f'<leaf name="1word" np="{np}" id0="0" pp0="{len(text)}">{text}{children}</leaf>'


def notes_inner(lines: list[str]) -> str:
    paras = "".join(f'<node name="1para"><node name="1rtline">{line}</node></node>' for line in lines)
    return f'<r2dtotree version="1">{FORMAT_MANAGER}<node name="1doc">{paras}</node></r2dtotree>'


MATH_BOX = ('<node name="0el" flags="8" id0="1"><mbox><attr iomode="1" comp="2" active="true" id0="2"/>'
            '<out><full>5</full><err>0</err></out></mbox><node name="0el" id0="2">'
            '<leaf name="0text" np="1" id0="2" pp0="3">2+3</leaf></node></node>')


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def notes_problem_xml(pages: list[list[str]] | None = None) -> bytes:
    if pages is None:
        pages = [[word("hola"), word("abc") + MATH_BOX + word("")],
                 [word("π"), word("x"), word("", children='<cursor index="0"/>')]]
    cards = "".join(
        '<card clay="0" h1="10000" h2="10000" w1="10000" w2="10000"><isDummyCard>0</isDummyCard><flag>0</flag>'
        '<wdgt xmlns:np="urn:TI.Notepad" type="TI.Notepad" ver="2.0"><np:mFlags>1024</np:mFlags>'
        f'<np:value>3</np:value><np:fmtxt>{_escape(notes_inner(p))}</np:fmtxt></wdgt></card>' for p in pages)
    return DECL + ('<prob xmlns="urn:TI.Problem" ver="1.0" pbname=""><sym></sym>' + cards + "</prob>").encode()


def notes_document(pages: list[list[str]] | None = None) -> bytes:
    return write(TnsDocument(version="0601", entries=[encrypted_entry("Document.xml", DOCUMENT_XML),
                                                       encrypted_entry("Problem1.xml", notes_problem_xml(pages))]))


# --- Maths boxes and other page types (structures observed in samples made on a CX CAS) ----

def mbox(input_tree: str, full: str | None, err: int = 0) -> str:
    out = (f"<full>{full}</full><warn>{{}}</warn>" if full is not None else "") + f"<err>{err}</err>"
    return ('<node name="0el" flags="8" id0="1"><mbox><attr iomode="1" comp="2" active="true" id0="3"/>'
            f'<out>{out}</out></mbox><node name="0el" id0="2">{input_tree}</node>'
            '<node name="0el" id0="3"><leaf name="0text" readonly="1" np="1" id0="3" pp0="1">r</leaf></node></node>')


def t(text: str) -> str:
    return f'<leaf name="0text" np="1" id0="2" pp0="{len(text)}">{text}</leaf>'


def el(*parts: str) -> str:
    return '<node name="0el" id0="2">' + "".join(parts) + "</node>"


MATH_SAMPLES = [
    (t("") + '<node name="0fraction" id0="2">((' + el(t("1")) + el(t("2")) + "</node>" + t("+")
     + '<node name="0fraction" id0="2">((' + el(t("1")) + el(t("3")) + "</node>", "5/6", "(1)/(2)+(1)/(3)"),
    ('<node name="0sqrt" id0="4">√(' + el(t("2")) + "</node>", "√(2)", "√(2)"),
    (t("x") + '<node name="0power" id0="6">^(' + el(t("3")) + "</node>", "x^3", "x^(3)"),
    ('<node name="0matrix" id0="2" data="2">[[' + el(t("1")) + el(t("2")) + el(t("3")) + el(t("4")) + "</node>",
     "[[1,2][3,4]]", "[[1,2][3,4]]"),
    ('<node name="0integral" id0="4">∫(' + el(t("0")) + el(t("1")) + el(t("x")) + el(t("x")) + "</node>",
     "1/2", "∫(x,x,0,1)"),
]

SCRATCHPAD = ('<wdgt xmlns:a="urn:TI.Scratchpad" type="TI.Scratchpad" ver="1.0"><a:mFlags>0</a:mFlags>'
              '<a:erow><a:entr>2+3</a:entr><a:exct>2+3</a:exct><a:rslt><a:warn2>{}</a:warn2><a:disp>5</a:disp>'
              '<a:full>5</a:full></a:rslt><a:ctxt ang="2" cplx="1" comp="1"/></a:erow></wdgt>')
TABULATOR = ('<wdgt xmlns:tb="urn:TI.Tabulator" type="tabulator" ver="1.0"><tb:table><tb:rowHeights/><tb:columns>'
             '<tb:column type="formula-column"><tb:formula>=datos</tb:formula><tb:cells><tb:cell><tb:rowId>1</tb:rowId>'
             '</tb:cell></tb:cells></tb:column><tb:column type="cell-column"><tb:cells/></tb:column></tb:columns>'
             '</tb:table></wdgt>')
GEO = ('<wdgt xmlns:g="urn:TI.GeoGrapher" type="TI.GeoGrapher" ver="1.0"><g:fig><g:ver>10</g:ver><g:objs>'
       '<g:axis><g:id>2</g:id></g:axis><g:axis><g:id>3</g:id></g:axis><g:point><g:id>4</g:id></g:point></g:objs>'
       '</g:fig></wdgt>')


def card(wdgt: str) -> str:
    return ('<card clay="0" h1="10000" h2="10000" w1="10000" w2="10000"><isDummyCard>0</isDummyCard><flag>0</flag>'
            + wdgt + "</card>")


def multi_page_xml() -> bytes:
    notes = notes_problem_xml([[word("hola")]]).decode()
    notes_card = notes[notes.index("<card"):notes.rindex("</card>") + len("</card>")]
    return DECL + ('<prob xmlns="urn:TI.Problem" ver="1.0" pbname=""><sym><e t="6" f="0" c="255"><n>f1</n><p>x</p>'
                   '<v>x^2</v></e></sym>' + notes_card + card(SCRATCHPAD) + card(TABULATOR) + card(GEO)
                   + "</prob>").encode()
