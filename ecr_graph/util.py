"""Small stdlib helpers shared by every stage."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable, Iterator


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: object, length: int = 14) -> str:
    """Deterministic id: same inputs always give the same id."""
    raw = "␟".join(str(p) for p in parts)
    return f"{prefix}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:length].upper()}"


def normalize_label(text: str) -> str:
    """Normalisation used for dedupe keys only — never for display.

    NFKC folds full-width brackets/digits, whitespace is dropped and case folded.
    """
    if text is None:
        return ""
    t = unicodedata.normalize("NFKC", str(text))
    t = re.sub(r"\s+", "", t)
    return t.casefold()


def read_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, value, pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2 if pretty else None, sort_keys=False)
        f.write("\n")


def read_jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:  # pragma: no cover - surfaced to user
                raise ValueError(f"{path}:{n}: invalid JSON ({exc})") from exc


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")
            n += 1
    return n


def ensure_new_dir(path: Path) -> Path:
    """Outputs never overwrite an earlier run."""
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"output directory already exists and is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path
