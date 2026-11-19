"""Evidence contract and graph records.

Every statement in an ECR-Graph package is a *triple with evidence*. The kit
never upgrades a candidate to a conclusion on its own: identity (`same_as`),
compliance and registration outcomes can only enter the graph through the
`human_adjudication` layer, written by a named person.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from .util import sha256_text, stable_id

# --- assertion layers (ordered from strongest source binding to weakest) ----
SOURCE_ASSERTION = "source_assertion"          # quoted verbatim from a source document
RULE_DERIVED = "rule_derived"                  # deterministic rule over source assertions
EXTERNAL_CORROBORATION = "external_corroboration"  # public record (e.g. registry entry)
CROSS_SOURCE_CANDIDATE = "cross_source_candidate"  # proposed by another package / an agent
HUMAN_ADJUDICATION = "human_adjudication"      # decided by a named reviewer

LAYERS = (
    SOURCE_ASSERTION,
    RULE_DERIVED,
    EXTERNAL_CORROBORATION,
    CROSS_SOURCE_CANDIDATE,
    HUMAN_ADJUDICATION,
)

# predicates that assert identity; same_as is reserved for human adjudication
SAME_AS = "same_as"
POSSIBLE_IDENTITY = "possible_identity"

SEVERITIES = ("info", "low", "medium", "high", "critical")


@dataclass
class Evidence:
    source_id: str              # document id (e.g. ECR number) — never a file name guess
    path: str                   # path of the derived text, relative to the package root
    line_start: int
    line_end: int
    quote: str
    section_path: str = ""
    source_sha256: str = ""     # sha256 of the original binary, when known
    evidence_id: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id:
            self.evidence_id = stable_id(
                "EVD", self.source_id, self.path, self.line_start, self.line_end, sha256_text(self.quote)
            )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Entity:
    id: str
    type: str                   # ECR, ChangePoint, Document, DocumentVersion, Product, Object, ...
    label: str
    attributes: Dict[str, object] = field(default_factory=dict)
    evidence: List[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


@dataclass
class Triple:
    subject: str
    predicate: str
    object: str
    assertion_layer: str = SOURCE_ASSERTION
    confidence: float = 1.0
    qualifiers: Dict[str, object] = field(default_factory=dict)
    evidence: List[Evidence] = field(default_factory=list)
    produced_by: str = "ecr-graph"
    adjudicated_by: Optional[str] = None
    id: str = ""

    def __post_init__(self) -> None:
        if self.assertion_layer not in LAYERS:
            raise ValueError(f"unknown assertion_layer: {self.assertion_layer}")
        if self.predicate == SAME_AS and self.assertion_layer != HUMAN_ADJUDICATION:
            raise ValueError("same_as may only be asserted in the human_adjudication layer; use possible_identity")
        if self.assertion_layer == HUMAN_ADJUDICATION and not self.adjudicated_by:
            raise ValueError("human_adjudication triples must name adjudicated_by")
        if not self.id:
            self.id = stable_id("TR", self.subject, self.predicate, self.object, self.assertion_layer)

    @property
    def spo(self) -> tuple:
        return (self.subject, self.predicate, self.object, self.assertion_layer)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Triple":
        ev = [Evidence(**e) for e in d.get("evidence", [])]
        keys = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "evidence"}
        return cls(evidence=ev, **keys)


@dataclass
class Finding:
    """A review result. Always a candidate for a human, never a verdict."""

    check: str                  # e.g. sufficiency.stale_value, regimpact.trigger
    severity: str
    subject: str                # record the finding is about
    message: str
    evidence: List[Evidence] = field(default_factory=list)
    details: Dict[str, object] = field(default_factory=dict)
    needs_reviewer_role: str = ""  # e.g. "RA", "document control", "R&D"
    status: str = "open_candidate"
    id: str = ""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity}")
        if not self.id:
            self.id = stable_id("FND", self.check, self.subject, self.message)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


def evidence_from_dict(d: dict) -> Evidence:
    return Evidence(**{k: v for k, v in d.items() if k in Evidence.__dataclass_fields__})
