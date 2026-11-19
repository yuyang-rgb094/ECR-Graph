"""Leak scan before sharing anything (code, examples, reports).

Two layers:

* a **private denylist** you keep outside the repository (company names,
  product names, document-number prefixes, people) — one term or ``re:<regex>``
  per line;
* generic patterns: e-mail addresses, phone numbers, ID-card-like numbers,
  home-directory absolute paths, API-key-like strings.

Exit code is non-zero when anything is found, so it can gate CI.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

GENERIC = {
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "cn_mobile": r"(?<!\d)1[3-9]\d{9}(?!\d)",
    "cn_id_card": r"(?<!\d)\d{17}[\dXx](?!\d)",
    "home_path": r"/(?:Users|home)/[A-Za-z0-9._-]+/",
    "api_key_like": r"\b(?:sk|ak|key|token)[-_][A-Za-z0-9]{20,}\b",
}
SKIP_DIRS = {".git", "__pycache__", ".venv", "work", "node_modules", ".pytest_cache"}
TEXT_EXT = {".py", ".md", ".json", ".jsonl", ".txt", ".csv", ".toml", ".cfg", ".sh", ".yaml", ".yml", ".html", ".graphml"}


def load_denylist(path: Path) -> List[re.Pattern]:
    pats = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pats.append(re.compile(line[3:] if line.startswith("re:") else re.escape(line), re.I))
    return pats


def scan(paths: Iterable[Path], deny: List[re.Pattern], allow_generic: Iterable[str] = ()) -> List[dict]:
    generic = {k: re.compile(v) for k, v in GENERIC.items() if k not in set(allow_generic)}
    hits = []
    for root in paths:
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for f in files:
            if set(f.parts) & SKIP_DIRS or f.suffix.lower() not in TEXT_EXT:
                continue
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for i, line in enumerate(lines, 1):
                for p in deny:
                    if p.search(line):
                        hits.append({"file": str(f), "line": i, "kind": "denylist", "pattern": p.pattern})
                for k, p in generic.items():
                    m = p.search(line)
                    if m and "example" not in m.group(0).lower():
                        hits.append({"file": str(f), "line": i, "kind": k, "match": m.group(0)[:40]})
    return hits
