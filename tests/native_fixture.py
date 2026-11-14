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
