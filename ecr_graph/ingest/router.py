"""Ingest: originals → line-numbered derived text + manifest.

Routing per file:

* ``.docx``                → stdlib OOXML reader (tables, check boxes)
* ``.doc``                 → converted work copy → OOXML reader
* ``.txt`` / ``.md``       → read as-is
* ``.pdf`` / images / any file over the size or image threshold → MinerU

The manifest records, for every original: SHA-256, size, parser, derived
text path, line count, image count and warnings. Sources are opened
read-only; nothing is written next to them.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from ..config import Config
from ..util import sha256_file, write_json
from . import mineru
from .convert import doc_to_docx
from .docx_text import read_docx
from .html_text import read_html

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def source_id_for(path: Path, patterns: List[str]) -> str:
    for pat in patterns:
        m = re.search(pat, path.name)
        if m:
            return m.group(1) if m.groups() else m.group(0)
    return re.sub(r"\s+", "_", path.stem)


def _is_large(path: Path, cfg: Config, images: int = 0) -> bool:
    ld = cfg["large_document"]
    if path.suffix.lower() == ".pdf" and ld.get("pdf_always", True):
        return True
    if path.suffix.lower() in IMAGE_EXT:
        return True
    return path.stat().st_size > ld["size_mb"] * 1024 * 1024 or images > ld["images"]


def _mineru_lines(src: Path, cfg: Config, out_dir: Path) -> (List[str], str):
    mc = cfg["mineru"]
    mode = mc.get("mode", "auto")
    errors = []
    if mode in ("auto", "local"):
        try:
            md = mineru.run_local(src, out_dir, tier=mc.get("tier", "standard"), template=mc.get("local_command"))
            return mineru.markdown_to_lines([md]), "mineru-local"
        except mineru.MinerUError as exc:
            errors.append(str(exc))
            if mode == "local":
                raise
    if mode in ("auto", "cloud"):
        mds = mineru.run_cloud(
            src, out_dir, consent=bool(mc.get("cloud_upload_allowed")),
            model_version=mc.get("model_version", "vlm"),
            allow_low_priority=bool(mc.get("allow_low_priority")),
        )
        return mineru.markdown_to_lines(mds), "mineru-cloud"
    raise mineru.MinerUError("; ".join(errors) or "MinerU disabled (mineru.mode=off)")


def ingest(cfg: Config, id_patterns: List[str], only: Optional[List[Path]] = None) -> Dict:
    work = cfg.work
    text_dir = work / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    exts = set(cfg["extensions"])
    files: List[Path] = []
    roots = [(r, "source") for r in cfg.sources] + [(r, "revised") for r in cfg.revised]
    for root, role in roots:
        if root.is_file():
            files.append((root, role))
        elif root.exists():
            files.extend((p, role) for p in sorted(root.rglob("*")) if p.is_file() and p.suffix.lower() in exts
                         and not p.name.startswith(("~$", ".")))
    if only:
        wanted = {p.resolve() for p in only}
        files = [(p, r) for p, r in files if p.resolve() in wanted]
    seen_ids: Dict[str, int] = {}
    for src, role in files:
        sid = source_id_for(src, id_patterns)
        if sid in seen_ids:
            seen_ids[sid] += 1
            sid = f"{sid}#{seen_ids[sid]}"
        else:
            seen_ids[sid] = 1
        entry = {
            "source_id": sid,
            "role": role,
            "original": str(src),
            "original_name": src.name,
            "sha256": sha256_file(src),
            "bytes": src.stat().st_size,
            "pages": mineru.count_pages(src),
            "warnings": [],
        }
        try:
            lines, parser, images = _parse(src, cfg, work / "convert" / sid, work / "mineru" / sid, entry)
        except Exception as exc:  # keep going; the manifest records the gap
            entry.update(parser="failed", error=str(exc), derived_text=None, lines=0)
            entries.append(entry)
            continue
        safe = re.sub(r"[^\w.#-]+", "_", sid)
        out = text_dir / f"{safe}.txt"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        entry.update(parser=parser, derived_text=str(out.relative_to(work)), lines=len(lines), images=images)
        if images and not parser.startswith("mineru"):
            entry["warnings"].append(
                f"{images} embedded image(s) not read; content inside images (signatures, drawings, screenshots) "
                "needs MinerU or manual review"
            )
        entries.append(entry)
    manifest = {"project": cfg["project_name"], "documents": entries,
                "summary": {"documents": len(entries), "failed": sum(1 for e in entries if e.get("parser") == "failed")}}
    write_json(work / "manifest.json", manifest)
    return manifest


def _glyphs(lines: List[str], cfg: Config) -> List[str]:
    """Apply the profile's glyph rules (e.g. Wingdings check boxes rendered as '£' by some converters)."""
    rules = [(re.compile(r["pattern"]), r["replace"]) for r in cfg.data.get("_glyph_rules") or []]
    for pat, rep in rules:
        lines = [pat.sub(rep, l) for l in lines]
    return lines


def _parse(src: Path, cfg: Config, convert_dir: Path, mineru_dir: Path, entry: dict):
    suffix = src.suffix.lower()
    if suffix in (".txt", ".md"):
        return src.read_text(encoding="utf-8", errors="replace").splitlines(), "plain", 0
    if suffix in (".html", ".htm"):
        d = read_html(src)
        return _glyphs(d.lines, cfg), "html", d.images
    if suffix in (".docx", ".doc"):
        target = src
        if suffix == ".doc":
            target, tool = doc_to_docx(src, convert_dir)
            entry["converted_with"] = tool
        derived = read_html(target) if target.suffix == ".html" else read_docx(target)
        derived.lines = _glyphs(derived.lines, cfg)
        if _is_large(src, cfg, derived.images) and cfg["mineru"].get("mode") != "off":
            try:
                lines, parser = _mineru_lines(target, cfg, mineru_dir)
                entry["warnings"].append("large/image-heavy document routed to MinerU")
                return lines, parser, derived.images
            except mineru.MinerUError as exc:
                entry["warnings"].append(f"MinerU unavailable, fell back to text-only reader: {exc}")
        return derived.lines, "ooxml" + ("+converted" if suffix == ".doc" else ""), derived.images
    lines, parser = _mineru_lines(src, cfg, mineru_dir)
    return lines, parser, 0
