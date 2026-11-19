"""Document association table and cross-review.

Builds an explicit table of *why two documents are related* — co-changed in
the same change point / ECR, cross-referenced in text, or linked by a
companion rule — and turns rule gaps into review findings enriched with the
customer's inspection checklist and past findings.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Dict, List

from .knowledge import Knowledge
from .model import Evidence, Finding
from .package import Package
from .util import read_json, write_jsonl


def load_rulepack(path: Path, knowledge: Knowledge) -> dict:
    pack = read_json(path)
    if knowledge.doc_classes:
        pack["doc_classes"] = {**pack.get("doc_classes", {}), **knowledge.doc_classes}
    return pack


def classify(title: str, number: str, classes: Dict[str, str]) -> List[str]:
    text = f"{title} {number}"
    return [c for c, pat in classes.items() if re.search(pat, text, flags=re.I)]


def build(pkg: Package, knowledge: Knowledge, pack: dict, revised_texts: Dict[str, List[str]] = None) -> Dict:
    classes = pack.get("doc_classes", {})
    doc_class: Dict[str, List[str]] = {}
    for t in pkg.transitions:
        doc_class.setdefault(t["file_number"], classify(t.get("file_title", ""), t["file_number"], classes))
    rows: List[dict] = []
    findings: List[Finding] = []

    by_cp = defaultdict(list)
    by_ecr = defaultdict(list)
    for t in pkg.transitions:
        for cp in t.get("change_point_ids") or []:
            by_cp[cp].append(t)
        by_ecr[t["ecr_id"]].append(t)

    seen = set()
    for cp, ts in by_cp.items():
        nums = sorted({t["file_number"] for t in ts})
        if len(nums) > 60:  # very wide change points: record membership instead of all pairs
            rows.extend({"doc_a": n, "relation": "changed_in_change_point", "doc_b": "", "basis": cp} for n in nums)
            continue
        for a, b in combinations(nums, 2):
            key = (a, b, "co_changed_in_change_point", cp)
            if key not in seen:
                seen.add(key)
                rows.append({"doc_a": a, "relation": "co_changed_in_change_point", "doc_b": b, "basis": cp})
    for ecr, ts in by_ecr.items():
        nums = sorted({t["file_number"] for t in ts})
        if len(nums) <= 60:  # avoid quadratic blow-up on huge ECRs; per-CP links carry the detail
            for a, b in combinations(nums, 2):
                rows.append({"doc_a": a, "relation": "co_changed_in_ecr", "doc_b": b, "basis": ecr})

    # textual cross references inside revised documents
    known = sorted(doc_class, key=len, reverse=True)
    for number, lines in (revised_texts or {}).items():
        for i, line in enumerate(lines, 1):
            for other in known:
                if other != number and other in line:
                    rows.append({"doc_a": number, "relation": "references", "doc_b": other, "basis": f"line {i}"})

    # companion rules per change point (fall back to ECR when rows are ECR-level)
    cps = {c["id"]: c for c in pkg.change_points}
    scopes = list(by_cp.items()) + [(f"{e} (ECR level)", [t for t in ts if not t.get("change_point_ids")])
                                     for e, ts in by_ecr.items()]
    for scope, ts in scopes:
        if not ts:
            continue
        present = defaultdict(list)
        for t in ts:
            for c in doc_class.get(t["file_number"], []):
                present[c].append(t["file_number"])
        ev = [Evidence(**ts[0]["evidence"])]
        for rule in pack.get("rules", []):
            trig = [c for c in rule["when_changed"] if c in present]
            if not trig:
                continue
            missing = [c for c in rule["must_review"] if c not in present]
            for m in missing:
                for a in sorted({n for c in trig for n in present[c]}):
                    rows.append({"doc_a": a, "relation": f"companion_expected:{m}", "doc_b": "", "basis": rule["id"]})
            if missing:
                text = " ".join(cps.get(scope, {}).get(k, "") or "" for k in ("title", "solution"))
                hits = knowledge.search(text + " " + " ".join(missing))
                findings.append(Finding(
                    "crossref.companion_not_in_file_list", rule.get("severity", "medium"), scope,
                    f"{rule['message']} Not in this change's file list: {', '.join(missing)}. "
                    "Confirm each was evaluated (record 'no change needed' with reason) or add it.",
                    ev, {"rule": rule["id"], "triggered_by": trig, "missing_classes": missing,
                         "basis": rule.get("basis"), "related_experience": hits}, "QA / document control"))
        cp = cps.get(scope)
        if cp:
            for exp in pack.get("domain_expectations", []):
                if exp["domain"] in cp.get("domains", []) and not any(c in present for c in exp["expects_changed"]):
                    findings.append(Finding("crossref.domain_without_documents", exp.get("severity", "medium"), scope,
                                            exp["message"], [Evidence(**cp["evidence"])],
                                            {"rule": exp["id"], "domain": exp["domain"]}, "R&D / document control"))
    # change points that have no file rows at all
    for cid, cp in cps.items():
        if cid not in by_cp and cp.get("domains"):
            findings.append(Finding("crossref.change_point_without_documents", "medium", cid,
                                    "change point declares engineering directions but no file row is traced to it",
                                    [Evidence(**cp["evidence"])], {"domains": cp["domains"]}, "document control"))
    return {"rows": rows, "doc_classes": doc_class, "findings": [f.to_dict() for f in findings]}


def write_table(rows: List[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["doc_a", "relation", "doc_b", "basis"])
        w.writeheader()
        w.writerows(rows)
    write_jsonl(out.with_suffix(".jsonl"), rows)
