"""Grill: turn detected gaps into questions and document requests for the customer.

The agent running ECR-Graph must not guess regulatory experience. Whenever
the project state shows a gap, ``grill`` produces prioritised questions with
*why it matters*, *who can answer* and *what file to provide in which format*.
The agent asks them (a few at a time), records each answer with its source in
``knowledge/``, and re-runs the affected stage.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .knowledge import Knowledge

BASE_QUESTIONS = {
    "inspection_checklist": {
        "priority": 1, "ask": "Which inspection checklist / audit criteria does your team prepare against "
                              "(regulator checklist, notified-body checklist, internal audit list)? Please share it.",
        "why": "Cross-review rules and findings cite these clauses; without them, findings fall back to generic examples.",
        "who": "QA / RA", "provide": "knowledge/inspection_checklist.jsonl",
        "template": {"id": "CL-001", "clause": "…", "doc_classes": ["risk_management"], "keywords": ["设计变更"], "source": "document + section"}},
    "inspection_experience": {
        "priority": 1, "ask": "What did past inspections or audits find in design-change records? "
                              "Share deficiency lists, CAPA records or your own lessons learned.",
        "why": "Past findings are the strongest signal for what reviewers will look for in this batch.",
        "who": "QA", "provide": "knowledge/inspection_findings.jsonl or knowledge/experience/*.md",
        "template": {"id": "IF-001", "finding": "…", "clause_ref": "CL-001", "doc_classes": ["ifu"], "keywords": ["说明书"],
                     "lesson": "…", "source": "report id / date"}},
    "registration_items": {
        "priority": 1, "ask": "Please provide the registered content for the affected products: registration certificate "
                              "scope, structure/composition, and the performance items with their limits.",
        "why": "Registration-impact pre-assessment compares proposed values with registered limits; without them it can only say 'needs RA review'.",
        "who": "RA", "provide": "knowledge/registration_items.jsonl",
        "template": {"id": "RI-001", "item": "…", "parameter": "…", "limit": "≤20 μm", "unit": "μm",
                     "doc_class": "technical_requirements", "keywords": ["…"], "source": "certificate / requirement clause"}},
    "software_version_rule": {
        "priority": 2, "ask": "What is your registered software version naming rule, and which component marks a "
                              "registration-relevant (significant) update?",
        "why": "Needed to tell a registration-relevant software change from a maintenance release.",
        "who": "RA / software configuration management", "provide": "knowledge/software_version_rule.json",
        "template": {"pattern": "V(\\d+)\\.(\\d+)\\.(\\d+)", "components": ["major", "minor", "patch"],
                     "registration_relevant": ["major"], "source": "procedure id + section"}},
    "doc_numbering": {
        "priority": 2, "ask": "How are your document numbers and titles structured? Which number ranges or title words mark "
                              "technical requirements, IFU, labels, risk files, software records, drawings, BOMs?",
        "why": "Document classes drive companion rules and sufficiency expectations.",
        "who": "Document control", "provide": "knowledge/doc_classes.json",
        "template": {"technical_requirements": "regex", "ifu": "regex"}},
    "revised_documents": {
        "priority": 2, "ask": "For the change points below, please provide the revised (post-change) versions of the affected documents.",
        "why": "Content sufficiency can only be checked against the revised text; the ECR form alone lists files, not their content.",
        "who": "Document control / R&D", "provide": "files into the 'revised_documents' folder (original file names)"},
    "proposal_details": {
        "priority": 1, "ask": "Describe the proposed change: what changes, why, which parameters (old → new values), "
                              "which software versions, which documents and products are affected.",
        "why": "The pre-assessment cannot match any registration-relevant dimension from the current description.",
        "who": "Change owner (R&D)", "provide": "proposal.json (see examples/)"},
}


def build(knowledge: Knowledge, *, checks: Optional[dict] = None, resolve_report: Optional[dict] = None,
          sufficiency: Optional[dict] = None, regimpact: Optional[dict] = None, crossref: Optional[dict] = None) -> Dict:
    qs: List[dict] = []

    def add(key: str, extra: dict = None):
        q = dict(BASE_QUESTIONS[key])
        q["topic"] = key
        if extra:
            q.update(extra)
        qs.append(q)

    st = knowledge.status()
    if not st["inspection_checklist"]:
        add("inspection_checklist")
    if not st["inspection_findings"] and not st["experience_documents"]:
        add("inspection_experience")
    if not st["registration_items"]:
        add("registration_items")
    if not st["software_version_rule"]:
        add("software_version_rule")
    if not knowledge.doc_classes:
        add("doc_numbering")
    for p in knowledge.problems:
        qs.append({"topic": "knowledge_quality", "priority": 2, "ask": p, "why": "Uncited or unattributed knowledge is not used.",
                   "who": "whoever supplied the item", "provide": "fix the knowledge file"})
    if sufficiency:
        missing = sorted({n for f in sufficiency.get("findings", []) if f["check"] == "sufficiency.not_checkable"
                          for n in f["details"].get("file_numbers", [])})
        if missing:
            add("revised_documents", {"items": missing[:50], "count": len(missing)})
    if resolve_report and resolve_report.get("possible_identity"):
        qs.append({"topic": "identity", "priority": 2,
                   "ask": f"{resolve_report['possible_identity']} pair(s) of product labels differ only in a qualifier. "
                          "For each pair: same configuration, or distinct?",
                   "why": "Merging distinct market configurations corrupts traceability; the kit never merges on its own.",
                   "who": "Product management / RA", "provide": "knowledge/aliases.json or knowledge/distinct.json"})
    if resolve_report and resolve_report.get("same_number_different_title"):
        qs.append({"topic": "same_number_different_title", "priority": 2,
                   "ask": "These document numbers appear with different titles. Same document, renamed, or a numbering error?",
                   "items": resolve_report["same_number_different_title"][:30], "who": "Document control",
                   "why": "Version chains are built per document number.", "provide": "answer per item"})
    if checks:
        c = checks.get("counts", {})
        if c.get("rows_with_unresolved_change_point_refs"):
            qs.append({"topic": "unresolved_refs", "priority": 2, "who": "Document control",
                       "ask": f"{c['rows_with_unresolved_change_point_refs']} file rows cite change points that do not exist "
                              "in the ECR body. Typo, or a missing change point?",
                       "why": "Unresolved references break change → file traceability.", "provide": "answer per row"})
        if c.get("version_backwards"):
            qs.append({"topic": "version_backwards", "priority": 2, "who": "Document control",
                       "ask": f"{c['version_backwards']} rows move a document to an earlier version. Intentional rollback?",
                       "why": "Possible transcription error in the attachment table.", "provide": "answer per row"})
    if crossref:
        n = sum(1 for f in crossref.get("findings", []) if f["check"] == "crossref.companion_not_in_file_list")
        if n:
            qs.append({"topic": "companion_documents", "priority": 1, "who": "QA / document owners",
                       "ask": f"{n} change(s) touch a document whose usual companions are not in the file list. "
                              "Were they evaluated? If 'no change needed', where is that recorded?",
                       "why": "Inspectors typically ask for the evaluation record, not only the changed files.",
                       "provide": "evaluation record per finding"})
    if regimpact:
        for g in regimpact.get("knowledge_gaps", []):
            if g in BASE_QUESTIONS and all(q["topic"] != g for q in qs):
                add(g)
    qs.sort(key=lambda q: q["priority"])
    return {"questions": qs, "knowledge_status": st,
            "protocol": "Ask at most 3 questions at a time, highest priority first. Record each answer with its source "
                        "(document id/section or person + date) in knowledge/, then re-run the affected stage."}


def to_markdown(g: dict) -> str:
    out = ["# Questions for the customer (grill sheet)", "", g["protocol"], "",
           "Knowledge loaded: " + ", ".join(f"{k}={v}" for k, v in g["knowledge_status"].items()), ""]
    for i, q in enumerate(g["questions"], 1):
        out += [f"## {i}. [{q['topic']}] (P{q['priority']}) — ask {q.get('who', '')}", "", q["ask"], "",
                f"- Why: {q.get('why', '')}", f"- Provide: {q.get('provide', '')}"]
        if q.get("items"):
            out.append(f"- Items: {q['items'][:20]}")
        if q.get("template"):
            import json
            out.append(f"- Template: `{json.dumps(q['template'], ensure_ascii=False)}`")
        out.append("")
    return "\n".join(out)
