"""Five independent axis indexes over one package.

Each axis file is self-contained and follows one record contract:
``metadata, indexes, records, evidence_registry, query_examples, quality``.
Records link across axes with ``{"predicate", "target", "target_axis"}``.

1. change-events            ECR → change point (what changed, why, how)
2. product-configurations   product labels and which files/changes apply to them
3. engineering-objects      engineering directions and agent-proposed objects
4. controlled-files         documents, versions, transitions, chain findings
5. impact-relationships     per change point: files, products, verification,
                            risk, cross-review and sufficiency findings
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from .package import Package
from .util import write_json, write_jsonl

AXES = ["01-change-events", "02-product-configurations", "03-engineering-objects",
        "04-controlled-files", "05-impact-relationships"]


class _Axis:
    def __init__(self, name: str, purpose: str):
        self.name, self.purpose = name, purpose
        self.records: List[dict] = []
        self.indexes: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
        self.evidence: Dict[str, dict] = {}

    def add(self, rid: str, rtype: str, attrs: dict, relations: List[dict], evidence: List[dict], index: Dict[str, object]):
        for e in evidence:
            self.evidence[e["evidence_id"]] = e
        self.records.append({"record_id": rid, "record_type": rtype, "attributes": attrs, "relations": relations,
                             "evidence_ids": [e["evidence_id"] for e in evidence],
                             "quality": {"status": "source_backed" if evidence else "derived", "warnings": []}})
        for key, vals in index.items():
            for v in (vals if isinstance(vals, list) else [vals]):
                if v not in (None, ""):
                    self.indexes[key][str(v)].append(rid)

    def dump(self, out: Path, queries: List[dict]) -> dict:
        data = {
            "metadata": {"axis": self.name, "purpose": self.purpose, "record_count": len(self.records),
                         "evidence_count": len(self.evidence),
                         "independence": "loadable alone; cross-axis links use target_axis + record_id"},
            "indexes": {k: dict(v) for k, v in self.indexes.items()},
            "records": self.records,
            "evidence_registry": self.evidence,
            "query_examples": queries,
            "quality": {"note": "no record ≠ object absent or compliant; counts cover this batch only"},
        }
        write_json(out / f"{self.name}.json", data)
        write_jsonl(out / f"{self.name}.jsonl", self.records)
        return data["metadata"]


def build_axes(pkg: Package, out: Path, findings: List[dict] = ()) -> Dict:
    ev_of = lambda ent: [e.to_dict() for e in ent.evidence]  # noqa: E731
    ax = {n: _Axis(n, p) for n, p in zip(AXES, [
        "What changed, why and how — ECRs and change points in order",
        "Which product labels each file change and change point applies to",
        "Engineering directions and objects touched by changes",
        "Controlled documents, versions and transitions",
        "Impact bundles linking each change point to files, products, verification, risk and findings"])}
    cp_files = defaultdict(list)
    cp_products = defaultdict(set)
    for t in pkg.transitions:
        for cp in t.get("change_point_ids") or []:
            cp_files[cp].append(t)
            cp_products[cp].update(t.get("products", []))

    # 1. change events
    for e in pkg.by_type("ECR"):
        sections = e.attributes.get("sections", {})
        ax[AXES[0]].add(e.id, "ECR", e.attributes, [], ev_of(e),
                        {"by_ecr": e.id, "by_nature": sorted({v for s in sections.values() for v in s.get("nature", [])})})
    for c in pkg.change_points:
        rel = [{"predicate": "changes_document", "target": f"DOC-{t['file_number']}", "target_axis": AXES[3]} for t in cp_files[c["id"]]]
        rel.append({"predicate": "impact_bundle", "target": f"IMP-{c['id']}", "target_axis": AXES[4]})
        ax[AXES[0]].add(c["id"], "ChangePoint", {k: v for k, v in c.items() if k not in ("evidence", "id")}, rel,
                        [c["evidence"]], {"by_ecr": c["ecr_id"], "by_domain": c.get("domains", [])})
    # 2. product configurations
    docs_of, ids_of = defaultdict(set), defaultdict(list)
    for t in pkg.triples:
        if t.predicate == "applicable_to":
            docs_of[t.object].add(t.subject)
        elif t.predicate in ("possible_identity", "same_as"):
            ids_of[t.subject].append(t)
            ids_of[t.object].append(t)
    for e in pkg.by_type("ProductLabel"):
        docs = sorted(docs_of.get(e.id, ()))
        ids = ids_of.get(e.id, [])
        rel = [{"predicate": "has_applicable_document", "target": d, "target_axis": AXES[3]} for d in docs]
        rel += [{"predicate": t.predicate, "target": t.object if t.subject == e.id else t.subject,
                 "note": t.assertion_layer} for t in ids]
        ax[AXES[1]].add(e.id, "ProductLabel", {**e.attributes, "document_count": len(docs)}, rel, ev_of(e)[:5],
                        {"by_label": e.label})
    # 3. engineering objects
    for c in pkg.change_points:
        for d in c.get("domains", []):
            ax[AXES[2]].add(f"DOMCHG-{c['id']}-{d}", "DomainInvolvement", {"domain": d, "change_point": c["id"]},
                            [{"predicate": "involved_in", "target": c["id"], "target_axis": AXES[0]}], [c["evidence"]],
                            {"by_domain": d, "by_change_point": c["id"]})
    for e in pkg.entities.values():
        if e.type not in ("ECR", "ChangePoint", "Document", "DocumentVersion", "ProductLabel", "CanonicalProduct"):
            ax[AXES[2]].add(e.id, e.type, e.attributes, [], ev_of(e), {"by_type": e.type})
    # 4. controlled files
    for e in pkg.by_type("Document"):
        ax[AXES[3]].add(e.id, "Document", e.attributes, [], ev_of(e)[:5], {"by_file_number": e.attributes.get("file_number")})
    for t in pkg.transitions:
        ax[AXES[3]].add(f"FT-{t['row_id']}", "FileTransition", {k: v for k, v in t.items() if k != "evidence"},
                        [{"predicate": "assessed_in_change_point", "target": c, "target_axis": AXES[0]} for c in t.get("change_point_ids", [])],
                        [t["evidence"]], {"by_file_number": t["file_number"], "by_ecr": t["ecr_id"], "by_operation": t["operation"],
                                          "by_change_point": t.get("change_point_ids", [])})
    # 5. impact bundles
    f_by_subject = defaultdict(list)
    for f in findings:
        f_by_subject[f["subject"].split("|")[0]].append(f)
    for c in pkg.change_points:
        fs = f_by_subject.get(c["id"], [])
        attrs = {"change_point": c["id"], "title": c.get("title"),
                 "files": sorted({t["file_number"] for t in cp_files[c["id"]]}),
                 "products": sorted(cp_products[c["id"]]),
                 "verification_text": c.get("verification"), "risk_text": c.get("risk"),
                 "open_findings": [{"check": f["check"], "severity": f["severity"], "message": f["message"]} for f in fs]}
        ax[AXES[4]].add(f"IMP-{c['id']}", "ImpactBundle", attrs,
                        [{"predicate": "bundles", "target": c["id"], "target_axis": AXES[0]}], [c["evidence"]],
                        {"by_change_point": c["id"], "by_finding_check": sorted({f["check"] for f in fs}),
                         "has_verification_text": str(bool(c.get("verification")))})
    out.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, a in ax.items():
        q = []
        if a.indexes:
            k = next(iter(a.indexes))
            v = next(iter(a.indexes[k]), None)
            if v is not None:
                q.append({"name": f"example_{k}", "intent": f"records with {k} = {v}", "filter": {k: v},
                          "result_count": len(a.indexes[k][v]), "result_record_ids": a.indexes[k][v][:20]})
        meta[name] = a.dump(out, q)
    write_json(out / "manifest.json", meta)
    return meta
