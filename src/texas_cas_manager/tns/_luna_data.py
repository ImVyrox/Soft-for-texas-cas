# This Source Code Form is subject to the Mozilla Public License, v. 1.1.
# The contents of this file are subject to the Mozilla Public License
# Version 1.1 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Constants extracted verbatim from Luna 2.1 (luna.c), whose Initial
# Developer is Olivier ARMAND <olivier.calc@gmail.com>, Copyright (C)
# 2011-2014. https://github.com/ndless-nspire/Luna
# This file only holds Luna's data; the rest of the project is MIT licensed.
"""Constants from Luna used to build Lua documents the calculator accepts."""

# 3DES keys and counter base used by Luna's doccrypt(); they match
# TIEN_CRYPTED_HEADER (the header stores them in an encoded form).
DOCCRYPT_KEYS = (
    bytes([0x16, 0xA7, 0xA7, 0x32, 0x68, 0xA7, 0xBA, 0x73]),
    bytes([0xD9, 0xA8, 0x86, 0xA4, 0x34, 0x45, 0x94, 0x10]),
    bytes([0x3D, 0x80, 0x8C, 0xB5, 0xDF, 0xB3, 0x80, 0x6B]),
)
DOCCRYPT_IVEC_BASE = 0x6FE21307

# XML-compressed Problem1.xml around a Lua script (CDATA content).
LUA_HEADER = (
    b'TIXC0100-1.0?><prob xmln'
    b's="urn:TI.P\xa8_[\x1f\n" ver="1'
    b'.0" pbname=""><sym>\x0e\x01<ca'
    b'rd clay="0" h1="\xf1\x00\x00\xff" h2'
    b'="\xf1\x00\x00\xff" w1="\xf1\x00\x00\xff" w2="\xf1\x00'
    b'\x00\xff"><isDummyCard>0\x0e\x03<fla'
    b'g>0\x0e\x04<wdgt xmlns:sc="urn'
    b':TI.S\xac\x84\xf2*App" type="TI.S'
    b'\xac\x84\xf2*App" ver="1.0"><sc:m'
    b'Flags>0\x0e\x06<sc:value>-1\x0e\x07<'
    b'sc:script version="512" '
    b'id="0"><![CDATA['
)

LUA_FOOTER = (
    b']]>\x0e\x08\x0e\x05\x0e\x02\x0e\x00'
)

# Prefix of XML-compressed data ("TIXC0100-1.0?>").
XML_HEADER = (
    b'TIXC0100-1.0?>'
)

# Complete Document.xml entry data (already compressed and encrypted).
DEFAULT_PROCESSED_DOCUMENT_XML = (
    b'\x0f\xce\xd8\xd2\x81\x06\x86[JJ\xc5\xce\xa9\x16\xf2\xd5\x1d\xa8/n\x00"\xf2\xf0'
    b'\xc1\xa6\x06wM~\xa6\xc0:\xf0\\t\xba\xaaD`\xcdX\xe6p\xd7@\xf6\x9c'
    b'\x17\xdc\xf0\x94w\xbf\xca\xde\xf7\x02\t\xc9b\xb1]\xef"\xfaQ7\xa0\x81\x91H'
    b'\xe1\x83M\xad\x081-\xd0\xd3\xe3-`\xab\x13\xc2\x98+\xed9[\t$9\x92'
    b"/\x0czL\x95t\x91;\x0c\xf4`\xccs'\xcb\x07~\x7f\xa9\x17\x87\xe2\xac\xa2"
    b';\xcc\xa0\xc4\xe3\x8e\x89\xf0\xc0Q\x9f\xc2\xbe\xce(E\xc3\xd4\x11\x90\xa6\xecS\xa0'
    b'\xfb[FkA\xad\xe9S\xbb\x97\xdb\xb1\xd2h\xe2\xf66\x0f&6u\x9b\xe9\x1f'
    b'H\xad\xe9)g\x00X\x19\xc3\xc0\x12v\xa0Js\xf3\xb1\xd3\t\x18\xd6\x06\xdd\x97'
    b'$S>"\xa4\xfb\x82P{|\x12\x88N}A\x80\xfer\x92)\x87\xe8\\V'
    b'r\xff)\x16\x8cB[\x8b\x9b\xa7\xd2\x08m\xd3\x98\xff\x91\xa9\x9e\xf3\x93\xa8.\x1c'
    b'\xb2\xa9kj\xdf\xf6\xce-\x15\x17\xcen\xc0O\x9a\x9c\x0e\xdf\x19\x8d-\xfai\x9f'
    b'\x11\xd2 \x12\xe0y\x14\x04Nb\x8f\n*\x18rZ\x8b\x80\xb3<\x9b\xd5gY'
    b'KQM\xe0\xc38(\xc3\xdc\xcd9"\x12\x8c@U'
)

# 40-byte header in front of every entry encrypted with DOCCRYPT_KEYS.
TIEN_CRYPTED_HEADER = (
    b'\x0f\xce\xd8\xd2\x81\x06\x86[\x99\xdd\xa2=\xd9\xe9K\xd41\xbbP\xb6M\xb3)$'
    b'p`I8\x1c0\xf8\x99\x00K\x92d\xe4X\xe6\xbc'
)
