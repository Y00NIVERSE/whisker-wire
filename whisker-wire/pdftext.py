"""A small PDF text reader. Standard library only.

Results announcements and annual reports are mostly PDFs, and there is no PDF package in this project on purpose
(everything here runs on Python's standard library). This reads the part of the format those documents use:
objects and object streams, Flate/ASCII filters, the page tree, fonts with a ToUnicode table or a simple
WinAnsi/Mac encoding, and the text-showing operators. It rebuilds lines from the way the text is positioned.

What it cannot do, and says so: scanned pages (they are pictures), password-protected PDFs, and fonts that give no way
to map their codes back to letters. A PDF is untrusted input from the internet, so everything is capped: file size,
how far one stream may inflate, pages, output size and total time.
"""
import re
import time
import unicodedata
import zlib
import base64
import binascii

MAX_BYTES = 15_000_000
MAX_STREAM = 40_000_000      # one stream may not inflate past this (a "zip bomb" guard)
MAX_OBJECTS = 300_000
MAX_PAGES = 400
MAX_CHARS = 600_000
TIME_BUDGET = 25.0           # seconds


class PdfError(ValueError):
    """Something a person can act on, phrased for them."""


class Name(str):
    pass


class Ref(tuple):
    pass


class Op(str):
    pass


_TOKEN = re.compile(rb"""
    (?P<ws>[\x00\t\n\x0c\r ]+|%[^\r\n]*)
  | (?P<dict_open><<)
  | (?P<dict_close>>>)
  | (?P<hex><[0-9A-Fa-f\x00\t\n\x0c\r ]*>)
  | (?P<str>\((?:[^()\\]|\\.|\((?:[^()\\]|\\.|\((?:[^()\\]|\\.)*\))*\))*\))
  | (?P<name>/[^\x00\t\n\x0c\r ()<>\[\]{}/%]*)
  | (?P<arr_open>\[)
  | (?P<arr_close>\])
  | (?P<num>[+-]?(?:\d+\.?\d*|\.\d+)(?![^\x00\t\n\x0c\r ()<>\[\]{}/%]))
  | (?P<kw>[^\x00\t\n\x0c\r ()<>\[\]{}/%]+)
""", re.X | re.S)

_ESC = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12, ord("("): 40, ord(")"): 41, ord("\\"): 92}


def _unescape(s):
    if b"\\" not in s:
        return s
    out, i, n = bytearray(), 0, len(s)
    while i < n:
        c = s[i]
        if c != 92:
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= n:
            break
        c = s[i]
        if c in _ESC:
            out.append(_ESC[c])
            i += 1
        elif 48 <= c <= 55:                       # \ddd octal
            j = i
            while j < n and j < i + 3 and 48 <= s[j] <= 55:
                j += 1
            out.append(int(s[i:j], 8) & 255)
            i = j
        elif c in (10, 13):                       # a backslash at the end of a line joins the lines
            i += 2 if c == 13 and i + 1 < n and s[i + 1] == 10 else 1
        else:
            out.append(c)
            i += 1
    return bytes(out)


def _hex(s):
    h = re.sub(rb"[^0-9A-Fa-f]", b"", s)
    if len(h) % 2:
        h += b"0"
    return binascii.unhexlify(h)


# ---------------------------------------------------------------- objects
class _Reader:
    """Recursive-descent parse of one PDF object from a token stream."""
    def __init__(self, data, pos=0, end=None):
        self.data, self.pos, self.end = data, pos, len(data) if end is None else end
        self.toks = []

    def _next(self):
        while self.pos < self.end:
            m = _TOKEN.match(self.data, self.pos)
            if not m:
                self.pos += 1
                continue
            self.pos = m.end()
            if m.lastgroup != "ws":
                return m.lastgroup, m.group()
        return None, None

    def _peek_ref(self, first):
        """int int R -> a reference; otherwise rewind."""
        save = self.pos
        k2, v2 = self._next()
        if k2 == "num" and v2.isdigit():
            k3, v3 = self._next()
            if k3 == "kw" and v3 == b"R":
                return Ref((int(first), int(v2)))
        self.pos = save
        return None

    def parse(self, depth=0):
        if depth > 60:
            raise PdfError("This PDF is nested too deeply to read. Paste the text instead.")
        k, v = self._next()
        if k is None:
            return None
        if k == "dict_open":
            d = {}
            while True:
                k2, v2 = self._next()
                if k2 in (None, "dict_close"):
                    return d
                if k2 != "name":
                    continue
                d[Name(v2[1:].decode("latin-1"))] = self.parse(depth + 1)
        if k == "arr_open":
            a = []
            while True:
                save = self.pos
                k2, v2 = self._next()
                if k2 in (None, "arr_close"):
                    return a
                self.pos = save
                a.append(self.parse(depth + 1))
        if k == "num":
            if v.isdigit():
                r = self._peek_ref(v)
                if r is not None:
                    return r
                return int(v)
            return float(v)
        if k == "name":
            return Name(re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), v[1:]).decode("latin-1"))
        if k == "str":
            return _unescape(v[1:-1])
        if k == "hex":
            return _hex(v[1:-1])
        if k == "kw":
            return {b"true": True, b"false": False, b"null": None}.get(v, Op(v.decode("latin-1")))
        return None


_OBJ = re.compile(rb"(?<![0-9])(\d{1,7})\s+(\d{1,5})\s+obj\b")


class Doc:
    def __init__(self, data):
        if not data[:1024].lstrip(b"\x00\t\n\r ").startswith(b"%PDF-") and b"%PDF-" not in data[:1024]:
            raise PdfError("That is not a PDF file. Paste the text instead.")
        if len(data) > MAX_BYTES:
            raise PdfError("That PDF is too large for Tick to read here. Copy the part you want read and paste it instead.")
        self.data = data
        self.deadline = time.monotonic() + TIME_BUDGET
        self.objs = {}                       # number -> (value, (start, end) of stream bytes or None)
        self._scan()

    def _scan(self):
        data = self.data
        if re.search(rb"/Encrypt\s*(?:\d+\s+\d+\s+R|<<)", data):
            raise PdfError("This PDF is password-protected or encrypted, which Tick cannot read. Open it, copy the text, and paste it here instead.")
        count = 0
        for m in _OBJ.finditer(data):
            count += 1
            if count > MAX_OBJECTS:
                break
            num, start = int(m.group(1)), m.end()
            end = data.find(b"endobj", start)
            end = len(data) if end < 0 else end
            body = data[start:end]
            s = body.find(b"stream")
            head_end = start + (s if s >= 0 else len(body))
            r = _Reader(data, start, head_end)
            try:
                val = r.parse()
            except PdfError:
                continue
            span = None
            if s >= 0 and isinstance(val, dict):
                ss = start + s + 6
                if data[ss:ss + 2] == b"\r\n":
                    ss += 2
                elif data[ss:ss + 1] in (b"\n", b"\r"):
                    ss += 1
                ln = val.get("Length")
                se = None
                if isinstance(ln, int) and data[ss + ln:ss + ln + 20].lstrip(b"\r\n ").startswith(b"endstream"):
                    se = ss + ln
                if se is None:
                    e2 = data.find(b"endstream", ss, end + 12)
                    se = e2 if e2 >= 0 else end
                    while se > ss and data[se - 1:se] in (b"\n", b"\r"):
                        se -= 1
                span = (ss, se)
            self.objs[num] = (val, span)
        for num, (val, span) in list(self.objs.items()):      # compressed objects
            if isinstance(val, dict) and val.get("Type") == "ObjStm" and span:
                self._load_objstm(val, span)
        if not self.objs:
            raise PdfError("Tick could not read the structure of that PDF. Open it, copy the text, and paste it here instead.")

    def _load_objstm(self, d, span):
        try:
            raw = self.stream_bytes(d, span)
            n, first = int(self.get(d.get("N"), 0)), int(self.get(d.get("First"), 0))
            if raw is None:
                return
            nums = [int(x) for x in re.findall(rb"\d+", raw[:first])][:2 * n]
            for i in range(0, len(nums) - 1, 2):
                num, off = nums[i], nums[i + 1]
                r = _Reader(raw, first + off)
                self.objs.setdefault(num, (r.parse(), None))
        except (PdfError, ValueError, zlib.error):
            return

    # ---- resolving
    def get(self, v, default=None, depth=0):
        while isinstance(v, Ref) and depth < 20:
            v = self.objs.get(v[0], (None, None))[0]
            depth += 1
        return default if v is None else v

    def dict_of(self, v):
        v = self.get(v)
        return v if isinstance(v, dict) else {}

    def stream_of(self, ref_or_obj):
        if isinstance(ref_or_obj, Ref):
            val, span = self.objs.get(ref_or_obj[0], (None, None))
            return (val, span) if span else (val, None)
        return ref_or_obj, None

    def stream_bytes(self, d, span):
        raw = self.data[span[0]:span[1]]
        filters = self.get(d.get("Filter"))
        parms = self.get(d.get("DecodeParms"))
        fl = [filters] if isinstance(filters, str) else [self.get(f) for f in (filters or [])]
        pl = parms if isinstance(parms, list) else [parms] * len(fl)
        for f, p in zip(fl, pl):
            p = self.dict_of(p)
            if f in ("FlateDecode", "Fl"):
                raw = _inflate(raw)
                raw = _predict(raw, p, self)
            elif f in ("ASCIIHexDecode", "AHx"):
                raw = _hex(raw.split(b">")[0])
            elif f in ("ASCII85Decode", "A85"):
                raw = base64.a85decode(raw.strip().removeprefix(b"<~"), adobe=False) if b"~>" not in raw else base64.a85decode(raw.strip().removeprefix(b"<~").split(b"~>")[0])
            else:
                return None                  # images, LZW and the like: nothing to read here
        return raw


def _inflate(raw):
    d = zlib.decompressobj()
    try:
        out = d.decompress(raw, MAX_STREAM)
        if d.unconsumed_tail:
            raise PdfError("A part of that PDF is too large to read safely. Copy the part you want read and paste it instead.")
        return out
    except zlib.error:
        d = zlib.decompressobj()                # damaged tail: keep what inflated
        out = b""
        for i in range(0, len(raw), 4096):
            try:
                out += d.decompress(raw[i:i + 4096])
            except zlib.error:
                break
            if len(out) > MAX_STREAM:
                raise PdfError("A part of that PDF is too large to read safely. Copy the part you want read and paste it instead.")
        return out


def _predict(raw, p, doc):
    pred = int(doc.get(p.get("Predictor"), 1) or 1)
    if pred < 10:
        return raw
    cols, colors, bpc = int(doc.get(p.get("Columns"), 1)), int(doc.get(p.get("Colors"), 1)), int(doc.get(p.get("BitsPerComponent"), 8))
    bpp = max(1, colors * bpc // 8)
    row = (colors * bpc * cols + 7) // 8
    out, prev = bytearray(), bytearray(row)
    for i in range(0, len(raw) - row, row + 1):
        ft, cur = raw[i], bytearray(raw[i + 1:i + 1 + row])
        for j in range(row):
            a = cur[j - bpp] if j >= bpp else 0
            b = prev[j]
            c = prev[j - bpp] if j >= bpp else 0
            if ft == 1:
                cur[j] = (cur[j] + a) & 255
            elif ft == 2:
                cur[j] = (cur[j] + b) & 255
            elif ft == 3:
                cur[j] = (cur[j] + (a + b) // 2) & 255
            elif ft == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                cur[j] = (cur[j] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += cur
        prev = cur
    return bytes(out)


# ---------------------------------------------------------------- fonts
_GLYPHS = {
    "space": " ", "period": ".", "comma": ",", "hyphen": "-", "minus": "−", "endash": "–", "emdash": "—", "bullet": "•",
    "quoteright": "’", "quoteleft": "‘", "quotedblleft": "“", "quotedblright": "”", "quotesingle": "'", "quotedbl": '"',
    "parenleft": "(", "parenright": ")", "bracketleft": "[", "bracketright": "]", "slash": "/", "backslash": "\\", "colon": ":",
    "semicolon": ";", "percent": "%", "dollar": "$", "ampersand": "&", "asterisk": "*", "plus": "+", "equal": "=", "less": "<",
    "greater": ">", "question": "?", "exclam": "!", "at": "@", "numbersign": "#", "underscore": "_", "asciitilde": "~", "asciicircum": "^",
    "braceleft": "{", "braceright": "}", "bar": "|", "fi": "fi", "fl": "fl", "ff": "ff", "ffi": "ffi", "ffl": "ffl", "copyright": "©",
    "registered": "®", "trademark": "™", "degree": "°", "sterling": "£", "Euro": "€", "yen": "¥", "cent": "¢",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "nbspace": " ", "uni00A0": " ", "ellipsis": "…", "section": "§", "multiply": "×", "periodcentered": "·",
}


def _glyph(name):
    if name in _GLYPHS:
        return _GLYPHS[name]
    if len(name) == 1:
        return name
    m = re.fullmatch(r"uni([0-9A-Fa-f]{4})", name) or re.fullmatch(r"u([0-9A-Fa-f]{4,6})", name)
    if m:
        try:
            return chr(int(m.group(1), 16))
        except ValueError:
            return ""
    if re.fullmatch(r"[A-Za-z]grave|[A-Za-z]acute|[A-Za-z]circumflex|[A-Za-z]dieresis|[A-Za-z]tilde", name):
        return name[0]
    return ""


def _cmap(raw):
    """A ToUnicode CMap: code -> text, and how many bytes one code takes."""
    m, widths = {}, set()
    for blk in re.findall(rb"begincodespacerange(.*?)endcodespacerange", raw, re.S):
        for a in re.findall(rb"<([0-9A-Fa-f]+)>", blk):
            widths.add(len(a) // 2)
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", raw, re.S):
        for a, b in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", blk):
            m[int(a, 16)] = _utf16(b)
            widths.add(len(a) // 2) if not widths else None
    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", raw, re.S):
        for lo, hi, rest in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])", blk):
            a, b = int(lo, 16), int(hi, 16)
            if b - a > 70000:
                continue
            if rest.startswith(b"["):
                for i, d in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", rest)):
                    m[a + i] = _utf16(d)
            else:
                base = int(rest[1:-1] or b"0", 16)
                step_w = len(rest[1:-1])
                for i in range(b - a + 1):
                    m[a + i] = _utf16(format(base + i, "0%dx" % step_w).encode())
            widths.add(len(lo) // 2) if not widths else None
    return m, (max(widths) if widths else 1), (min(widths) if widths else 1)


def _utf16(h):
    try:
        return unicodedata.normalize("NFKC", binascii.unhexlify(h if len(h) % 2 == 0 else h + b"0").decode("utf-16-be", "replace"))
    except (binascii.Error, ValueError):
        return ""


class Font:
    """Turns the bytes a content stream shows back into text.

    A simple font (Type1, TrueType) always uses one byte per character, whatever its ToUnicode table claims: real PDFs
    declare a two-byte code range there and then list only the characters they use, so the table is consulted first and
    the font's own encoding (WinAnsi by default) fills the gaps. A composite font (Type0) uses the table's code width and
    has nothing to fall back on."""

    def __init__(self, doc, fd):
        self.unreadable = 0
        self.map, self.width, self.minw, self.codec, self.diff = None, 1, 1, "cp1252", {}
        sub = doc.get(fd.get("Subtype"))
        self.simple = sub != "Type0"
        if self.simple:
            enc = doc.get(fd.get("Encoding"))
            base = enc if isinstance(enc, str) else doc.get(enc.get("BaseEncoding")) if isinstance(enc, dict) else None
            if base == "MacRomanEncoding":
                self.codec = "mac_roman"
            elif base == "StandardEncoding":
                self.codec = "latin-1"
            if isinstance(enc, dict):
                code = 0
                for it in doc.get(enc.get("Differences"), []) or []:
                    it = doc.get(it)
                    if isinstance(it, (int, float)):
                        code = int(it)
                    elif isinstance(it, str):
                        self.diff[code] = _glyph(str(it))
                        code += 1
        tu = fd.get("ToUnicode")
        sd = doc.stream_of(tu) if tu is not None else (None, None)
        if sd[1]:
            raw = doc.stream_bytes(sd[0], sd[1])
            if raw:
                self.map, self.width, self.minw = _cmap(raw)
        if self.simple:
            self.width = self.minw = 1
        elif self.map is None:
            self.width = 2
        self.widths, self.dw = {}, None           # glyph widths in 1/1000 em; None when the font does not declare them
        if self.simple:
            first = doc.get(fd.get("FirstChar"), 0)
            ws = doc.get(fd.get("Widths"))
            if isinstance(ws, list) and isinstance(first, int):
                for i, w in enumerate(ws):
                    w = doc.get(w)
                    if isinstance(w, (int, float)):
                        self.widths[first + i] = w
                mw = doc.dict_of(fd.get("FontDescriptor")).get("MissingWidth")
                self.dw = mw if isinstance(mw, (int, float)) and mw else 500
        else:
            desc = doc.get(fd.get("DescendantFonts"))
            d0 = doc.dict_of(desc[0]) if isinstance(desc, list) and desc else {}
            dw = doc.get(d0.get("DW"), 1000)
            self.dw = dw if isinstance(dw, (int, float)) else 1000
            w = doc.get(d0.get("W"))
            i = 0
            while isinstance(w, list) and i < len(w):
                c0 = doc.get(w[i])
                nxt = doc.get(w[i + 1]) if i + 1 < len(w) else None
                if isinstance(c0, int) and isinstance(nxt, list):
                    for j, x in enumerate(nxt):
                        x = doc.get(x)
                        if isinstance(x, (int, float)):
                            self.widths[c0 + j] = x
                    i += 2
                elif isinstance(c0, int) and isinstance(nxt, int) and i + 2 < len(w):
                    x = doc.get(w[i + 2])
                    if isinstance(x, (int, float)) and nxt - c0 < 70000:
                        for c in range(c0, nxt + 1):
                            self.widths[c] = x
                    i += 3
                else:
                    break

    def advance(self, b):
        """How far the pen moves for these bytes, in 1/1000 em; None if the font gives no widths."""
        if self.dw is None:
            return None
        if self.simple:
            return sum(self.widths.get(c, self.dw) for c in b)
        step = max(self.width, 1)
        return sum(self.widths.get(int.from_bytes(b[i:i + step], "big"), self.dw) for i in range(0, len(b), step))

    def _byte(self, c):
        if c in self.diff:
            return self.diff[c]
        return bytes([c]).decode(self.codec, "replace") if c >= 32 or c in (9, 10) else ""

    def decode(self, b):
        if self.simple:
            out = []
            for c in b:
                t = self.map.get(c) if self.map else None
                out.append(t if t is not None else self._byte(c))
            return unicodedata.normalize("NFKC", "".join(out))
        if self.map is None:                         # a composite font with no table: its codes are glyph numbers
            self.unreadable += len(b) // 2
            return ""
        out, i = [], 0
        while i < len(b):
            if self.width >= 2 and i + 1 < len(b):
                code = (b[i] << 8) | b[i + 1]
                t = self.map.get(code)
                step = 2
                if t is None and self.minw == 1:     # mixed one- and two-byte codes
                    code, step = b[i], 1
                    t = self.map.get(code)
            else:
                code, step = b[i], 1
                t = self.map.get(code)
            if t is None:
                self.unreadable += 1
            else:
                out.append(t)
            i += step
        return "".join(out)


# ---------------------------------------------------------------- pages and text
def _pages(doc):
    """Page dictionaries in reading order, each with its inherited Resources."""
    root = next((d for d, _ in (v for v in doc.objs.values()) if isinstance(d, dict) and d.get("Type") == "Catalog"), None)
    out = []

    def walk(node, inherited, depth=0):
        node = doc.dict_of(node)
        if not node or depth > 40 or len(out) >= MAX_PAGES:
            return
        res = node.get("Resources", inherited)
        if node.get("Type") == "Pages" or "Kids" in node:
            for k in doc.get(node.get("Kids"), []) or []:
                walk(k, res, depth + 1)
        else:
            out.append((node, res))
    if root:
        walk(root.get("Pages"), None)
    if not out:                                   # no usable tree: take every page object in file order
        for num in sorted(doc.objs):
            d = doc.objs[num][0]
            if isinstance(d, dict) and d.get("Type") == "Page":
                out.append((d, d.get("Resources")))
                if len(out) >= MAX_PAGES:
                    break
    return out


def _content(doc, page):
    c = doc.get(page.get("Contents"))
    refs = page.get("Contents")
    items = refs if isinstance(refs, list) else [refs]
    data = []
    for it in items:
        if it is None:
            continue
        d, span = doc.stream_of(it) if isinstance(it, Ref) else (None, None)
        if span and isinstance(d, dict):
            raw = doc.stream_bytes(d, span)
            if raw:
                data.append(raw)
    return b"\n".join(data)


def _show(font, s, cur, st, eff):
    """Add a shown string to the current line. A gap is a space only if the pen really moved past the end of the last
    text by more than a sliver of an em; with the font's glyph widths that is exact, without them it is a guess."""
    if font is None:
        return
    t = font.decode(s)
    if not t:
        return
    gap = None
    if st["pen"] is not None and st["end"] is not None and eff:
        gap = (st["pen"] - st["end"]) / eff
    if cur and not cur[-1].endswith(" ") and not t.startswith(" "):
        if (gap is not None and gap > 0.15) or (gap is None and st["need_space"]) or st["force_space"]:
            cur.append(" ")
    st["need_space"] = st["force_space"] = False
    cur.append(t)
    adv = font.advance(s)
    if adv is not None and st["pen"] is not None:
        st["pen"] += adv * eff / 1000.0
        st["end"] = st["pen"]
    else:
        st["end"] = None            # widths unknown: the next gap cannot be measured


def _page_lines(content, fonts):
    lines, cur = [], []
    st = {"need_space": False, "force_space": False, "pen": None, "end": None}
    font, size, y, scale, leading, line_x = None, 10.0, None, 1.0, 0.0, 0.0
    prev_y, fresh = None, False        # a new BT block restarts at the origin; its first move is compared with the last line
    stack = []
    pos, n = 0, len(content)

    def newline():
        nonlocal cur
        t = re.sub(r"[ \t]+", " ", "".join(cur)).strip()
        t = re.sub(r" ([,.;:)%’])", r"\1", t)          # a gap can still land before punctuation
        t = re.sub(r"([(‘$]) ", r"\1", t)
        t = re.sub(r"([a-z]) -([a-z])", r"\1-\2", t)      # "best -selling": the hyphen was placed on its own
        if t:
            lines.append(t)
        cur = []
        st.update(need_space=False, force_space=False, end=None)

    def eff():
        return abs(size) * scale

    while pos < n:
        m = _TOKEN.match(content, pos)
        if not m:
            pos += 1
            continue
        pos = m.end()
        k = m.lastgroup
        if k == "ws":
            continue
        v = m.group()
        if k == "num":
            stack.append(float(v))
        elif k == "name":
            stack.append(Name(v[1:].decode("latin-1")))
        elif k == "str":
            stack.append(_unescape(v[1:-1]))
        elif k == "hex":
            stack.append(_hex(v[1:-1]))
        elif k == "arr_open":
            stack.append("[")
        elif k == "arr_close":
            j = len(stack) - 1
            while j >= 0 and stack[j] != "[":
                j -= 1
            arr = stack[j + 1:] if j >= 0 else []
            del stack[max(j, 0):]
            stack.append(arr)
        elif k in ("dict_open", "dict_close"):
            continue
        else:
            op = v.decode("latin-1")
            if op == "BI":                                    # an inline image: skip its binary body
                e = content.find(b"EI", pos)
                pos = n if e < 0 else e + 2
                stack.clear()
                continue
            nums = len(stack) >= 2 and all(isinstance(x, (int, float)) for x in stack[-2:])
            if op == "Tf" and len(stack) >= 2:
                font = fonts.get(stack[-2]) if isinstance(stack[-2], str) else font
                size = float(stack[-1]) if isinstance(stack[-1], (int, float)) and stack[-1] else size
            elif op in ("Td", "TD") and nums:
                tx, ty = stack[-2], stack[-1]
                if op == "TD":
                    leading = -ty
                line_x += tx * scale
                st["pen"] = line_x
                new_y = (y or 0.0) + ty * scale
                ref = prev_y if fresh and prev_y is not None else (y if y is not None and not fresh else None)
                moved = abs(new_y - ref) if ref is not None else abs(ty)
                fresh = False
                y = new_y
                if moved > 0.35 * max(abs(size), 0.1):
                    newline()
                elif tx and st["end"] is None and abs(tx) > 0.15 * max(abs(size), 0.1):
                    st["need_space"] = True
            elif op == "Tm" and len(stack) >= 6 and all(isinstance(x, (int, float)) for x in stack[-6:]):
                a, b_, c_, d_, e_, f_ = stack[-6:]
                scale = max(abs(a), 0.01)
                ref = prev_y if fresh and prev_y is not None else (y if not fresh else None)
                fresh = False
                if ref is not None and abs(f_ - ref) > 0.35 * abs(size) * max(abs(d_), 0.01):
                    newline()
                elif ref is not None and st["end"] is None:
                    st["need_space"] = True
                y = f_
                line_x = e_
                st["pen"] = e_
            elif op == "TL" and stack and isinstance(stack[-1], (int, float)):
                leading = stack[-1]
            elif op == "T*":
                newline()
                st["pen"] = line_x
            elif op == "Tj" and stack and isinstance(stack[-1], bytes):
                _show(font, stack[-1], cur, st, eff())
            elif op == "TJ" and stack and isinstance(stack[-1], list):
                for it in stack[-1]:
                    if isinstance(it, bytes):
                        _show(font, it, cur, st, eff())
                    elif isinstance(it, (int, float)):
                        if st["pen"] is not None:
                            st["pen"] -= it / 1000.0 * eff()
                        if it < -150:                          # a justified-text word gap, not a kerning nudge
                            st["force_space"] = True
            elif op in ("'", '"') and stack and isinstance(stack[-1], bytes):
                newline()
                st["pen"] = line_x
                _show(font, stack[-1], cur, st, eff())
            elif op == "BT":
                prev_y, y, line_x, fresh = y, 0.0, 0.0, True
                st["pen"] = 0.0
            elif op == "ET":
                st["need_space"] = True
            stack.clear()
    newline()
    return lines


def extract(data, max_chars=MAX_CHARS):
    """Lines of text from a PDF, in reading order; PdfError when nothing readable can be got out of it."""
    doc = Doc(data)
    pages = _pages(doc)
    if not pages:
        raise PdfError("Tick could not find any pages in that PDF. Open it, copy the text, and paste it here instead.")
    font_cache, lines, total, unreadable = {}, [], 0, 0
    for page, res in pages:
        if time.monotonic() > doc.deadline:
            break
        fonts = {}
        for name, ref in doc.dict_of(doc.dict_of(res).get("Font")).items():
            key = ref[0] if isinstance(ref, Ref) else id(ref)
            if key not in font_cache:
                font_cache[key] = Font(doc, doc.dict_of(ref))
            fonts[name] = font_cache[key]
        for ln in _page_lines(_content(doc, page), fonts):
            lines.append(ln)
            total += len(ln)
        lines.append("")
        if total > max_chars:
            break
    unreadable = sum(f.unreadable for f in font_cache.values())
    text_chars = sum(len(x) for x in lines)
    if text_chars < 120:
        if unreadable > 20:
            raise PdfError("The text in that PDF uses an encoding Tick cannot read. Open it, copy the text, and paste it here instead.")
        raise PdfError("That PDF has no readable text (it may be a scan, which is a picture of a page). Paste the text instead.")
    return lines[:200000]
