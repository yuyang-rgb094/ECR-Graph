"""Customer experience packs — the knowledge the toolkit cannot ship.

Everything regulatory-specific comes from the customer, with a source for each
item, under ``<knowledge_dir>/``:

=============================  ===============================================
``inspection_checklist.jsonl``  inspection checklist clauses (考纲/检查要点)
                                ``{id, clause, doc_classes[], keywords[], source}``
``inspection_findings.jsonl``   past inspection / audit findings (飞检、体系核查)
                                ``{id, finding, clause_ref, doc_classes[], keywords[], lesson, source}``
``registration_items.jsonl``    registered content: parameters and limits from the
                                registration certificate / technical requirements
                                ``{id, item, parameter, limit, unit, doc_class, keywords[], source}``
``software_version_rule.json``  how the registered software version is formed
                                ``{pattern, components[], registration_relevant[], source}``
``aliases.json``                identity decisions made by named people
                                ``[{"canonical", "labels"[], "adjudicated_by", "date", "basis"}]``
``distinct.json``               labels people decided are *not* the same
``doc_classes.json``            optional override of document-class regexes
``experience/*.md``             free-text lessons; indexed line by line for citation
=============================  ===============================================
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .util import read_jsonl

FILES = {
    "inspection_checklist": "inspection_checklist.jsonl",
    "inspection_findings": "inspection_findings.jsonl",
    "registration_items": "registration_items.jsonl",
}


@dataclass
class Knowledge:
    root: Path
    inspection_checklist: List[dict] = field(default_factory=list)
    inspection_findings: List[dict] = field(default_factory=list)
    registration_items: List[dict] = field(default_factory=list)
    software_version_rule: dict = field(default_factory=dict)
    aliases: List[dict] = field(default_factory=list)
    distinct: List[dict] = field(default_factory=list)
    doc_classes: Dict[str, str] = field(default_factory=dict)
    experience: Dict[str, List[str]] = field(default_factory=dict)
    problems: List[str] = field(default_factory=list)

    @classmethod
    def load(cls, root: Path) -> "Knowledge":
        k = cls(Path(root))
        if not k.root.exists():
            return k
        for attr, name in FILES.items():
            p = k.root / name
            if p.exists():
                rows = list(read_jsonl(p))
                for r in rows:
                    if not r.get("source"):
                        k.problems.append(f"{name}: item {r.get('id')} has no 'source' — cite where it came from")
                setattr(k, attr, rows)
        for attr in ("software_version_rule", "aliases", "distinct", "doc_classes"):
            p = k.root / f"{attr}.json"
            if p.exists():
                setattr(k, attr, json.loads(p.read_text(encoding="utf-8")))
        for a in k.aliases:
            if not a.get("adjudicated_by"):
                k.problems.append(f"aliases.json: '{a.get('canonical')}' lacks adjudicated_by — it will be ignored")
        exp = k.root / "experience"
        if exp.exists():
            for md in sorted(exp.glob("*.md")) + sorted(exp.glob("*.txt")):
                k.experience[md.name] = md.read_text(encoding="utf-8").splitlines()
        return k

    def status(self) -> Dict[str, int]:
        return {
            "inspection_checklist": len(self.inspection_checklist),
            "inspection_findings": len(self.inspection_findings),
            "registration_items": len(self.registration_items),
            "software_version_rule": int(bool(self.software_version_rule)),
            "aliases": len([a for a in self.aliases if a.get("adjudicated_by")]),
            "experience_documents": len(self.experience),
        }

    def search(self, text: str, limit: int = 8) -> List[dict]:
        """Keyword hits across checklist, findings and experience notes (deterministic)."""
        hits = []
        for kind, rows, key in (("checklist", self.inspection_checklist, "clause"),
                                ("finding", self.inspection_findings, "finding")):
            for r in rows:
                kws = [w for w in r.get("keywords", []) if w and w in text]
                if kws:
                    hits.append({"kind": kind, "id": r.get("id"), "text": r.get(key), "matched": kws,
                                 "source": r.get("source"), "lesson": r.get("lesson")})
        for name, lines in self.experience.items():
            for i, line in enumerate(lines, 1):
                words = [w for w in _keywords(line) if w in text]
                if len(words) >= 2:
                    hits.append({"kind": "experience", "id": f"{name}:L{i}", "text": line.strip(), "matched": words,
                                 "source": name})
        hits.sort(key=lambda h: -len(h["matched"]))
        return hits[:limit]


def _keywords(line: str) -> List[str]:
    import re
    return [w for w in re.findall(r"[一-鿿]{2,6}|[A-Za-z][A-Za-z0-9-]{2,}", line)][:20]
