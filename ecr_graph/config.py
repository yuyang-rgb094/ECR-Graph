"""Project configuration (plain JSON so it works on Python 3.9 without extras).

All paths are resolved relative to the config file; nothing is hard-coded to a
particular company, product line or directory layout.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

PACKAGE_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: Dict[str, Any] = {
    "project_name": "my-ecr-project",
    # read-only source folders (ECR forms, controlled documents, new versions of changed files)
    "sources": ["sources"],
    # optional: folders that hold post-change versions of affected documents (for sufficiency review)
    "revised_documents": [],
    "work_dir": "work",
    "profile": str(PACKAGE_ROOT / "profiles" / "generic-ecr-zh.json"),
    # customer experience: inspection checklist items, past inspection findings, SOP excerpts
    "knowledge_dir": "knowledge",
    "rulepacks": {
        "registration_impact": str(PACKAGE_ROOT / "rulepacks" / "registration-impact.template.json"),
        "cross_review": str(PACKAGE_ROOT / "rulepacks" / "cross-review.template.json"),
        "sufficiency": str(PACKAGE_ROOT / "rulepacks" / "sufficiency.template.json"),
    },
    "large_document": {"size_mb": 50, "images": 30, "pdf_always": True},
    "mineru": {
        "mode": "auto",                 # auto | local | cloud | off
        "cloud_upload_allowed": False,  # owner decision; uploading leaves your network
        "tier": "standard",
        "model_version": "vlm",
        "local_command": None,          # e.g. "mineru-kit parse {input} -o {output_md} --tier {tier}"
        "allow_low_priority": False,
    },
    "extensions": [".doc", ".docx", ".html", ".htm", ".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg"],
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    data: Dict[str, Any]
    root: Path

    @classmethod
    def load(cls, path: Path) -> "Config":
        path = Path(path).resolve()
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return cls(_merge(DEFAULTS, raw), path.parent)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def path(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.root / p).resolve()

    @property
    def work(self) -> Path:
        return self.path(self.data["work_dir"])

    @property
    def sources(self) -> List[Path]:
        return [self.path(s) for s in self.data["sources"]]

    @property
    def revised(self) -> List[Path]:
        return [self.path(s) for s in self.data.get("revised_documents", [])]

    def rulepack(self, name: str) -> Path:
        return self.path(self.data["rulepacks"][name])


def write_default(path: Path, project_name: str) -> None:
    cfg = {
        "project_name": project_name,
        "sources": ["sources"],
        "revised_documents": ["revised"],
        "work_dir": "work",
        "knowledge_dir": "knowledge",
        "mineru": {"mode": "auto", "cloud_upload_allowed": False},
    }
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
