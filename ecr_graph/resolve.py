"""Deduplication and disambiguation.

Rules (deliberately conservative):

1. Exact duplicate SPO in the same layer → one triple, evidence merged.
2. ``same_as`` only from ``aliases.json`` entries that name ``adjudicated_by``.
3. Labels that differ only in bracketed qualifiers ("X (CE)" vs "X (US)") are
   linked by ``possible_identity`` with the reason recorded — **never merged**:
   market variants are usually distinct configurations.
4. Prefix/suffix similarity ("X" vs "X-E") is *not* evidence of identity and
   produces nothing; such pairs are listed for review only if a human asks.
5. One file number with several different titles is flagged as a candidate
   "same number, different object" conflict.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Tuple

from .knowledge import Knowledge
from .model import HUMAN_ADJUDICATION, POSSIBLE_IDENTITY, RULE_DERIVED, SAME_AS, Entity, Triple
from .package import Package
from .util import normalize_label

QUALIFIER = re.compile(r"[（(\[【][^）)\]】]*[）)\]】]")


def dedupe_triples(triples: List[Triple]) -> Tuple[List[Triple], int]:
    merged: Dict[tuple, Triple] = {}
    dupes = 0
    for t in triples:
        key = t.spo
        if key in merged:
            dupes += 1
            cur = merged[key]
            ids = {e.evidence_id for e in cur.evidence}
            cur.evidence.extend(e for e in t.evidence if e.evidence_id not in ids)
            cur.confidence = max(cur.confidence, t.confidence)
            for k, v in t.qualifiers.items():
                if k in cur.qualifiers and cur.qualifiers[k] != v:
                    vals = cur.qualifiers.setdefault(f"{k}__all", [cur.qualifiers[k]])
                    if v not in vals:
                        vals.append(v)
                else:
                    cur.qualifiers.setdefault(k, v)
        else:
            merged[key] = t
    return list(merged.values()), dupes


def base_label(label: str) -> str:
    return normalize_label(QUALIFIER.sub("", label))


def resolve(pkg: Package, knowledge: Knowledge) -> dict:
    report = {"duplicate_triples_merged": 0, "same_as_from_adjudication": 0, "possible_identity": 0,
              "same_number_different_title": []}
    pkg.triples, report["duplicate_triples_merged"] = dedupe_triples(pkg.triples)

    labels = {e.id: e.label for e in pkg.by_type("ProductLabel")}
    by_norm = defaultdict(list)
    for eid, lab in labels.items():
        by_norm[normalize_label(lab)].append(eid)
    distinct_pairs = {frozenset(map(normalize_label, d.get("labels", []))) for d in knowledge.distinct}

    # 2. human adjudicated identity
    for a in knowledge.aliases:
        if not a.get("adjudicated_by"):
            continue
        members = [eid for lab in a.get("labels", []) for eid in by_norm.get(normalize_label(lab), [])]
        canon = "CANON-" + re.sub(r"\s+", "_", a["canonical"])
        pkg.entities.setdefault(canon, Entity(canon, "CanonicalProduct", a["canonical"],
                                              {"adjudicated_by": a["adjudicated_by"], "basis": a.get("basis", "")}))
        for eid in members:
            pkg.triples.append(Triple(eid, SAME_AS, canon, HUMAN_ADJUDICATION, 1.0,
                                      {"basis": a.get("basis", ""), "date": a.get("date", "")},
                                      [], produced_by="aliases.json", adjudicated_by=a["adjudicated_by"]))
            report["same_as_from_adjudication"] += 1

    # 3. qualifier-only differences → possible_identity
    groups = defaultdict(list)
    for eid, lab in labels.items():
        groups[base_label(lab)].append(eid)
    for base, ids in groups.items():
        if len(ids) < 2 or not base:
            continue
        ids = sorted(ids)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = labels[ids[i]], labels[ids[j]]
                if frozenset((normalize_label(a), normalize_label(b))) in distinct_pairs:
                    continue
                pkg.triples.append(Triple(ids[i], POSSIBLE_IDENTITY, ids[j], RULE_DERIVED, 0.4,
                                          {"reason": "labels differ only in bracketed qualifiers; often distinct market "
                                                     "configurations — needs product/RA adjudication",
                                           "labels": [a, b]}))
                report["possible_identity"] += 1

    # 5. same number, different titles
    for doc in pkg.by_type("Document"):
        titles = sorted({t for t in doc.attributes.get("titles", []) if t})
        norm = {normalize_label(t) for t in titles}
        if len(norm) > 1:
            report["same_number_different_title"].append({"document": doc.id, "titles": titles})
    pkg.triples, extra = dedupe_triples(pkg.triples)
    report["duplicate_triples_merged"] += extra
    return report
