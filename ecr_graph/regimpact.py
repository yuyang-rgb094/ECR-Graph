"""Registration-impact pre-assessment of a *proposed* change (变更方案合规性及注册影响预评估).

Meant to run when an engineer receives a requirement or drafts a change
proposal — before design work and before an ECR is filed — so that RA/QA are
pulled in early instead of after implementation.

Inputs
------
* a proposal (JSON, Markdown or plain text) or an existing change point id;
* the customer's registration items (registered parameters and limits), the
  software version rule, inspection checklist and past findings
  (``knowledge/``);
* the registration-impact rule pack (dimensions, outcomes, redesign hints).

Output
------
Per dimension: matched keywords, registered items touched, numeric comparison
against registered limits, version-rule result, expected evidence, related
checklist clauses / past findings, and *questions to ask*. The overall result
is one of four **candidate** outcomes for RA to decide. The kit never states
that a change is compliant or that no registration change is needed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .knowledge import Knowledge
from .sufficiency import extract_facts
from .util import normalize_label, read_json

NUM = r"(-?\d+(?:\.\d+)?)"


# ------------------------------------------------------------------ limits
def parse_limit(text: str) -> Optional[dict]:
    """'≤20 μm' | '>= 5' | '10~100 mm' | '50±5 Hz' | '20 μm' → structured limit."""
    t = text.replace("～", "~").replace("–", "~").replace("至", "~").replace(" ", "")
    m = re.match(rf"^{NUM}±{NUM}(.*)$", t)
    if m:
        c, d = float(m.group(1)), float(m.group(2))
        return {"op": "range", "lo": c - d, "hi": c + d, "unit": m.group(3)}
    m = re.match(rf"^{NUM}~{NUM}(.*)$", t)
    if m:
        return {"op": "range", "lo": float(m.group(1)), "hi": float(m.group(2)), "unit": m.group(3)}
    m = re.match(rf"^(≤|<=|不大于|≥|>=|不小于|<|>){NUM}(.*)$", t)
    if m:
        op = {"不大于": "<=", "≤": "<=", "不小于": ">=", "≥": ">="}.get(m.group(1), m.group(1))
        return {"op": op, "value": float(m.group(2)), "unit": m.group(3)}
    m = re.match(rf"^{NUM}(.*)$", t)
    if m:
        return {"op": "==", "value": float(m.group(1)), "unit": m.group(2)}
    return None


def first_number(text: str) -> Optional[float]:
    m = re.search(NUM, str(text))
    return float(m.group(1)) if m else None


def within(limit: dict, value: float) -> Optional[bool]:
    op = limit["op"]
    if op == "range":
        return limit["lo"] <= value <= limit["hi"]
    v = limit["value"]
    return {"<=": value <= v, "<": value < v, ">=": value >= v, ">": value > v, "==": abs(value - v) < 1e-9}.get(op)


# ------------------------------------------------------------------ proposals
def load_proposal(path: Path) -> dict:
    if path.suffix.lower() == ".json":
        return read_json(path)
    text = path.read_text(encoding="utf-8")
    return {"id": path.stem, "title": text.strip().splitlines()[0][:80] if text.strip() else path.stem, "description": text}


def proposal_from_change_point(cp: dict) -> dict:
    return {"id": cp["id"], "title": cp.get("title", ""),
            "description": " ".join(str(cp.get(k) or "") for k in ("title", "problem", "cause", "solution")),
            "domains": cp.get("domains", [])}


def _version_bump(rule: dict, old: str, new: str) -> Tuple[List[str], Optional[str]]:
    pat = re.compile(rule["pattern"])
    mo, mn = pat.search(old or ""), pat.search(new or "")
    if not mo or not mn:
        return [], "version strings do not match the registered version rule pattern"
    names = rule.get("components") or [f"c{i}" for i in range(1, len(mo.groups()) + 1)]
    changed = [names[i] for i in range(min(len(names), len(mo.groups()))) if mo.group(i + 1) != mn.group(i + 1)]
    return changed, None


# ------------------------------------------------------------------ assessment
def assess(proposal: dict, pack: dict, knowledge: Knowledge, suff_pack: dict = None) -> dict:
    text = " ".join(str(proposal.get(k) or "") for k in ("title", "description"))
    params = list(proposal.get("parameters", []))
    proposal = dict(proposal)
    if suff_pack:
        for f in extract_facts(text, suff_pack):
            if f["type"] != "pair":
                continue
            if re.fullmatch(r"[Vv]?\d+(\.\d+)+", f["old"]) and re.fullmatch(r"[Vv]?\d+(\.\d+)+", f["new"]):
                proposal.setdefault("software_version", {"old": f["old"], "new": f["new"], "from_text": f["span"]})
            elif not proposal.get("parameters") and first_number(f["new"]) is not None:
                # free-text proposals only; explicit parameters take precedence
                params.append({"parameter": "", "old": f["old"], "new": f["new"], "from_text": f["span"]})
    order = pack.get("outcome_order", [])
    dims_out = []
    gaps: List[str] = []
    overall = "likely_within_registration"
    hints = []

    def bump(outcome: str):
        nonlocal overall
        if order.index(outcome) > order.index(overall):
            overall = outcome

    any_match = False
    for dim in pack["dimensions"]:
        kws = [k for k in dim["keywords"] if k.lower() in text.lower()]
        docs = [d for d in proposal.get("affected_documents", []) if set(d.get("classes", [])) & set(dim.get("doc_classes", []))]
        if not kws and not docs and not (dim.get("software_version_rule") and proposal.get("software_version")):
            continue
        any_match = True
        res = {"id": dim["id"], "name": dim["name"], "matched_keywords": kws, "outcome": dim.get("default_outcome", "needs_ra_review"),
               "registered_items": [], "comparisons": [], "notes": [], "questions": list(dim.get("questions", [])),
               "evidence_expected": dim.get("evidence_expected", [])}
        if dim.get("compare_with_registered"):
            items = [it for it in knowledge.registration_items
                     if any(normalize_label(w) in normalize_label(text + " " + " ".join(p.get("parameter", "") for p in params))
                            for w in [it.get("parameter", "")] + it.get("keywords", []) if w)]
            res["registered_items"] = [{k: it.get(k) for k in ("id", "item", "parameter", "limit", "unit", "source")} for it in items]
            if not knowledge.registration_items:
                res["outcome"] = "insufficient_information"
                gaps.append("registration_items")
            for it in items:
                lim = parse_limit(str(it.get("limit", "")))
                for p in params:
                    if p.get("parameter") and normalize_label(p["parameter"]) not in normalize_label(
                            " ".join([it.get("parameter", "")] + it.get("keywords", []))):
                        continue
                    val = first_number(p.get("new", ""))
                    if lim is None or val is None:
                        res["notes"].append(f"could not compare '{p.get('new')}' with registered limit '{it.get('limit')}'")
                        continue
                    ok = within(lim, val)
                    res["comparisons"].append({"registered_item": it.get("id"), "limit": it.get("limit"),
                                               "proposed": p.get("new"), "within_registered_limit": ok})
                    if ok is False:
                        res["outcome"] = "likely_registration_change"
                        hints.append(pack["redesign_hints"]["outside_registered_limit"])
                    elif ok is True and res["outcome"] != "likely_registration_change":
                        res["outcome"] = "likely_within_registration"
                        res["notes"].append("within the registered limit — confirm test evidence and that no other "
                                            "registered item is affected")
        if dim.get("software_version_rule"):
            rule = knowledge.software_version_rule
            sv = proposal.get("software_version") or {}
            if not rule:
                res["outcome"] = "insufficient_information" if res["outcome"] != "likely_registration_change" else res["outcome"]
                gaps.append("software_version_rule")
            elif sv.get("old") and sv.get("new"):
                changed, err = _version_bump(rule, sv["old"], sv["new"])
                if err:
                    res["notes"].append(err)
                relevant = [c for c in changed if c in rule.get("registration_relevant", [])]
                res["comparisons"].append({"version_old": sv["old"], "version_new": sv["new"], "changed_components": changed,
                                           "registration_relevant_changed": relevant})
                if relevant:
                    res["outcome"] = "likely_registration_change"
                    hints.append(pack["redesign_hints"]["software_relevant_component_bump"])
                else:
                    res["notes"].append("version rule shows no registration-relevant component change; this only holds "
                                        "if the version truthfully reflects the change's nature")
            else:
                res["questions"].append("What are the current and planned software version numbers?")
        if dim["id"] == "RD-STRUCTURE":
            hints.append(pack["redesign_hints"]["structure_or_configuration"])
        res["related_experience"] = knowledge.search(text + " " + " ".join(kws), limit=5)
        bump(res["outcome"])
        dims_out.append(res)
    if not any_match:
        overall = "insufficient_information"
        gaps.append("proposal_details")
    if not knowledge.inspection_checklist and not knowledge.inspection_findings:
        gaps.append("inspection_experience")
    return {
        "proposal": {k: proposal.get(k) for k in ("id", "title")},
        "candidate_outcome": overall,
        "outcome_meaning": pack["outcomes"][overall],
        "dimensions": dims_out,
        "redesign_hints": sorted(set(hints)) or [pack["redesign_hints"]["default"]] if dims_out else [],
        "knowledge_gaps": sorted(set(gaps)),
        "disclaimer": "Candidate pre-assessment generated from the customer's own rule pack and knowledge. "
                      "It is not a compliance or registration decision; RA/QA decide and record the rationale.",
    }


def to_markdown(a: dict) -> str:
    out = [f"# Registration-impact pre-assessment — {a['proposal'].get('title') or a['proposal'].get('id')}", "",
           f"**Candidate outcome:** `{a['candidate_outcome']}` — {a['outcome_meaning']}", "",
           f"> {a['disclaimer']}", ""]
    for d in a["dimensions"]:
        out += [f"## {d['name']} (`{d['id']}`) → `{d['outcome']}`", ""]
        if d["matched_keywords"]:
            out.append(f"- Matched: {', '.join(d['matched_keywords'])}")
        for it in d["registered_items"]:
            out.append(f"- Registered item {it['id']}: {it.get('item')} — limit {it.get('limit')} (source: {it.get('source')})")
        for c in d["comparisons"]:
            out.append(f"- Comparison: `{json.dumps(c, ensure_ascii=False)}`")
        for n in d["notes"]:
            out.append(f"- Note: {n}")
        if d["evidence_expected"]:
            out.append(f"- Evidence RA will expect: {', '.join(d['evidence_expected'])}")
        for h in d.get("related_experience", []):
            out.append(f"- Related {h['kind']} {h['id']}: {h['text']} (source: {h.get('source')})")
        for q in d["questions"]:
            out.append(f"- [ ] Ask: {q}")
        out.append("")
    if a["redesign_hints"]:
        out += ["## Options to discuss with RA", ""] + [f"- {h}" for h in a["redesign_hints"]] + [""]
    if a["knowledge_gaps"]:
        out += ["## Missing knowledge (run `ecr-graph grill`)", ""] + [f"- {g}" for g in a["knowledge_gaps"]] + [""]
    return "\n".join(out)
