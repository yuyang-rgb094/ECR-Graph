"""Legacy .doc → .docx conversion into a *work copy*.

Originals are opened read-only and never renamed, moved or overwritten; the
converted copy lives under the run's work directory and its provenance (the
original's SHA-256 and the converter used) is recorded in the manifest.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple


def available_converters() -> list:
    found = []
    for name in ("soffice", "libreoffice"):
        if shutil.which(name):
            found.append(name)
            break
    if sys.platform == "darwin" and shutil.which("textutil"):
        found.append("textutil")
    return found


def doc_to_docx(src: Path, work_dir: Path, prefer: Optional[str] = None) -> Tuple[Path, str]:
    """Return (converted path, tool). The path is .docx (LibreOffice) or .html (textutil)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    converters = available_converters()
    if prefer:
        converters = [c for c in converters if c == prefer] or converters
    if not converters:
        raise RuntimeError(
            "No .doc converter found. Install LibreOffice (soffice) or, on macOS, use the built-in textutil. "
            "Alternatively save the file as .docx manually (keep the original untouched)."
        )
    # copy first so converters never write next to the original
    staged = work_dir / src.name
    shutil.copy2(src, staged)
    tool = converters[0]
    if tool in ("soffice", "libreoffice"):
        target = work_dir / (src.stem + ".docx")
        cmd = [tool, "--headless", "--convert-to", "docx", "--outdir", str(work_dir), str(staged)]
    else:
        # textutil's .docx output drops tables; its HTML output keeps them
        target = work_dir / (src.stem + ".html")
        cmd = ["textutil", "-convert", "html", "-output", str(target), str(staged)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    staged.unlink(missing_ok=True) if staged != target else None
    if proc.returncode != 0 or not target.exists():
        raise RuntimeError(f"{tool} failed on {src.name}: {proc.stderr.strip()[:400]}")
    return target, tool
