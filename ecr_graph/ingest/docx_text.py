"""Stdlib OOXML (.docx) reader that keeps tables addressable.

Output is *line-numbered derived text*: one paragraph per line, one table row
per line prefixed with ``[T<table>R<row>]``. Nested tables get dotted ids
(``T3.1``). Check boxes become ``■`` (checked) / ``□`` (unchecked), embedded
images become ``[IMG n]`` so a reviewer knows content was not read.

The derived text is the evidence substrate: every evidence locator points at
``(path, line_start, line_end)`` in it, and the original's SHA-256 is recorded
alongside so the text can always be traced back to the binary.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
NS = {"w": W, "w14": W14}

CHECKED_SYM = {"F0FE", "F0FD", "F078", "F052", "F06E", "F0A2", "2612", "25A0", "F053"}
UNCHECKED_SYM = {"F0A8", "F06F", "F071", "F0A3", "2610", "25A1", "F0A1"}


def q(tag: str) -> str:
    p, t = tag.split(":")
    return "{%s}%s" % (NS[p], t)


@dataclass
class DerivedText:
    lines: List[str] = field(default_factory=list)
    tables: int = 0
    images: int = 0
    checkboxes: int = 0

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


class _Reader:
    def __init__(self) -> None:
        self.out = DerivedText()

    # ---- inline content ------------------------------------------------
    def run_text(self, node) -> str:
        parts: List[str] = []
        for el in node.iter():
            tag = el.tag
            if tag == q("w:t"):
                parts.append(el.text or "")
            elif tag == q("w:tab"):
                parts.append("\t")
            elif tag in (q("w:br"), q("w:cr")):
                parts.append(" ")
            elif tag == q("w:sym"):
                code = (el.get(q("w:char")) or "").upper()
                if code in CHECKED_SYM:
                    parts.append("■"); self.out.checkboxes += 1
                elif code in UNCHECKED_SYM:
                    parts.append("□"); self.out.checkboxes += 1
            elif tag == q("w14:checkbox"):
                checked = el.find(q("w14:checked"))
                val = checked.get(q("w14:val")) if checked is not None else "0"
                parts.append("■" if val in ("1", "true") else "□"); self.out.checkboxes += 1
            elif tag == q("w:checkBox"):  # legacy form field
                c = el.find(q("w:checked"))
                if c is None:
                    c = el.find(q("w:default"))
                val = c.get(q("w:val"), "1") if c is not None else "0"
                parts.append("■" if val in ("1", "true") else "□"); self.out.checkboxes += 1
            elif tag in (q("w:drawing"), "{urn:schemas-microsoft-com:vml}imagedata"):
                self.out.images += 1
                parts.append(f"[IMG {self.out.images}]")
        # w14 sdt checkboxes also carry a w:t glyph; collapse doubled glyphs
        text = "".join(parts)
        text = re.sub(r"([■□])[☐☒✓✔■□]", r"\1", text)
        return text

    def paragraph(self, p) -> str:
        return re.sub(r"[ 　]+", " ", self.run_text(p)).strip()

    # ---- block content -------------------------------------------------
    def block(self, parent, table_prefix: str = "") -> None:
        for child in list(parent):
            if child.tag == q("w:p"):
                line = self.paragraph(child)
                if line:
                    self.out.lines.append(line)
            elif child.tag == q("w:tbl"):
                self.table(child, table_prefix)
            elif child.tag == q("w:sdt"):
                content = child.find(q("w:sdtContent"))
                if content is not None:
                    self.block(content, table_prefix)

    def table(self, tbl, prefix: str) -> None:
        self.out.tables += 1
        tid = f"{prefix}.{self._nested_counter(prefix)}" if prefix else str(self._top_counter())
        for r_idx, tr in enumerate(tbl.findall(q("w:tr")), 1):
            cells: List[str] = []
            nested = []
            for tc in tr.findall(q("w:tc")):
                tcpr = tc.find(q("w:tcPr"))
                span = 1
                vmerge_continue = False
                if tcpr is not None:
                    gs = tcpr.find(q("w:gridSpan"))
                    if gs is not None:
                        span = int(gs.get(q("w:val"), "1") or 1)
                    vm = tcpr.find(q("w:vMerge"))
                    if vm is not None and vm.get(q("w:val"), "continue") == "continue":
                        vmerge_continue = True
                paras = []
                for el in list(tc):
                    if el.tag == q("w:p"):
                        t = self.paragraph(el)
                        if t:
                            paras.append(t)
                    elif el.tag == q("w:tbl"):
                        nested.append(el)
                cell = " ".join(paras)
                if vmerge_continue and not cell:
                    cell = "⟨merged⟩"
                cells.append(cell)
                cells.extend([""] * (span - 1))
            self.out.lines.append(f"[T{tid}R{r_idx}] " + " | ".join(cells))
            for n in nested:
                self.table(n, f"T{tid}R{r_idx}".lstrip("T"))

    _top = 0
    _nested: dict = {}

    def _top_counter(self) -> int:
        self._top += 1
        return self._top

    def _nested_counter(self, prefix: str) -> int:
        self._nested = dict(self._nested)
        self._nested[prefix] = self._nested.get(prefix, 0) + 1
        return self._nested[prefix]


def read_docx(path: Path) -> DerivedText:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find(q("w:body"))
    reader = _Reader()
    if body is not None:
        reader.block(body)
    return reader.out
