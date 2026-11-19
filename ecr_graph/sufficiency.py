"""Change-content sufficiency review (变更内容充分性审查).

Question answered: *for each change point, do the revised versions of the
affected documents actually contain what the change requires?*

Two tiers:

1. **Deterministic** (no LLM): extract checkable facts from the change point —
   old→new pairs, values with units, version strings, material codes, quoted
   terms — and test them against the revised documents' text:

   - ``stale_old_value``: the old value is still present and the new one is not;
   - ``new_value_missing``: a required fact appears in none of the revised files;
   - ``class_missing_fact``: a fact type a document class must carry
     (e.g. a version in the software release record) is absent;
   - ``revision_not_stated``: the revised file never states its new version;
   - ``not_checkable``: a revised text is not available — sufficiency unknown.

2. **Semantic** (customer's agent): a review packet per (change point,
   document) with the change text, extracted facts, deterministic results and
   line-numbered excerpts. The agent answers in a fixed schema; every gap it
   reports must cite lines that verify, or explicitly state ``absent``.

Neither tier concludes "sufficient". The output is a list of candidate gaps for
the document owner and QA.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .crossref import classify
from .extract.candidates import quote_matches
from .model import Evidence, Finding, evidence_from_dict
from .package import Package
from .util import normalize_label, read_jsonl, stable_id


# ------------------------------------------------------------------ facts
def extract_facts(text: str, pack: dict) -> List[dict]:
    facts: List[dict] = []
    seen = set()
    for pat in pack.get("pair_patterns", []):
        for m in re.finditer(pat, text):
            old, new = m.group("old").strip(), m.group("new").strip()
            if old and new and normalize_label(old) != normalize_label(new):
                key = ("pair", old, new)
                # "将X由a改为b" also matches the generic pattern with old="X由a"; keep the tighter pair
                if any(f["new"] == new and normalize_label(old).endswith(normalize_label(f["old"])) for f in facts):
                    continue
                if key not in seen:
                    seen.add(key)
                    facts.append({"type": "pair", "old": old, "new": new, "span": m.group(0)[:120]})
    pair_values = {normalize_label(f[k]) for f in facts for k in ("old", "new")}
    for ftype, pat in pack.get("fact_patterns", {}).items():
        for m in re.finditer(pat, text):
            val = (m.group(1) if m.groups() else m.group(0)).strip()
            nv = normalize_label(val)
            if not nv or (ftype, nv) in seen or nv in pair_values:
                continue
            seen.add((ftype, nv))
            facts.append({"type": ftype, "value": val})
    return facts


def contains(lines_norm: str, value: str) -> bool:
    v = normalize_label(value)
    return bool(v) and v in lines_norm


def locate(lines: List[str], value: str, limit: int = 3) -> List[int]:
    v = normalize_label(value)
    return [i for i, l in enumerate(lines, 1) if v and v in normalize_label(l)][:limit]


# ------------------------------------------------------------------ revised documents
def index_revised(manifest: dict, work: Path, file_numbers: List[str]) -> Dict[str, dict]:
    """Map file numbers to revised derived texts (filename first, then document header)."""
    out: Dict[str, dict] = {}
    numbers = sorted(set(file_numbers), key=len, reverse=True)
    for e in manifest.get("documents", []):
        if e.get("role") != "revised" or not e.get("derived_text"):
            continue
        path = work / e["derived_text"]
        lines = path.read_text(encoding="utf-8").splitlines()
        head = " ".join(lines[:40])
        hit = next((n for n in numbers if n in e["original_name"]), None) or next((n for n in numbers if n in head), None)
        if hit:
            out.setdefault(hit, {"path": e["derived_text"], "lines": lines, "original_name": e["original_name"],
                                 "sha256": e["sha256"], "source_id": e["source_id"]})
    return out


# ------------------------------------------------------------------ review
def review(pkg: Package, revised: Dict[str, dict], pack: dict, doc_classes: Dict[str, str]) -> Dict:
    findings: List[Finding] = []
    packets: List[dict] = []
    stats = defaultdict(int)
    by_cp = defaultdict(list)
    for t in pkg.transitions:
        if t.get("operation") == "obsolete":
            continue
        for cp in t.get("change_point_ids") or []:
            by_cp[cp].append(t)
    req = pack.get("require_in_classes", {})
    rh = pack.get("revision_history", {})
    sr = pack.get("semantic_review", {})
    for cp in pkg.change_points:
        cid = cp["id"]
        cp_ev = evidence_from_dict(cp["evidence"])
        text = " ".join(str(cp.get(k) or "") for k in ("title", "solution")) or str(cp.get("title", ""))
        facts = extract_facts(text, pack)
        stats["change_points"] += 1
        stats["facts"] += len(facts)
        docs = by_cp.get(cid, [])
        available = [(t, revised[t["file_number"]]) for t in docs if t["file_number"] in revised]
        missing_text = [t for t in docs if t["file_number"] not in revised]
        stats["affected_documents"] += len(docs)
        stats["revised_text_available"] += len(available)
        if missing_text:
            findings.append(Finding(
                "sufficiency.not_checkable", "info", cid,
                f"{len(missing_text)} of {len(docs)} affected document(s) have no revised text; their content was not checked",
                [cp_ev], {"file_numbers": sorted({t['file_number'] for t in missing_text})}, "document control"))
        if not available:
            continue
        norm = {t["file_number"]: normalize_label(" ".join(r["lines"])) for t, r in available}
        # fact-level: must appear somewhere among the revised files
        for f in facts:
            target = f["new"] if f["type"] == "pair" else f["value"]
            where = [n for n in norm if contains(norm[n], target)]
            if not where:
                stats["new_value_missing"] += 1
                findings.append(Finding(
                    "sufficiency.new_value_missing", "high", cid,
                    f"'{target}' required by the change point is not found in any revised document "
                    f"({', '.join(sorted(norm))})", [cp_ev], {"fact": f}, "R&D document owner"))
        for t, r in available:
            n = t["file_number"]
            classes = classify(t.get("file_title", ""), n, doc_classes)
            # stale values
            for f in facts:
                if f["type"] != "pair":
                    continue
                old_hit = contains(norm[n], f["old"])
                new_hit = contains(norm[n], f["new"])
                if old_hit and not new_hit:
                    stats["stale_old_value"] += 1
                    lines = locate(r["lines"], f["old"])
                    ev = [Evidence(r["source_id"], r["path"], ln, ln, r["lines"][ln - 1][:300], "revised", r["sha256"])
                          for ln in lines]
                    findings.append(Finding(
                        "sufficiency.stale_old_value", "high", f"{cid}|{n}",
                        f"{n}: old value '{f['old']}' still present, new value '{f['new']}' absent", [cp_ev] + ev,
                        {"fact": f, "file_number": n}, "R&D document owner"))
                elif old_hit and new_hit:
                    findings.append(Finding(
                        "sufficiency.old_and_new_present", "low", f"{cid}|{n}",
                        f"{n}: both '{f['old']}' and '{f['new']}' present — confirm the old value only remains in "
                        "history/compatibility text", [cp_ev], {"fact": f, "file_number": n}, "R&D document owner"))
            # class expectations
            for ftype, cls_list in req.items():
                if not set(classes) & set(cls_list):
                    continue
                for f in facts:
                    if f["type"] == ftype or (f["type"] == "pair" and ftype == "version" and
                                              re.match(r"^[Vv]?\d+(\.\d+)+$", f["new"])):
                        val = f.get("value") or f.get("new")
                        if not contains(norm[n], val):
                            stats["class_missing_fact"] += 1
                            findings.append(Finding(
                                "sufficiency.class_missing_fact", "medium", f"{cid}|{n}",
                                f"{n} ({'/'.join(classes)}) is expected to carry {ftype} '{val}' but does not",
                                [cp_ev], {"fact": f, "classes": classes}, "R&D document owner"))
            # revision statement
            nv = t.get("new_version")
            if rh.get("expect_new_version_in_text") and nv and nv not in ("/", "-") and not contains(norm[n], nv):
                stats["revision_not_stated"] += 1
                findings.append(Finding("sufficiency.revision_not_stated", "medium", f"{cid}|{n}",
                                        f"{n}: revised text never states its new version {nv}", [cp_ev],
                                        {"file_number": n}, "document control"))
            if rh.get("expect_ecr_id_in_text") and not contains(norm[n], t["ecr_id"]):
                findings.append(Finding("sufficiency.ecr_not_cited", "low", f"{cid}|{n}",
                                        f"{n}: revision history does not cite {t['ecr_id']}", [cp_ev], {}, "document control"))
            packets.append(_packet(cp, t, r, facts, classes, sr))
    stats["packets"] = len(packets)
    return {"stats": dict(stats), "findings": [f.to_dict() for f in findings], "packets": packets}


def _packet(cp: dict, t: dict, r: dict, facts: List[dict], classes: List[str], sr: dict) -> dict:
    lines = r["lines"]
    keep = set(range(1, min(len(lines), sr.get("header_lines", 30)) + 1))
    w = sr.get("excerpt_window", 2)
    for f in facts:
        for val in [f.get("value"), f.get("old"), f.get("new")]:
            if val:
                for ln in locate(lines, val, 5):
                    keep.update(range(max(1, ln - w), min(len(lines), ln + w) + 1))
    for kw in re.findall(r"[一-鿿]{2,6}", cp.get("title", ""))[:6]:
        for ln in locate(lines, kw, 3):
            keep.update(range(max(1, ln - w), min(len(lines), ln + w) + 1))
    excerpt = [{"line": i, "text": lines[i - 1]} for i in sorted(keep)][: sr.get("max_excerpt_lines", 80)]
    return {
        "packet_id": stable_id("PKT", cp["id"], t["file_number"]),
        "change_point": {k: cp.get(k) for k in ("id", "title", "problem", "cause", "solution", "verification", "domains")},
        "document": {"file_number": t["file_number"], "title": t.get("file_title"), "old_version": t.get("old_version"),
                     "new_version": t.get("new_version"), "classes": classes, "text_path": r["path"],
                     "total_lines": len(lines)},
        "facts": facts,
        "excerpt": excerpt,
        "questions": [
            "Does the revised document state every requirement of the change point that belongs in a document of this kind?",
            "List each missing or inconsistent item. Cite line numbers + exact quote, or mark absent=true if it is nowhere in the document.",
            "Is any old content left that contradicts the change? Cite it.",
            "If you cannot judge (excerpt insufficient, image-only content), say cannot_judge and what you need.",
        ],
        "answer_schema": {
            "packet_id": "string", "verdict_candidate": "appears_sufficient | gaps_found | cannot_judge",
            "gaps": [{"description": "string", "expected_content": "string", "absent": "bool",
                      "evidence": [{"path": "string", "line_start": "int", "line_end": "int", "quote": "string"}]}],
            "needs": "string (what is missing to judge)", "reviewer": "agent:<name>",
        },
    }


def ingest_agent_review(responses: Path, packets: Dict[str, dict], text_loader) -> Dict:
    findings, rejected = [], []
    for d in read_jsonl(responses):
        pkt = packets.get(d.get("packet_id"))
        if not pkt:
            rejected.append({"packet_id": d.get("packet_id"), "reason": "unknown packet"})
            continue
        subject = f"{pkt['change_point']['id']}|{pkt['document']['file_number']}"
        verdict = d.get("verdict_candidate")
        if verdict == "cannot_judge":
            findings.append(Finding("sufficiency.agent_cannot_judge", "info", subject, d.get("needs") or "agent could not judge",
                                    [], {"reviewer": d.get("reviewer")}, "R&D document owner").to_dict())
            continue
        for g in d.get("gaps", []):
            evs = [Evidence(pkt["document"]["file_number"], e.get("path") or pkt["document"]["text_path"],
                            int(e["line_start"]), int(e["line_end"]), e["quote"], "revised")
                   for e in g.get("evidence", [])]
            ok = all(_verify(text_loader, ev) for ev in evs)
            if not g.get("absent") and (not evs or not ok):
                rejected.append({"packet_id": d["packet_id"], "reason": "gap cites no verifiable line", "gap": g})
                continue
            findings.append(Finding("sufficiency.agent_gap", "medium", subject, g.get("description", ""), evs,
                                    {"expected_content": g.get("expected_content"), "absent": bool(g.get("absent")),
                                     "reviewer": d.get("reviewer"), "layer": "cross_source_candidate"},
                                    "R&D document owner").to_dict())
    return {"findings": findings, "rejected": rejected}


def _verify(loader, ev: Evidence) -> bool:
    try:
        return quote_matches(loader(ev.path), ev)
    except FileNotFoundError:
        return False
