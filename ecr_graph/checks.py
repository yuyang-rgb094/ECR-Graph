"""Deterministic package checks.

Each check returns counts plus ``Finding`` objects. A zero count means "not
found by this rule in this batch", never "does not exist" or "compliant".
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Tuple

from .extract.candidates import quote_matches
from .model import Finding
from .package import Package

VERSION_NUM = re.compile(r"\d+")


def version_key(v: str) -> Tuple:
    nums = tuple(int(x) for x in VERSION_NUM.findall(v or ""))
    return nums or (-1,)


def check_package(pkg: Package, version_pattern: str = r"^[Vv]?\d+(?:\.\d+)*[A-Za-z]?$") -> Dict:
    findings: List[Finding] = []
    counts: Dict[str, int] = {}

    # 1. duplicate SPO
    seen = defaultdict(int)
    for t in pkg.triples:
        seen[t.spo] += 1
    counts["duplicate_spo"] = sum(n - 1 for n in seen.values() if n > 1)

    # 2. dangling edges (subject/object must be entities, except domain tags)
    dangling = []
    for t in pkg.triples:
        for end in (t.subject, t.object):
            if end not in pkg.entities and not end.startswith("DOM-"):
                dangling.append((t.id, end))
    counts["dangling_edges"] = len(dangling)
    for tid, end in dangling[:200]:
        findings.append(Finding("graph.dangling_edge", "medium", tid, f"edge endpoint {end} is not an entity"))

    # 3. evidence: every triple from the source layer has evidence; quotes verify
    no_ev = [t for t in pkg.triples if t.assertion_layer == "source_assertion" and not t.evidence]
    counts["source_assertions_without_evidence"] = len(no_ev)
    bad_quotes, missing_text, checked = 0, 0, 0
    cache: Dict[str, List[str]] = {}
    for t in pkg.triples:
        for ev in t.evidence:
            checked += 1
            if ev.path not in cache:
                try:
                    cache[ev.path] = pkg.text_lines(ev.path)
                except FileNotFoundError:
                    cache[ev.path] = None
            lines = cache[ev.path]
            if lines is None:
                missing_text += 1
            elif not quote_matches(lines, ev):
                bad_quotes += 1
                findings.append(Finding("evidence.quote_mismatch", "high", t.id,
                                        f"quote not found at {ev.path}:{ev.line_start}-{ev.line_end}", [ev]))
    counts.update(evidence_checked=checked, evidence_quote_mismatch=bad_quotes, evidence_text_missing=missing_text)

    # 4. coverage: every change point is referenced by at least one file change
    cp_with_files = {cp for t in pkg.transitions for cp in t.get("change_point_ids", [])}
    uncovered = [c for c in pkg.change_points if c["id"] not in cp_with_files]
    counts["change_points"] = len(pkg.change_points)
    counts["change_points_without_file_change"] = len(uncovered)
    for c in uncovered:
        findings.append(Finding("coverage.change_point_without_file", "medium", c["id"],
                                "no attachment row is traced to this change point; either the file list is incomplete "
                                "or rows only reference the ECR as a whole", [], {"title": c.get("title")},
                                "document control"))
    unresolved = [t for t in pkg.transitions if t.get("unresolved_refs")]
    counts["rows_with_unresolved_change_point_refs"] = len(unresolved)
    for t in unresolved:
        findings.append(Finding("coverage.unresolved_reference", "medium", t["row_id"],
                                f"row cites change point(s) {t['unresolved_refs']} that the ECR body does not contain",
                                [], {"file_number": t["file_number"]}, "document control"))
    ecr_level = [t for t in pkg.transitions if not t.get("change_point_ids")]
    counts["rows_assigned_at_ecr_level_only"] = len(ecr_level)

    # 5. version format and chain
    vre = re.compile(version_pattern)
    by_doc = defaultdict(list)
    for t in pkg.transitions:
        for v in (t.get("old_version"), t.get("new_version")):
            if v and v not in ("/", "-", "—") and not vre.match(v):
                findings.append(Finding("version.format", "low", t["row_id"], f"version '{v}' does not match the pattern",
                                        [], {"file_number": t["file_number"]}))
        by_doc[t["file_number"]].append(t)
    gaps = backrefs = repeats = 0
    for number, rows in by_doc.items():
        rows = sorted(rows, key=lambda r: (r["ecr_id"], r["row_id"]))
        last_new = None
        seen_pairs = set()
        for r in rows:
            old, new = r.get("old_version") or "", r.get("new_version") or ""
            pair = (old, new)
            if pair in seen_pairs and old and new:
                repeats += 1
                findings.append(Finding("version.repeated_transition", "low", r["row_id"],
                                        f"{number} {old}→{new} appears in more than one row/ECR", [], {}, "document control"))
                continue
            seen_pairs.add(pair)
            if old and new and version_key(new) <= version_key(old) and r["operation"] != "obsolete":
                backrefs += 1
                findings.append(Finding("version.backwards", "medium", r["row_id"],
                                        f"{number}: new version {new} is not after old version {old}", [], {}, "document control"))
            if last_new and old and old not in ("/", "-") and version_key(old) != version_key(last_new):
                gaps += 1
                findings.append(Finding("version.gap", "info", r["row_id"],
                                        f"{number}: previous row in this batch ends at {last_new}, this row starts from {old} "
                                        "(other changes may be outside the batch)", [], {}, "document control"))
            if new and new not in ("/", "-"):
                last_new = new
    counts.update(version_gaps=gaps, version_backwards=backrefs, version_repeated=repeats)
    return {"counts": counts, "findings": [f.to_dict() for f in findings]}
