"""A *package* is the on-disk unit every stage reads and writes.

    <package>/
      meta.json              name, role (base | candidate), producer, created
      entities.jsonl
      triples.jsonl
      transitions.jsonl      one row per attachment-table file change
      change_points.jsonl
      text/                  derived evidence text (copied or referenced)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .model import Entity, Triple, evidence_from_dict
from .util import read_json, read_jsonl, write_json, write_jsonl


@dataclass
class Package:
    root: Path
    meta: dict = field(default_factory=dict)
    entities: Dict[str, Entity] = field(default_factory=dict)
    triples: List[Triple] = field(default_factory=list)
    transitions: List[dict] = field(default_factory=list)
    change_points: List[dict] = field(default_factory=list)

    # --------------------------------------------------------------- io
    @classmethod
    def load(cls, root: Path) -> "Package":
        root = Path(root)
        pkg = cls(root, read_json(root / "meta.json") if (root / "meta.json").exists() else {"name": root.name})
        if (root / "entities.jsonl").exists():
            for d in read_jsonl(root / "entities.jsonl"):
                ev = [evidence_from_dict(e) for e in d.pop("evidence", [])]
                pkg.entities[d["id"]] = Entity(evidence=ev, **{k: v for k, v in d.items() if k in Entity.__dataclass_fields__})
        if (root / "triples.jsonl").exists():
            pkg.triples = [Triple.from_dict(d) for d in read_jsonl(root / "triples.jsonl")]
        for name in ("transitions", "change_points"):
            p = root / f"{name}.jsonl"
            if p.exists():
                setattr(pkg, name, list(read_jsonl(p)))
        return pkg

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        write_json(self.root / "meta.json", self.meta)
        write_jsonl(self.root / "entities.jsonl", (e.to_dict() for e in sorted(self.entities.values(), key=lambda e: e.id)))
        write_jsonl(self.root / "triples.jsonl", (t.to_dict() for t in sorted(self.triples, key=lambda t: t.id)))
        write_jsonl(self.root / "transitions.jsonl", self.transitions)
        write_jsonl(self.root / "change_points.jsonl", self.change_points)

    # --------------------------------------------------------------- helpers
    def by_type(self, etype: str) -> List[Entity]:
        return [e for e in self.entities.values() if e.type == etype]

    def text_lines(self, rel_path: str, base: Path = None) -> List[str]:
        """Resolve an evidence path against the package, then its parent work dir."""
        for b in [base, self.root, self.root.parent]:
            if b is None:
                continue
            p = Path(b) / rel_path
            if p.exists():
                return p.read_text(encoding="utf-8").splitlines()
        raise FileNotFoundError(rel_path)
