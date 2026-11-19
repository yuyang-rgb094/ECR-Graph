"""Contract for agent-produced candidates.

A customer's agent (any LLM) may propose entities/triples the deterministic
extractor cannot: engineering objects, parameters, semantic links. The kit
accepts them only under this contract:

* JSONL, one object per line: ``{"kind": "triple"|"entity", ...}``.
* Every candidate must carry at least one evidence locator whose quote is
  found verbatim in the cited lines of the derived text. Unverifiable
  candidates are rejected, not silently kept.
* ``same_as`` from an agent is downgraded to ``possible_identity``; layers
  ``source_assertion`` and ``human_adjudication`` are never accepted from an
  agent — everything enters as ``cross_source_candidate``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from ..model import CROSS_SOURCE_CANDIDATE, POSSIBLE_IDENTITY, SAME_AS, Entity, Evidence, Triple, evidence_from_dict
from ..util import normalize_label, read_jsonl


def quote_matches(lines: List[str], ev: Evidence) -> bool:
    if ev.line_start < 1 or ev.line_end < ev.line_start or ev.line_end > len(lines):
        return False
    window = normalize_label(" ".join(lines[ev.line_start - 1: ev.line_end]))
    q = normalize_label(ev.quote)
    return bool(q) and q in window


def import_candidates(path: Path, producer: str, text_loader) -> Tuple[List[Entity], List[Triple], List[dict]]:
    entities, triples, rejected = [], [], []
    for n, d in enumerate(read_jsonl(path), 1):
        evs = [evidence_from_dict(e) for e in d.get("evidence", [])]
        bad = []
        for ev in evs:
            try:
                ok = quote_matches(text_loader(ev.path), ev)
            except FileNotFoundError:
                ok = False
            if not ok:
                bad.append(ev.evidence_id)
        if not evs or bad:
            rejected.append({"line": n, "reason": "missing or unverifiable evidence", "evidence": bad, "record": d})
            continue
        if d.get("kind") == "entity":
            entities.append(Entity(d["id"], d["type"], d.get("label", d["id"]),
                                   {**d.get("attributes", {}), "proposed_by": producer}, evs))
        else:
            pred = POSSIBLE_IDENTITY if d["predicate"] == SAME_AS else d["predicate"]
            q = dict(d.get("qualifiers", {}))
            if pred != d["predicate"]:
                q["downgraded_from"] = SAME_AS
            triples.append(Triple(d["subject"], pred, d["object"], CROSS_SOURCE_CANDIDATE,
                                  min(float(d.get("confidence", 0.5)), 0.9), q, evs, produced_by=producer))
    return entities, triples, rejected
