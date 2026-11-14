# The contents of this file are subject to the Mozilla Public License
# Version 1.1 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Python port of crates/tns-core/src/tixc.rs from Rust TNS
# (https://github.com/dev1837457/rust-tns, commit 48a6f5e, MPL 1.1,
# "TNS modernization contributors", 2026). Ported for Texas CAS Manager;
# the rest of the project is MIT licensed.
"""TIXC0100: the XML token stream stored inside TI-encrypted (method 0x0D) entries.

Grammar (from the Rust TNS implementation, checked against real documents):
the first time a tag or attribute name appears it is written out and added to
a dictionary (max. 256 each); later uses reference it by index (0x0C = start
tag, 0x0E = close tag, 0x0F = attribute). Text uses nibble-packed tables for
common letters (0xA_) and digits/symbols (0xF_) and a compact form for
non-ASCII UTF-8. ``decode`` returns canonical XML starting with
``<?xml version="1.0" encoding="UTF-8" ?>``; TI's directory CRC/size of
native documents describe exactly that XML.
"""

from __future__ import annotations

import re

TAG_NAME_TERMINATORS = (0x0E, 0x0F, ord(" "), ord("/"), ord(">"))
ETA_TABLE = b" etaionsrhAlcduFmfpgybwvkxqjz,.'"
DIGIT_TABLE = b"0123456789AN,.EFx; (){}[]^+-/*PB"
CDATA_OPEN = b"<![CDATA["
CDATA_CLOSE = b"]]>"
DECLARATION_PREFIX = b'<?xml version="'
DECLARATION_SUFFIX = b'" encoding="UTF-8" ?>'

MAX_OUTPUT = 64 * 1024 * 1024
MAX_DEPTH = 256
MAX_NAME = 256

_NAME_RE = re.compile(r"[:A-Z_a-zÀ-ÖØ-öø-˿Ͱ-ͽͿ-῿‌-‍"
                      r"⁰-↏Ⰰ-⿯、-퟿豈-﷏ﷰ-�\U00010000-\U000effff]"
                      r"[-.0-9·̀-ͯ‿-⁀:A-Z_a-zÀ-ÖØ-öø-˿"
                      r"Ͱ-ͽͿ-῿‌-‍⁰-↏Ⰰ-⿯、-퟿"
                      r"豈-﷏ﷰ-�\U00010000-\U000effff]*\Z")
_XML_CHARS_RE = re.compile(r"[^\t\n\r -퟿-�\U00010000-\U0010ffff]")


class TixcError(ValueError):
    """Malformed TIXC stream or XML that cannot be encoded."""


def has_only_xml_characters(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return _XML_CHARS_RE.search(text) is None


def _validate_name(name: bytes, kind: str) -> None:
    try:
        text = name.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TixcError(f"{kind} name is not valid UTF-8") from exc
    if not _NAME_RE.match(text):
        raise TixcError(f"invalid XML {kind} name {text!r}")


def _special_digit(ch: int) -> bytes:
    return {ord("N"): "−".encode(), ord("E"): b"\xef\x80\x80", ord("P"): b"))", ord("B"): b"]["}.get(ch, bytes([ch]))


class _Out:
    def __init__(self, limit: int):
        self.buf = bytearray()
        self.limit = limit

    def add(self, data: bytes | bytearray) -> None:
        if len(self.buf) + len(data) > self.limit:
            raise TixcError(f"TIXC output exceeds {self.limit} bytes")
        self.buf += data


class _TextDecoder:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.state = 0
        self.count = 0
        self.tmp = 0

    def decode(self, b: int, out: _Out) -> None:  # noqa: C901 (direct port of the state machine)
        s = self.state
        if s == 0:
            if b < 0xA0:
                needs_utf = (b < 0x20 and ((0xFFFFD9FF >> b) & 1)) or b >= 0x7F
                if needs_utf:
                    if b & 0xF0 == 0x80:
                        self.count = (b & 0x0F) + 1
                        self.state = 28
                        return
                    if b >= 8:
                        if b == 8:
                            self.state = 30
                            return
                        if b == 11:
                            self.state = 33
                            return
                        raise TixcError(f"unsupported text control byte 0x{b:02x}")
                    self.tmp = (((b & 7) | 0xF0) << 2) & 0xFF
                    self.count = 1
                    self.state = 27
                    return
                out.add(bytes([b]))
                return
            if b & 0xF0 == 0xA0:
                ch = ETA_TABLE[b & 0x0F]
                if ch == ord("F"):
                    self.state = 24
                elif ch == ord("A"):
                    self.state = 0
                else:
                    self.state = 23
                    out.add(bytes([ch]))
                return
            if b & 0xF0 == 0xF0:
                ch = DIGIT_TABLE[b & 0x0F]
                if ch == ord("A"):
                    self.state = 26
                elif ch == ord("F"):
                    self.state = 0
                else:
                    self.state = 25
                    out.add(_special_digit(ch))
                return
            raise TixcError(f"unsupported text byte 0x{b:02x}")
        if s == 23:
            first = ETA_TABLE[b >> 4]
            if first == ord("F"):
                out.add(bytes([ETA_TABLE[(b & 0x0F) + 16]]))
                return
            if first == ord("A"):
                self.state = 0
                return
            out.add(bytes([first]))
            second = ETA_TABLE[b & 0x0F]
            if second == ord("F"):
                self.state = 24
            elif second == ord("A"):
                self.state = 0
            else:
                out.add(bytes([second]))
            return
        if s == 24:
            out.add(bytes([ETA_TABLE[(b >> 4) + 16]]))
            second = ETA_TABLE[b & 0x0F]
            if second == ord("F"):
                pass
            elif second == ord("A"):
                self.state = 0
            else:
                out.add(bytes([second]))
                self.state = 23
            return
        if s == 25:
            first = DIGIT_TABLE[b >> 4]
            if first == ord("A"):
                out.add(_special_digit(DIGIT_TABLE[(b & 0x0F) + 16]))
                return
            if first == ord("F"):
                self.state = 0
                return
            out.add(_special_digit(first))
            second = DIGIT_TABLE[b & 0x0F]
            if second == ord("A"):
                self.state = 26
            elif second == ord("F"):
                self.state = 0
            else:
                out.add(_special_digit(second))
            return
        if s == 26:
            out.add(_special_digit(DIGIT_TABLE[(b >> 4) + 16]))
            second = DIGIT_TABLE[b & 0x0F]
            if second == ord("A"):
                pass
            elif second == ord("F"):
                self.state = 0
            else:
                self.state = 25
                out.add(_special_digit(second))
            return
        if s == 27:
            self.state = 0
            self.count = 0
            out.add(bytes([(self.tmp | (b >> 6)) & 0xFF, (b & 0x3F) | 0x80]))
            return
        if s == 28:
            self.state = 29
            self.tmp = b
            out.add(bytes([(b >> 4) | 0xE0]))
            return
        if s == 29:
            self.count = max(0, self.count - 1)
            self.state = 0 if self.count == 0 else 28
            out.add(bytes([((b >> 6) | (((self.tmp & 0x0F) | 0xE0) << 2)) & 0xFF, (b & 0x3F) | 0x80]))
            return
        if s == 30:
            self.tmp = b
            self.state = 31
            if b >= 0x20:
                self.count = 2
                out.add(bytes([0xF8, (b >> 2) | 0x80]))
            else:
                self.count = 1
                out.add(bytes([((b >> 2) & 7) | 0xF0]))
            return
        if s in (31, 35):
            self.count = 1
            self.state = 32
            out.add(bytes([((b >> 4) | (((self.tmp & 3) | 0xF8) << 4)) & 0xFF]))
            self.tmp = b
            return
        if s in (32, 36):
            self.state = 0
            self.count = 0
            out.add(bytes([((b >> 6) | (((self.tmp & 0x0F) | 0xE0) << 2)) & 0xFF, (b & 0x3F) | 0x80]))
            return
        if s == 33:
            self.state = 34
            if b >= 4:
                out.add(bytes([(1 if b & 0x40 else 0) | 0xFC, (b & 0x3F) | 0x80]))
            else:
                out.add(bytes([(b & 3) | 0xF8]))
            return
        if s == 34:
            self.state = 35
            self.tmp = b
            self.count = 1
            out.add(bytes([(b >> 2) | 0x80]))
            return
        raise TixcError(f"unsupported text state {s}")


def decode(data: bytes, max_output: int = MAX_OUTPUT) -> bytes:  # noqa: C901 (state machine)
    """Expand a TIXC0100 stream to canonical XML. Raises TixcError if malformed."""
    if not data.startswith(b"TIXC0100"):
        raise TixcError("stream does not start with TIXC0100")
    if data[8:9] != b"-":
        raise TixcError("missing version separator in header")
    q = data.find(b"?", 9)
    if q < 0 or data[q:q + 2] != b"?>":
        raise TixcError("invalid TIXC header terminator")
    version = data[9:q]
    if version != b"1.0":
        raise TixcError("only XML version 1.0 is supported")
    out = _Out(max_output)
    out.add(DECLARATION_PREFIX + version + DECLARATION_SUFFIX)

    tags: list[bytes] = []
    attrs: list[bytes] = []
    token = bytearray()
    text = _TextDecoder()
    state = 1
    cdata_match = 0
    pos = q + 2
    stack: list[bytes] = []
    current: bytes | None = None
    current_attrs: set[bytes] = set()
    saw_root = root_closed = False

    def complete(self_closing: bool) -> None:
        nonlocal current, saw_root, root_closed
        if current is None:
            raise TixcError("start tag terminator has no tag name")
        tag, current = current, None
        current_attrs.clear()
        if root_closed and not stack:
            raise TixcError("multiple XML roots are not supported")
        saw_root = True
        if not self_closing:
            if len(stack) >= MAX_DEPTH:
                raise TixcError("TIXC nesting too deep")
            stack.append(tag)
        elif not stack:
            root_closed = True

    def close(tag: bytes) -> None:
        nonlocal root_closed
        if not stack:
            raise TixcError("closing tag has no open element")
        expected = stack.pop()
        if expected != tag:
            raise TixcError(f"closing tag {tag!r} does not match {expected!r}")
        if not stack:
            root_closed = True

    n = len(data)
    while pos < n:
        b = data[pos]
        if state == 1:
            if b != ord("<"):
                raise TixcError("expected root '<' after TIXC header")
            out.add(b"<")
            pos += 1
            state = 2
        elif state == 2:
            if b in TAG_NAME_TERMINATORS:
                had = bool(token)
                name = bytes(token)
                if token:
                    if len(token) > MAX_NAME:
                        raise TixcError("tag token too long")
                    if len(tags) < 256:
                        tags.append(name)
                    token.clear()
                if had:
                    _validate_name(name, "tag")
                    current = name
                if b == 0x0E:
                    out.add(b"></")
                    complete(False)
                    state = 12
                elif b == 0x0F:
                    out.add(b" ")
                    state = 13
                elif b == ord(" "):
                    if not had and out.buf.endswith(b"<"):
                        raise TixcError("empty tag before attribute separator")
                    out.add(b" ")
                    state = 4
                elif b == ord("/") and not had and out.buf.endswith(b"<"):
                    # Literal closing tag "</name>": used once the 256-entry tag dictionary
                    # is full (seen in documents saved by a CX CAS; Luna does the same).
                    gt = data.find(b">", pos + 1)
                    if gt < 0:
                        raise TixcError("unterminated literal closing tag")
                    name = data[pos + 1:gt]
                    _validate_name(name, "tag")
                    out.add(b"/" + name + b">")
                    close(name)
                    pos = gt
                    state = 3
                elif b == ord("/"):
                    out.add(b"/")
                    state = 9 if had else 10
                else:  # '>'
                    if not had and out.buf.endswith(b"<"):
                        raise TixcError("empty tag before '>'")
                    out.add(b">")
                    complete(False)
                    state = 3
                pos += 1
            else:
                if len(token) >= MAX_NAME:
                    raise TixcError("tag token too long")
                token.append(b)
                out.add(bytes([b]))
                pos += 1
        elif state == 3:
            text.reset()
            token.clear()
            if b == ord("<"):
                out.add(b"<")
                pos += 1
                state = 17
            elif b == 0x0C:
                out.add(b"<")
                pos += 1
                state = 11
            elif b == 0x0E:
                out.add(b"</")
                pos += 1
                state = 12
            else:
                state = 8
        elif state == 4:
            if b == ord("="):
                if not token:
                    raise TixcError("empty attribute name")
                name = bytes(token)
                _validate_name(name, "attribute")
                if name in current_attrs:
                    raise TixcError("duplicate attribute name")
                current_attrs.add(name)
                if len(attrs) < 256:
                    attrs.append(name)
                token.clear()
                out.add(b"=")
                pos += 1
                state = 5
            else:
                if len(token) >= MAX_NAME:
                    raise TixcError("attribute token too long")
                token.append(b)
                out.add(bytes([b]))
                pos += 1
        elif state == 5:
            pos += 1
            if b == ord('"'):
                out.add(b'"')
                state = 6
            elif b != ord(" "):
                raise TixcError("expected quote or space after attribute '='")
        elif state == 6:
            if b == ord('"') and text.state == 0:
                out.add(b'"')
                pos += 1
                token.clear()
                state = 7
            else:
                text.decode(b, out)
                pos += 1
        elif state == 7:
            if b == ord(">"):
                out.add(b">")
                complete(False)
                pos += 1
                state = 3
            elif b == ord("/"):
                out.add(b"/")
                pos += 1
                state = 10
            elif b == ord(" "):
                out.add(b" ")
                pos += 1
                state = 4
            elif b == 0x0F:
                out.add(b" ")
                pos += 1
                state = 13
            else:
                raise TixcError(f"unexpected byte 0x{b:02x} after attribute value")
        elif state == 8:
            if b == ord("<") and text.state == 0:
                out.add(b"<")
                pos += 1
                token.clear()
                state = 2
            elif b == 0x0C and text.state == 0:
                out.add(b"<")
                pos += 1
                token.clear()
                state = 11
            elif b == 0x0E and text.state == 0:
                out.add(b"</")
                pos += 1
                token.clear()
                state = 12
            else:
                text.decode(b, out)
                pos += 1
        elif state in (9, 10):
            if b != ord(">"):
                raise TixcError("expected '>' after '/'")
            out.add(b">")
            complete(True)
            pos += 1
            state = 3
        elif state == 11:
            if b >= len(tags):
                raise TixcError(f"tag dictionary index {b} out of range")
            out.add(tags[b])
            current = tags[b]
            pos += 1
            state = 14
        elif state == 12:
            if b >= len(tags):
                raise TixcError(f"tag dictionary index {b} out of range")
            out.add(tags[b] + b">")
            close(tags[b])
            pos += 1
            state = 3
        elif state == 13:
            if b >= len(attrs):
                raise TixcError(f"attribute dictionary index {b} out of range")
            if attrs[b] in current_attrs:
                raise TixcError("duplicate attribute name")
            current_attrs.add(attrs[b])
            out.add(attrs[b] + b'="')
            pos += 1
            text.reset()
            state = 6
        elif state == 14:
            if b == ord(" "):
                out.add(b" ")
                pos += 1
                state = 4
            elif b == ord("/"):
                pos += 1
                state = 15
            elif b == 0x0F:
                out.add(b" ")
                pos += 1
                state = 13
            else:
                out.add(b">")
                complete(False)
                state = 3
        elif state == 15:
            if b != ord(">"):
                raise TixcError("expected '>' after '/'")
            out.add(b"/>")
            complete(True)
            pos += 1
            state = 3
        elif state == 17:
            if b == ord("!"):
                if not stack or root_closed:
                    raise TixcError("CDATA is only allowed inside an element")
                out.add(b"!")
                pos += 1
                cdata_match = 2
                state = 18
            else:
                state = 2
        elif state == 18:
            if cdata_match >= len(CDATA_OPEN):
                state = 19
                token.clear()
            else:
                if b != CDATA_OPEN[cdata_match]:
                    raise TixcError("invalid CDATA opener")
                out.add(bytes([b]))
                pos += 1
                cdata_match += 1
        elif state == 19:
            out.add(bytes([b]))
            pos += 1
            if b == ord("]"):
                cdata_match = 1
                state = 20
        elif state == 20:
            out.add(bytes([b]))
            pos += 1
            if cdata_match < len(CDATA_CLOSE) and b == CDATA_CLOSE[cdata_match]:
                cdata_match += 1
            else:
                state = 19
                cdata_match = 0
            if cdata_match == len(CDATA_CLOSE):
                state = 3
                cdata_match = 0
        else:
            raise TixcError(f"unsupported parser state {state}")

    if state != 3:
        raise TixcError(f"stream ended in parser state {state}")
    if not saw_root or not root_closed or stack:
        raise TixcError("stream ended before the XML root was closed")
    result = bytes(out.buf)
    if not has_only_xml_characters(result):
        raise TixcError("decoded XML is not valid UTF-8 XML 1.0 text")
    return result


# ---------------------------------------------------------------- encoder

def _name_end(data: bytes, start: int) -> int:
    i = start
    while i < len(data) and data[i] not in b" \t\r\n/=>":
        i += 1
    return i


def _skip_ws(data: bytes, i: int) -> int:
    while i < len(data) and data[i] in b" \t\r\n":
        i += 1
    return i


def _table_run(data: bytes, start: int, digit: bool) -> tuple[int, list[int]]:
    table = DIGIT_TABLE[:14] if digit else ETA_TABLE[:15]
    i, idx = start, []
    while i < len(data):
        ch = data[i]
        k = table.find(bytes([ch]))
        if k < 0 or ch == ord("A") or (digit and ch == ord("N")):
            break
        idx.append(k)
        i += 1
    return i, idx


def _pack_run(prefix: int, terminator: int, idx: list[int], out: bytearray) -> None:
    out.append(prefix | idx[0])
    i = 1
    while i + 1 < len(idx):
        out.append((idx[i] << 4) | idx[i + 1])
        i += 2
    out.append((idx[i] << 4) | terminator if i < len(idx) else terminator << 4)


def _encode_text(data: bytes, out: bytearray) -> None:
    i = 0
    while i < len(data):
        b = data[i]
        if b < 0x80:
            d_end, d_idx = _table_run(data, i, True)
            e_end, e_idx = _table_run(data, i, False)
            if len(d_idx) >= 6 and len(d_idx) >= len(e_idx):
                _pack_run(0xF0, 0x0F, d_idx, out)
                i = d_end
                continue
            if len(e_idx) >= 6:
                _pack_run(0xA0, 0x0A, e_idx, out)
                i = e_end
                continue
            if b in (9, 10, 13) or 0x20 <= b <= 0x7E:
                out.append(b)
                i += 1
                continue
            raise TixcError(f"unsupported XML text control byte 0x{b:02x}")
        size = 2 if 0xC0 <= b <= 0xDF else 3 if 0xE0 <= b <= 0xEF else 4 if 0xF0 <= b <= 0xF7 else 0
        if not size:
            raise TixcError(f"invalid UTF-8 lead byte 0x{b:02x}")
        seq = data[i:i + size]
        if len(seq) < size:
            raise TixcError("truncated UTF-8 sequence")
        try:
            seq.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TixcError("invalid UTF-8 sequence") from exc
        if size == 2:
            out += bytes([(seq[0] & 0x1C) >> 2, ((seq[0] & 0x03) << 6) | (seq[1] & 0x3F)])
        elif size == 3:
            out += bytes([0x80, ((seq[0] & 0x0F) << 4) | ((seq[1] & 0x3C) >> 2), ((seq[1] & 0x03) << 6) | (seq[2] & 0x3F)])
        else:
            out += bytes([0x08, ((seq[0] & 0x07) << 2) | ((seq[1] & 0x30) >> 4),
                          ((seq[1] & 0x0F) << 4) | ((seq[2] & 0x3C) >> 2), ((seq[2] & 0x03) << 6) | (seq[3] & 0x3F)])
        i += size


def encode(xml: bytes) -> bytes:
    """Compress canonical XML to TIXC0100; verified by decoding back to ``xml``."""
    if not xml.startswith(DECLARATION_PREFIX):
        raise TixcError('XML must start with <?xml version="..." encoding="UTF-8" ?>')
    if not has_only_xml_characters(xml):
        raise TixcError("XML input is not valid UTF-8 XML 1.0 text")
    v_end = xml.find(b'"', len(DECLARATION_PREFIX))
    decl_end = xml.find(b"?>")
    if v_end < 0 or decl_end < 0 or xml[v_end:decl_end + 2] != DECLARATION_SUFFIX:
        raise TixcError("XML declaration must use the canonical UTF-8 form with a trailing space")
    version = xml[len(DECLARATION_PREFIX):v_end]
    if version != b"1.0":
        raise TixcError("only XML version 1.0 is supported")
    body = xml[decl_end + 2:]
    out = bytearray(b"TIXC0100-" + version + b"?>")
    tag_index: dict[bytes, int] = {}
    open_literal: list[bytes] = []  # literal (non-dictionary) elements still open
    pos = 0
    while pos < len(body):
        if body.startswith(CDATA_OPEN, pos):
            close = body.find(CDATA_CLOSE, pos + len(CDATA_OPEN))
            if close < 0:
                raise TixcError("unterminated CDATA section")
            end = close + len(CDATA_CLOSE)
            out += body[pos:end]
            pos = end
            continue
        if body[pos] != ord("<"):
            end = body.find(b"<", pos)
            end = len(body) if end < 0 else end
            _encode_text(body[pos:end], out)
            pos = end
            continue
        if body.startswith(b"</", pos):
            end = body.find(b">", pos + 2)
            if end < 0:
                raise TixcError("unterminated closing tag")
            name = body[pos + 2:end]
            if open_literal and open_literal[-1] == name:
                open_literal.pop()
                out += b"</" + name + b">"  # tag outside the full dictionary: literal close
            elif name in tag_index:
                out += bytes([0x0E, tag_index[name]])
            else:
                raise TixcError(f"close tag has no dictionary entry: {name!r}")
            pos = end + 1
            continue
        if body.startswith(b"<?", pos) or body.startswith(b"<!", pos):
            raise TixcError("only CDATA markup is supported")
        name_end = _name_end(body, pos + 1)
        name = body[pos + 1:name_end]
        if not name or len(name) > 64:
            raise TixcError(f"invalid tag name at offset {pos}")
        literal = False
        if name in tag_index:
            out += bytes([0x0C, tag_index[name]])
            reference = True
        else:
            if len(tag_index) < 256:
                tag_index[name] = len(tag_index)
            else:
                literal = True  # dictionary full: written literally, closed literally
            out += b"<" + name
            reference = False
        cursor, has_attrs = name_end, False
        while True:
            cursor = _skip_ws(body, cursor)
            if cursor >= len(body):
                raise TixcError("unterminated start tag")
            if body.startswith(b"/>", cursor):
                out += b"/>"
                pos = cursor + 2
                break
            if body[cursor] == ord(">"):
                if not reference or has_attrs:
                    out.append(ord(">"))
                if literal:
                    open_literal.append(name)
                pos = cursor + 1
                break
            a_end = _name_end(body, cursor)
            attr = body[cursor:a_end]
            if not attr:
                raise TixcError(f"empty attribute name at offset {cursor}")
            cursor = _skip_ws(body, a_end)
            if cursor >= len(body) or body[cursor] != ord("="):
                raise TixcError(f"expected '=' after attribute {attr!r}")
            cursor = _skip_ws(body, cursor + 1)
            if cursor >= len(body) or body[cursor] != ord('"'):
                raise TixcError(f"expected double quote for attribute {attr!r}")
            v_end = body.find(b'"', cursor + 1)
            if v_end < 0:
                raise TixcError(f"unterminated value for attribute {attr!r}")
            # Attribute names are written literally (never 0x0F references), as Rust TNS does:
            # TI's own expander was observed to truncate at 0x0F references.
            out += b" " + attr + b'="'
            _encode_text(body[cursor + 1:v_end], out)
            out.append(ord('"'))
            has_attrs = True
            cursor = v_end + 1
    result = bytes(out)
    if decode(result, max_output=len(xml) + 1) != xml:
        raise TixcError("internal encode/decode mismatch")
    return result
