"""Small text helpers shared by the annual-report reader (company.py) and Tick's profit lens (lens.py)."""
import re

# not after abbreviations: "U.S. District Court" and "Apple Inc. announced" are not sentence ends
_SENT = re.compile(r"(?<!\bU\.S\.)(?<!\bInc\.)(?<!\bCo\.)(?<!\bCorp\.)(?<!\bLtd\.)(?<!\bNo\.)(?<!\bvs\.)(?<!\bSt\.)(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bMrs\.)(?<=[.!?])\s+(?=[A-Z\"“(])")


def sentences(text):
    out = []
    for line in text.split("\n"):
        for s in _SENT.split(line):
            s = s.strip().lstrip("•·▪●‣◦ ")   # bullet glyphs the HTML puts in front of list items
            if s:
                out.append(s)
    return out
