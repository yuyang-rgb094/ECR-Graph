"""Deterministic, profile-driven extraction from one ECR's derived text.

Produces source-backed records only. Anything that needs judgement (engineering
objects, synonyms, identity of product labels) is left to agent candidates and
the resolution stage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..model import RULE_DERIVED, SOURCE_ASSERTION, Entity, Evidence, Triple
from ..util import normalize_label, stable_id

MARKER = re.compile(r"^\[T([\w.]+?)R(\d+)\]\s?")
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def cn_to_int(token: str) -> int:
    token = token.strip()
    if token.isdigit():
        return int(token)
    if token == "十":
        return 10
    if token.startswith("十"):
        return 10 + CN_NUM.get(token[1:], 0)
    if "十" in token:
        a, _, b = token.partition("十")
        return CN_NUM.get(a, 1) * 10 + (CN_NUM.get(b, 0) if b else 0)
    return CN_NUM.get(token, 0)


@dataclass
class Line:
    no: int
    raw: str
    table: Optional[str]
    row: Optional[int]
    cells: List[str]


def parse_lines(text_lines: List[str]) -> List[Line]:
    out = []
    for i, raw in enumerate(text_lines, 1):
        m = MARKER.match(raw)
        body = raw[m.end():] if m else raw
        cells = [c.strip() for c in body.split(" | ")] if m else [body.strip()]
        out.append(Line(i, raw, m.group(1) if m else None, int(m.group(2)) if m else None, cells))
    return out


@dataclass
class ExtractResult:
    entities: Dict[str, Entity] = field(default_factory=dict)
    triples: List[Triple] = field(default_factory=list)
    transitions: List[dict] = field(default_factory=list)
    change_points: List[dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_entity(self, ent: Entity) -> Entity:
        if ent.id in self.entities:
            cur = self.entities[ent.id]
            merge_attributes(cur.attributes, ent.attributes)
            known = {e.evidence_id for e in cur.evidence}
            cur.evidence.extend(e for e in ent.evidence if e.evidence_id not in known)
            return cur
        self.entities[ent.id] = ent
        return ent


class ECRExtractor:
    def __init__(self, profile: dict):
        self.p = profile
        self.re_section = re.compile(profile["section_header"])
        self.re_cp = re.compile(profile["change_point_header"])
        self.re_ref = re.compile(profile["change_point_reference"])
        self.re_split = re.compile(profile["product_split"])
        self.field_labels = {k: v for k, v in profile["fields"].items()}
        label_alt = "|".join(sorted({re.escape(l) for ls in self.field_labels.values() for l in ls}, key=len, reverse=True))
        self.re_field = re.compile(rf"({label_alt})\s*[:：]")

    # ------------------------------------------------------------------ helpers
    def evidence(self, sid: str, path: str, lines: List[Line], sha: str, section_path: str) -> Evidence:
        # quote = the first line (lines in a range may be non-contiguous; the quote must be verbatim)
        return Evidence(sid, path, lines[0].no, lines[-1].no, lines[0].raw[:600], section_path, sha)

    def header_map(self, cells: List[str]) -> Dict[str, int]:
        cols = {}
        for canon, aliases in self.p["attachment_columns"].items():
            for idx, cell in enumerate(cells):
                c = normalize_label(cell)
                if any(normalize_label(a) == c or (len(a) > 2 and normalize_label(a) in c) for a in aliases):
                    cols.setdefault(canon, idx)
                    break
        return cols if len(cols) >= self.p["attachment_min_columns"] and "file_number" in cols else {}

    def operation(self, text: str) -> str:
        for op, words in self.p["operations"].items():
            if any(w in text for w in words):
                return op
        return "unspecified"

    def refs(self, text: str, implicit_section: Optional[int]) -> List[Tuple[int, Optional[int]]]:
        out = []
        for m in self.re_ref.finditer(text):
            sec = cn_to_int(m.group(1))
            pts = m.group(2)
            if pts:
                out.extend((sec, n) for n in expand_numbers(pts))
            else:
                out.append((sec, None))
        if not out and implicit_section is not None:
            for n in re.findall(r"(?:更改|变更)点\s*([\d、,，/和及至~\-\s]+)", text):
                out.extend((implicit_section, k) for k in expand_numbers(n))
        return out

    def checkbox_selected(self, text: str) -> List[str]:
        return [s.strip(" ：:|") for s in re.findall(r"■\s*([^■□|]+)", text) if s.strip(" ：:|")]

    # ------------------------------------------------------------------ main
    def extract(self, source_id: str, text_lines: List[str], text_path: str, source_sha: str = "") -> ExtractResult:
        res = ExtractResult()
        lines = parse_lines(text_lines)
        ecr_id = source_id
        ecr = res.add_entity(Entity(ecr_id, "ECR", ecr_id, {"source_sha256": source_sha, "sections": {}},
                                    [self.evidence(source_id, text_path, lines[:1], source_sha, "header")] if lines else []))
        section = 1
        cp: Optional[dict] = None
        cps: Dict[Tuple[int, int], dict] = {}
        table_mode: Optional[Tuple[str, Dict[str, int]]] = None
        section_seen_explicit = False

        def close_cp():
            if cp is None:
                return
            key = (cp["section"], cp["point"])
            if key in cps:  # the same point re-appears later (e.g. an assessment block): append, never overwrite
                prev = cps[key]
                prev["lines"].extend(l for l in cp["lines"] if l.no not in {x.no for x in prev["lines"]})
                prev["text"].extend(cp["text"])
            else:
                cps[key] = cp

        for ln in lines:
            # ---- attachment tables -------------------------------------------------
            if ln.table is not None:
                hm = self.header_map(ln.cells)
                if hm:
                    table_mode = (ln.table, hm)
                    continue
                if table_mode and table_mode[0] == ln.table:
                    self._row(res, ecr_id, ln, table_mode[1], text_path, source_sha,
                              section if section_seen_explicit else None)
                    continue
                table_mode = None
            # ---- section-level check boxes --------------------------------------
            for group, label in self.p["checkbox_groups"].items():
                for ci, cell in enumerate(ln.cells):
                    m = re.search(label, cell)
                    if not m:
                        continue
                    seg = cell[m.start():]
                    if "■" not in seg and "□" not in seg and ci + 1 < len(ln.cells):
                        seg = seg + " " + ln.cells[ci + 1]  # label and boxes in adjacent cells
                    if "■" not in seg and "□" not in seg:
                        continue
                    body = seg.split("：", 1)[-1] if "：" in seg else seg[m.end() - m.start():]
                    picked = self.checkbox_selected(body)
                    sel = ecr.attributes["sections"].setdefault(str(section), {}).setdefault(group, [])
                    sel.extend(s for s in picked if s not in sel)
                    ecr.attributes.setdefault("form_checkboxes", []).append(
                        {"group": group, "selected": picked, "line": ln.no, "section_context": section})
            # ---- headers and change point bodies --------------------------------
            for cell in ln.cells:
                ms = self.re_section.match(cell)
                if ms:
                    close_cp()
                    cp = None
                    section = cn_to_int(ms.group(1)) or section
                    section_seen_explicit = True
                    cell = cell[ms.end():].strip()
                # a cell may hold several change points ("…。 更改点2：…"); split at each header
                heads = [m for m in self.re_cp.finditer(cell)
                         if m.start() == 0 or cell[m.start() - 1] in " \t。；;）)】]：:"]
                cuts = [0] + [m.start() for m in heads] + [len(cell)]
                for i in range(len(cuts) - 1):
                    seg = cell[cuts[i]:cuts[i + 1]].strip()
                    mc = self.re_cp.match(seg) if i > 0 else None  # segment 0 = text before the first header
                    if mc:
                        close_cp()
                        rest = seg[mc.end():].strip()
                        title = self.re_field.split(rest)[0].strip() if rest else ""
                        cp = {"section": section, "point": int(mc.group(1)), "title": title[:80], "lines": [ln], "text": [rest]}
                    elif cp is not None and seg:
                        if cp["lines"][-1].no != ln.no:
                            cp["lines"].append(ln)
                        cp["text"].append(seg)
        close_cp()
        for (sec, pt), c in sorted(cps.items()):
            self._change_point(res, ecr_id, c, text_path, source_sha)
        res.change_points.sort(key=lambda r: (r["section"], r["point"]))
        # link transitions to change points
        known = {(c["section"], c["point"]) for c in res.change_points}
        for t in res.transitions:
            resolved, unresolved = [], []
            for sec, pt in t.pop("_refs"):
                if pt is None:
                    resolved.extend(cp_id(ecr_id, s, p) for s, p in sorted(known) if s == sec)
                elif (sec, pt) in known:
                    resolved.append(cp_id(ecr_id, sec, pt))
                else:
                    unresolved.append(f"S{sec}P{pt}")
            t["change_point_ids"] = sorted(set(resolved))
            t["unresolved_refs"] = unresolved
            subj = t["change_point_ids"] or [ecr_id]
            ev = [Evidence(**t["evidence"])]
            for s in subj:
                res.triples.append(Triple(s, "changes_document", t["document_id"], SOURCE_ASSERTION, 0.95,
                                          {"operation": t["operation"], "old_version": t["old_version"],
                                           "new_version": t["new_version"], "row_id": t["row_id"],
                                           "assignment_scope": "change_point" if t["change_point_ids"] else "ecr_level"},
                                          ev))
        return res

    # ------------------------------------------------------------------ records
    def _change_point(self, res: ExtractResult, ecr_id: str, c: dict, path: str, sha: str) -> None:
        cid = cp_id(ecr_id, c["section"], c["point"])
        body = " ".join(c["text"])
        fields = split_fields(body, self.re_field, self.field_labels)
        sec_path = f"section{c['section']}/point{c['point']}"
        ev = self.evidence(ecr_id, path, c["lines"], sha, sec_path)
        domains = []
        for dom, labels in self.p["domains"].items():
            for lab in labels:
                m = re.search(re.escape(lab) + r"\s*[:：]\s*([^。；;]{0,40})", body)
                if m and not re.match(self.p["not_involved"], m.group(1).strip()):
                    domains.append(dom)
                    break
        attrs = {"ecr_id": ecr_id, "section": c["section"], "point": c["point"], "title": c["title"],
                 "body": body, **fields, "domains": domains}
        res.add_entity(Entity(cid, "ChangePoint", f"{ecr_id} S{c['section']:02d}P{c['point']:02d} {c['title']}"[:120], attrs, [ev]))
        res.triples.append(Triple(ecr_id, "has_change_point", cid, SOURCE_ASSERTION, 1.0, {}, [ev]))
        for d in domains:
            res.triples.append(Triple(cid, "involves_domain", f"DOM-{d}", RULE_DERIVED, 0.8,
                                      {"rule": "domain label followed by non-empty, non-'not involved' text"}, [ev]))
        res.change_points.append({"id": cid, **{k: v for k, v in attrs.items() if k != "body"},
                                  "evidence": ev.to_dict()})

    def _row(self, res: ExtractResult, ecr_id: str, ln: Line, hm: Dict[str, int], path: str, sha: str,
             implicit_section: Optional[int]) -> None:
        def cell(name: str) -> str:
            i = hm.get(name)
            return ln.cells[i].strip() if i is not None and i < len(ln.cells) else ""

        number = cell("file_number")
        if not number or number == "⟨merged⟩":
            return
        disposition = cell("disposition")
        whole = " ".join(ln.cells)
        op = self.operation(disposition or whole)
        old_v, new_v = cell("old_version"), cell("new_version")
        doc_id = f"DOC-{number}"
        ev = Evidence(ecr_id, path, ln.no, ln.no, ln.raw[:600], f"table{ln.table}/row{ln.row}", sha)
        res.add_entity(Entity(doc_id, "Document", number, {"file_number": number, "titles": [cell("file_title")]}, [ev]))
        products = [p.strip() for p in self.re_split.split(cell("product")) if p.strip() and p.strip() != "⟨merged⟩"]
        for p in products:
            pid = stable_id("PRD", normalize_label(p), length=10)
            res.add_entity(Entity(pid, "ProductLabel", p, {"raw_label": p}, [ev]))
            res.triples.append(Triple(doc_id, "applicable_to", pid, SOURCE_ASSERTION, 0.95, {"ecr_id": ecr_id}, [ev]))
        for v in (old_v, new_v):
            if v and v not in ("/", "-", "—"):
                res.add_entity(Entity(f"{doc_id}@{v}", "DocumentVersion", f"{number} {v}", {"file_number": number, "version": v}, [ev]))
                res.triples.append(Triple(f"{doc_id}@{v}", "version_of", doc_id, SOURCE_ASSERTION, 1.0, {}, [ev]))
        if old_v and new_v and old_v not in ("/", "-") and new_v not in ("/", "-"):
            res.triples.append(Triple(f"{doc_id}@{old_v}", "superseded_by", f"{doc_id}@{new_v}", SOURCE_ASSERTION, 0.95,
                                      {"ecr_id": ecr_id}, [ev]))
        res.transitions.append({
            "row_id": f"{ecr_id}-L{ln.no}", "ecr_id": ecr_id, "document_id": doc_id, "file_number": number,
            "file_title": cell("file_title"), "old_version": old_v, "new_version": new_v, "operation": op,
            "products": products, "affects_registration_raw": cell("affects_registration"),
            "disposition_raw": disposition, "_refs": self.refs(disposition or whole, implicit_section),
            "evidence": ev.to_dict(),
        })


def expand_numbers(text: str) -> List[int]:
    """'1、3/5' → [1, 3, 5];  '1-4' / '1~4' / '1至4' → [1, 2, 3, 4] (ranges capped at 50)."""
    out: List[int] = []
    for a, b in re.findall(r"(\d+)\s*(?:[-~～至]\s*(\d+))?", text):
        lo = int(a)
        hi = int(b) if b else lo
        if hi < lo or hi - lo > 50:
            hi = lo
        out.extend(range(lo, hi + 1))
    return out


def merge_attributes(cur: dict, new: dict) -> None:
    for k, v in new.items():
        if k not in cur:
            cur[k] = v
        elif isinstance(cur[k], list) and isinstance(v, list):
            cur[k].extend(x for x in v if x not in cur[k])


def cp_id(ecr_id: str, section: int, point: int) -> str:
    return f"CP-{ecr_id}-S{section:02d}P{point:02d}"


def split_fields(body: str, re_field, labels: Dict[str, List[str]]) -> Dict[str, str]:
    lookup = {l: k for k, ls in labels.items() for l in ls}
    parts = re_field.split(body)
    out: Dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        key = lookup.get(parts[i])
        if key and key not in out:
            out[key] = parts[i + 1].strip(" ；;|")
    return out
