"""HTML → line-numbered derived text (same format as docx_text).

Used for legacy .doc files converted by macOS ``textutil -convert html``,
which keeps tables (its .docx output does not), and for any HTML export.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional

from .docx_text import DerivedText

BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br"}
PUA = {"": "■", "": "■", "": "■", "": "■", "": "□", "": "□", "": "□",
       "☒": "■", "☐": "□"}


class _Table:
    def __init__(self, tid: str):
        self.tid = tid
        self.rows: List[List[str]] = []
        self.row: Optional[List[str]] = None
        self.cell: Optional[List[str]] = None
        self.nested = 0
        self.pending_nested: List[tuple] = []  # (row_idx, _Table)


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = DerivedText()
        self.stack: List[_Table] = []
        self.buf: List[str] = []
        self.top = 0
        self.skip = 0

    # -- helpers
    def flush_para(self):
        text = re.sub(r"[ \t　\xa0]+", " ", "".join(self.buf)).strip()
        self.buf = []
        if text:
            self.out.lines.append(text)

    def emit(self, t: _Table):
        for r_idx, cells in enumerate(t.rows, 1):
            self.out.lines.append(f"[T{t.tid}R{r_idx}] " + " | ".join(cells))
            for ri, nt in t.pending_nested:
                if ri == r_idx:
                    self.emit(nt)

    # -- events
    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self.skip += 1
        elif tag == "table":
            if self.stack:
                parent = self.stack[-1]
                parent.nested += 1
                row_idx = len(parent.rows) + (1 if parent.row is not None else 0)
                t = _Table(f"{parent.tid}R{row_idx}.{parent.nested}")
                parent.pending_nested.append((row_idx, t))
            else:
                self.flush_para()
                self.top += 1
                t = _Table(str(self.top))
            self.out.tables += 1
            self.stack.append(t)
        elif tag == "tr" and self.stack:
            self.stack[-1].row = []
        elif tag in ("td", "th") and self.stack:
            self.stack[-1].cell = []
            span = int(dict(attrs).get("colspan", "1") or 1)
            self.stack[-1]._span = span
        elif tag == "img":
            self.out.images += 1
            self._text(f"[IMG {self.out.images}]")
        elif tag in BLOCK:
            if self.stack and self.stack[-1].cell is not None:
                self.stack[-1].cell.append(" ")
            else:
                self.flush_para()

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th") and self.stack and self.stack[-1].cell is not None:
            t = self.stack[-1]
            text = re.sub(r"\s+", " ", "".join(t.cell)).strip()
            if t.row is None:
                t.row = []
            t.row.append(text)
            t.row.extend([""] * (getattr(t, "_span", 1) - 1))
            t.cell = None
        elif tag == "tr" and self.stack and self.stack[-1].row is not None:
            t = self.stack[-1]
            t.rows.append(t.row)
            t.row = None
        elif tag == "table" and self.stack:
            t = self.stack.pop()
            if not self.stack:
                self.emit(t)
        elif tag in BLOCK and not self.stack:
            self.flush_para()

    def _text(self, data: str):
        if self.skip:
            return
        data = "".join(PUA.get(ch, ch) for ch in data)
        self.out.checkboxes += sum(data.count(c) for c in "■□")
        if self.stack and self.stack[-1].cell is not None:
            self.stack[-1].cell.append(data)
        elif not self.stack:
            self.buf.append(data)

    def handle_data(self, data):
        self._text(data)


def read_html(path: Path) -> DerivedText:
    p = _Parser()
    p.feed(Path(path).read_text(encoding="utf-8", errors="replace"))
    p.flush_para()
    return p.out
