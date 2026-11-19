"""Exports: GraphML, Neo4j CSV, Obsidian vault."""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from .package import Package


def graphml(pkg: Package, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<graphml xmlns="http://graphml.graphdrawing.org/xmlns">\n')
        for k, target in (("label", "node"), ("type", "node"), ("predicate", "edge"), ("layer", "edge"), ("confidence", "edge")):
            f.write(f'  <key id="{k}" for="{target}" attr.name="{k}" attr.type="string"/>\n')
        f.write('  <graph id="ecr-graph" edgedefault="directed">\n')
        for e in pkg.entities.values():
            f.write(f'    <node id="{escape(e.id, {chr(34): "&quot;"})}"><data key="label">{escape(e.label)}</data>'
                    f'<data key="type">{escape(e.type)}</data></node>\n')
        for t in pkg.triples:
            f.write(f'    <edge id="{t.id}" source="{escape(t.subject, {chr(34): "&quot;"})}" target="{escape(t.object, {chr(34): "&quot;"})}">'
                    f'<data key="predicate">{escape(t.predicate)}</data><data key="layer">{t.assertion_layer}</data>'
                    f'<data key="confidence">{t.confidence}</data></edge>\n')
        f.write("  </graph>\n</graphml>\n")


def neo4j_csv(pkg: Package, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "nodes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id:ID", "label", ":LABEL", "attributes"])
        for e in pkg.entities.values():
            w.writerow([e.id, e.label, e.type, json.dumps(e.attributes, ensure_ascii=False)[:30000]])
        for dom in sorted({t.object for t in pkg.triples if t.object.startswith("DOM-")}):
            w.writerow([dom, dom[4:], "Domain", "{}"])
    with open(out / "edges.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([":START_ID", ":END_ID", ":TYPE", "layer", "confidence", "evidence"])
        for t in pkg.triples:
            ev = ";".join(f"{e.source_id}:{e.line_start}" for e in t.evidence)
            w.writerow([t.subject, t.object, t.predicate.upper(), t.assertion_layer, t.confidence, ev])


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|#^\[\]]+', "_", name).strip()[:120]


def obsidian(pkg: Package, out: Path, findings=()) -> int:
    out.mkdir(parents=True, exist_ok=True)
    names = {e.id: _safe(f"{e.id}") for e in pkg.entities.values()}
    edges = defaultdict(list)
    for t in pkg.triples:
        edges[t.subject].append(t)
    f_by = defaultdict(list)
    for f in findings:
        f_by[f["subject"].split("|")[0]].append(f)
    folder = {"ECR": "01-ECR", "ChangePoint": "02-ChangePoints", "Document": "03-Documents",
              "DocumentVersion": "03-Documents/versions", "ProductLabel": "04-Products"}
    n = 0
    for e in pkg.entities.values():
        d = out / folder.get(e.type, "05-Other")
        d.mkdir(parents=True, exist_ok=True)
        lines = ["---", f"type: {e.type}", f"label: {json.dumps(e.label, ensure_ascii=False)}", "---", "",
                 f"# {e.label}", ""]
        for k, v in e.attributes.items():
            if isinstance(v, (str, int, float)) and str(v):
                lines.append(f"- **{k}**: {str(v)[:500]}")
        if edges.get(e.id):
            lines += ["", "## Relations", ""]
            for t in edges[e.id][:200]:
                target = f"[[{names[t.object]}]]" if t.object in names else t.object
                lines.append(f"- {t.predicate} → {target} `{t.assertion_layer}`")
        if f_by.get(e.id):
            lines += ["", "## Open review findings (candidates)", ""]
            lines += [f"- **{f['severity']}** {f['check']}: {f['message']}" for f in f_by[e.id]]
        if e.evidence:
            lines += ["", "## Evidence", ""]
            lines += [f"- {ev.source_id} L{ev.line_start}-{ev.line_end}: {ev.quote[:200]}" for ev in e.evidence[:10]]
        (d / f"{names[e.id]}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        n += 1
    (out / "00-Start.md").write_text(
        "# ECR-Graph vault\n\nFolders: 01-ECR, 02-ChangePoints, 03-Documents, 04-Products.\n"
        "Everything here is a candidate work view; decisions belong to the named reviewers.\n", encoding="utf-8")
    return n
