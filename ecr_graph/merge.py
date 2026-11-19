"""Merge several candidate packages without majority voting.

* One package is the **base** (the most complete, best-evidenced fact layer).
* Other packages contribute triples as ``cross_source_candidate`` unless the
  identical SPO already exists in the base — then they only add corroboration.
* Disagreements are recorded in a conflict ledger, never resolved silently:

  - ``functional``: same subject + functional predicate, different objects;
  - ``identity``: a package proposes identity between entities the base
    keeps apart (or vice versa);
  - ``entity_type`` / ``label``: same id, different type or label.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List

from .model import CROSS_SOURCE_CANDIDATE, POSSIBLE_IDENTITY, SAME_AS, SOURCE_ASSERTION
from .package import Package
from .resolve import dedupe_triples
from .util import normalize_label, stable_id

DEFAULT_FUNCTIONAL = ("version_of", "has_new_version", "has_status", "has_owner_role")


def merge_packages(base: Package, others: Iterable[Package], out_root: Path,
                   functional: Iterable[str] = DEFAULT_FUNCTIONAL) -> Dict:
    functional = set(functional)
    merged = Package(out_root, {"name": out_root.name, "role": "merged", "base": base.meta.get("name"),
                                "inputs": [base.meta.get("name")]})
    merged.entities = {k: v for k, v in base.entities.items()}
    merged.transitions = list(base.transitions)
    merged.change_points = list(base.change_points)
    base_spo = {(t.subject, t.predicate, t.object): t for t in base.triples}
    triples = list(base.triples)
    conflicts: List[dict] = []
    stats = defaultdict(lambda: {"corroborated": 0, "candidates": 0, "new_entities": 0})

    base_func = defaultdict(set)
    for t in base.triples:
        if t.predicate in functional:
            base_func[(t.subject, t.predicate)].add(t.object)

    for pkg in others:
        name = pkg.meta.get("name", pkg.root.name)
        merged.meta["inputs"].append(name)
        for eid, ent in pkg.entities.items():
            if eid not in merged.entities:
                ent.attributes = {**ent.attributes, "proposed_by": name}
                merged.entities[eid] = ent
                stats[name]["new_entities"] += 1
                continue
            cur = merged.entities[eid]
            if cur.type != ent.type:
                conflicts.append(_conflict("entity_type", eid, {base.meta.get("name"): cur.type, name: ent.type}))
            if normalize_label(cur.label) != normalize_label(ent.label):
                conflicts.append(_conflict("label", eid, {base.meta.get("name"): cur.label, name: ent.label}))
        for t in pkg.triples:
            key = (t.subject, t.predicate, t.object)
            if key in base_spo:
                b = base_spo[key]
                corr = b.qualifiers.setdefault("corroborated_by", [])
                if name not in corr:
                    corr.append(name)
                stats[name]["corroborated"] += 1
                continue
            if t.predicate in (SAME_AS, POSSIBLE_IDENTITY):
                conflicts.append(_conflict("identity", f"{t.subject}|{t.object}",
                                           {name: t.predicate, base.meta.get("name"): "kept distinct"},
                                           evidence=[e.to_dict() for e in t.evidence]))
                t.predicate = POSSIBLE_IDENTITY
            if t.predicate in functional and base_func.get((t.subject, t.predicate)) and \
                    t.object not in base_func[(t.subject, t.predicate)]:
                conflicts.append(_conflict("functional", f"{t.subject}|{t.predicate}",
                                           {base.meta.get("name"): sorted(base_func[(t.subject, t.predicate)]), name: t.object}))
            t.qualifiers = {**t.qualifiers, "from_package": name,
                            "original_layer": t.assertion_layer}
            t.assertion_layer = CROSS_SOURCE_CANDIDATE
            t.adjudicated_by = None
            t.id = stable_id("TR", t.subject, t.predicate, t.object, t.assertion_layer)
            triples.append(t)
            stats[name]["candidates"] += 1
    merged.triples, dupes = dedupe_triples(triples)
    merged.meta["stats"] = {k: dict(v) for k, v in stats.items()}
    merged.meta["duplicates_merged"] = dupes
    merged.meta["conflicts"] = len(conflicts)
    merged.save()
    from .util import write_jsonl
    write_jsonl(out_root / "conflicts.jsonl", conflicts)
    return merged.meta


def _conflict(kind: str, key: str, positions: dict, evidence=None) -> dict:
    return {"id": stable_id("CF", kind, key), "kind": kind, "key": key, "positions": positions,
            "evidence": evidence or [], "status": "open — needs a named reviewer"}
