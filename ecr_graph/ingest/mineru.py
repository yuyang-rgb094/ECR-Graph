"""MinerU bridge for large / image-heavy / scanned documents.

Two modes:

* **local** — MinerU installed on the engineer's machine (no data leaves it).
  MinerU 4.x needs Python >= 3.11, so it is installed in its *own* virtual
  environment (see ``scripts/install_mineru.sh``); this kit only shells out.
* **cloud** — mineru.net precision API with a personal API key read from the
  ``MINERU_API_KEY`` environment variable. Uploading sends documents to a third
  party, so it is **off unless the project config sets
  ``mineru.cloud_upload_allowed: true``** (a decision for the document owner).

Published cloud limits at the time of writing (verify on mineru.net before
relying on them): 200 MB and 200 pages per file; 1000 pages per account per
day at highest priority, pages beyond that are processed at lower priority.
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Optional

API_BASE = "https://mineru.net/api/v4"
CLOUD_MAX_BYTES = 200 * 1024 * 1024
CLOUD_MAX_PAGES = 200
DAILY_PRIORITY_PAGES = 1000
QUOTA_FILE = Path(os.environ.get("ECR_GRAPH_HOME", Path.home() / ".ecr-graph")) / "mineru-quota.json"


class MinerUError(RuntimeError):
    pass


# --------------------------------------------------------------------------- page counting
def count_pages(path: Path) -> Optional[int]:
    """Best-effort page count without third-party packages. None = unknown."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader  # optional
                return len(PdfReader(str(path)).pages)
            except ImportError:
                data = path.read_bytes()
                counts = [int(m) for m in re.findall(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", data)]
                if counts:
                    return max(counts)
                n = len(re.findall(rb"/Type\s*/Page\b", data))
                return n or None
        if suffix in (".docx", ".pptx"):
            with zipfile.ZipFile(path) as z:
                app = z.read("docProps/app.xml").decode("utf-8", "ignore")
            m = re.search(r"<(?:Pages|Slides)>(\d+)</", app)
            return int(m.group(1)) if m else None
    except Exception:
        return None
    return None


def page_ranges(total: Optional[int], size: int = CLOUD_MAX_PAGES) -> List[Optional[str]]:
    if not total or total <= size:
        return [None]
    return [f"{s}-{min(s + size - 1, total)}" for s in range(1, total + 1, size)]


# --------------------------------------------------------------------------- quota ledger
def quota_used_today(ledger: Path = QUOTA_FILE) -> int:
    if not ledger.exists():
        return 0
    data = json.loads(ledger.read_text(encoding="utf-8"))
    return int(data.get(_dt.date.today().isoformat(), 0))


def quota_add(pages: int, ledger: Path = QUOTA_FILE) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else {}
    key = _dt.date.today().isoformat()
    data[key] = int(data.get(key, 0)) + int(pages)
    ledger.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- local
def local_command(src: Path, out_dir: Path, tier: str = "standard", template: Optional[str] = None) -> List[str]:
    if template:
        return [part.format(input=str(src), output=str(out_dir), output_md=str(out_dir / (src.stem + ".md")), tier=tier)
                for part in template.split()]
    if shutil.which("mineru-kit"):  # MinerU 4.x
        return ["mineru-kit", "parse", str(src), "-o", str(out_dir / (src.stem + ".md")), "--tier", tier]
    if shutil.which("mineru"):  # MinerU 2.x CLI
        return ["mineru", "-p", str(src), "-o", str(out_dir), "-b", "pipeline"]
    raise MinerUError(
        "MinerU is not installed. Run scripts/install_mineru.sh (local, recommended for confidential files) "
        "or configure the cloud API (needs MINERU_API_KEY and cloud_upload_allowed=true)."
    )


def run_local(src: Path, out_dir: Path, tier: str = "standard", template: Optional[str] = None,
              timeout: int = 6 * 3600) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = local_command(src, out_dir, tier, template)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise MinerUError(f"local MinerU failed: {proc.stderr.strip()[-800:]}")
    md = find_markdown(out_dir, src.stem)
    if md is None:
        raise MinerUError(f"MinerU finished but no markdown found under {out_dir}")
    return md


def find_markdown(out_dir: Path, stem: str) -> Optional[Path]:
    candidates = sorted(out_dir.rglob("*.md"), key=lambda p: (stem not in p.name, -p.stat().st_size))
    return candidates[0] if candidates else None


# --------------------------------------------------------------------------- cloud
def _request(method: str, url: str, token: str, payload: Optional[dict] = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("code") not in (0, "0", None):
        raise MinerUError(f"MinerU API error {data.get('code')}: {data.get('msg')}")
    return data.get("data") or {}


def run_cloud(src: Path, out_dir: Path, *, consent: bool, model_version: str = "vlm",
              allow_low_priority: bool = False, poll_seconds: int = 15, max_wait: int = 3 * 3600,
              api_base: str = API_BASE) -> List[Path]:
    if not consent:
        raise MinerUError(
            "Cloud parsing uploads the document to mineru.net. Set mineru.cloud_upload_allowed=true in the "
            "project config only after the document owner has agreed."
        )
    token = os.environ.get("MINERU_API_KEY", "").strip()
    if not token:
        raise MinerUError("MINERU_API_KEY is not set. Register at https://mineru.net and export the key in your shell.")
    size = src.stat().st_size
    if size > CLOUD_MAX_BYTES:
        raise MinerUError(
            f"{src.name} is {size / 1e6:.0f} MB; the cloud API accepts at most 200 MB per file. "
            "Use local MinerU, or split the file (ecr-graph mineru split) first."
        )
    pages = count_pages(src)
    used = quota_used_today()
    if pages and used + pages > DAILY_PRIORITY_PAGES and not allow_low_priority:
        raise MinerUError(
            f"Today {used} pages already submitted; {pages} more exceeds the {DAILY_PRIORITY_PAGES}-page "
            "high-priority daily allowance. Re-run tomorrow, use local MinerU, or pass --allow-low-priority."
        )
    ranges = page_ranges(pages)
    files = []
    for i, rng in enumerate(ranges, 1):
        entry = {"name": src.name, "data_id": f"{src.stem[:80]}-part{i}"}
        if rng:
            entry["page_ranges"] = rng
        files.append(entry)
    data = _request("POST", f"{api_base}/file-urls/batch", token,
                    {"files": files, "model_version": model_version, "enable_table": True})
    batch_id, urls = data["batch_id"], data["file_urls"]
    for url in urls:
        with open(src, "rb") as f:
            put = urllib.request.Request(url, data=f.read(), method="PUT")
            with urllib.request.urlopen(put, timeout=1800) as resp:
                if resp.status not in (200, 201):
                    raise MinerUError(f"upload failed with HTTP {resp.status}")
    if pages:
        quota_add(pages)
    deadline = time.time() + max_wait
    results: List[dict] = []
    while time.time() < deadline:
        res = _request("GET", f"{api_base}/extract-results/batch/{batch_id}", token)
        results = res.get("extract_result", [])
        states = {r.get("state") for r in results}
        if results and states <= {"done", "failed"}:
            break
        time.sleep(poll_seconds)
    else:
        raise MinerUError(f"MinerU batch {batch_id} not finished after {max_wait}s; query it again later")
    out_dir.mkdir(parents=True, exist_ok=True)
    mds: List[Path] = []
    for r in sorted(results, key=lambda r: r.get("data_id", "")):
        if r.get("state") != "done":
            raise MinerUError(f"MinerU part {r.get('data_id')} failed: {r.get('err_msg')}")
        part_dir = out_dir / r.get("data_id", "part")
        with urllib.request.urlopen(r["full_zip_url"], timeout=1800) as resp:
            zipfile.ZipFile(io.BytesIO(resp.read())).extractall(part_dir)
        md = find_markdown(part_dir, "full")
        if md:
            mds.append(md)
    return mds


def split_pdf(src: Path, out_dir: Path, pages_per_part: int = CLOUD_MAX_PAGES) -> List[Path]:
    """Split a large PDF into parts (needs the optional ``pypdf`` package)."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise MinerUError("pip install pypdf to split PDFs, or use local MinerU which has no size limit") from exc
    reader = PdfReader(str(src))
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, start in enumerate(range(0, len(reader.pages), pages_per_part), 1):
        w = PdfWriter()
        for p in reader.pages[start:start + pages_per_part]:
            w.add_page(p)
        target = out_dir / f"{src.stem}.part{i:02d}.pdf"
        with open(target, "wb") as f:
            w.write(f)
        parts.append(target)
    return parts


def markdown_to_lines(md_paths: List[Path]) -> List[str]:
    """Flatten MinerU markdown into evidence lines; HTML tables become [T#R#] rows."""
    lines: List[str] = []
    t = 0
    for md in md_paths:
        text = md.read_text(encoding="utf-8", errors="replace")
        for block in re.split(r"(<table>.*?</table>)", text, flags=re.S):
            if block.startswith("<table>"):
                t += 1
                for r, row in enumerate(re.findall(r"<tr>(.*?)</tr>", block, flags=re.S), 1):
                    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S)]
                    lines.append(f"[T{t}R{r}] " + " | ".join(cells))
                continue
            for raw in block.splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                if raw.startswith("|") and raw.endswith("|"):
                    if re.fullmatch(r"\|[\s:\-|]+\|", raw):
                        continue
                    lines.append(raw)
                elif raw.startswith("!["):
                    lines.append(f"[IMG {raw}]")
                else:
                    lines.append(raw)
    return lines
