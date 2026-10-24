"""Small text helpers shared by the annual-report reader (company.py) and Tick's profit lens (lens.py)."""
import re

# not after abbreviations: "U.S. District Court" and "Apple Inc. announced" are not sentence ends
_SENT = re.compile(r"(?<!\bU\.S\.)(?<!\bInc\.)(?<!\bCo\.)(?<!\bCorp\.)(?<!\bLtd\.)(?<!\bNo\.)(?<!\bvs\.)(?<!\bSt\.)(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bMrs\.)(?<=[.!?])\s+(?=[A-Z\"“(])")


def unwrap_lines(lines):
    """Text out of a PDF is hard-wrapped at the page's line width, which would cut every sentence in half. Join lines
    until one ends a sentence; blank lines stay as paragraph breaks; a word split with a hyphen at the line end is
    put back together ("Sys-" + "tem")."""
    out, buf = [], ""
    for raw in lines:
        ln = raw.strip()
        if not ln:
            if buf:
                out.append(buf)
            buf = ""
        elif buf and buf.endswith("-") and ln[:1].islower() and len(buf) > 2 and buf[-2].isalpha():
            buf = buf[:-1] + ln
        elif buf and not re.search(r"[.!?:”\"]$", buf):
            buf += " " + ln
        else:
            if buf:
                out.append(buf)
            buf = ln
    if buf:
        out.append(buf)
    return out


def sentences(text):
    out = []
    for line in text.split("\n"):
        for s in _SENT.split(line):
            s = s.strip().lstrip("•·▪●‣◦ ")   # bullet glyphs the HTML puts in front of list items
            if s:
                out.append(s)
    return out
