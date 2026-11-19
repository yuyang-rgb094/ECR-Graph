"""Command line entry point: ``ecr-graph <command>`` or ``python -m ecr_graph <command>``."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import List

from . import __version__
from .config import PACKAGE_ROOT, Config, write_default
from .package import Package
from .util import read_json, read_jsonl, write_json, write_jsonl


# ------------------------------------------------------------------ stages
def _cfg(a) -> Config:
    return Config.load(Path(a.config))


def _profile(cfg: Config) -> dict:
    return read_json(cfg.path(cfg["profile"]))


def _knowledge(cfg: Config):
    from .knowledge import Knowledge
    return Knowledge.load(cfg.path(cfg["knowledge_dir"]))


def stage_ingest(cfg: Config) -> dict:
    from .ingest.router import ingest
    prof = _profile(cfg)
    cfg.data["_glyph_rules"] = prof.get("glyph_rules", [])
    m = ingest(cfg, prof["id_patterns"])
    s = m["summary"]
    print(f"ingest: {s['documents']} document(s), {s['failed']} failed → {cfg.work / 'manifest.json'}")
    for d in m["documents"]:
        for w in d.get("warnings", []):
            print(f"  ! {d['source_id']}: {w}")
        if d.get("error"):
            print(f"  ✗ {d['source_id']}: {d['error']}")
    return m


def stage_extract(cfg: Config) -> Package:
    from .extract.ecr import ECRExtractor, merge_attributes
    manifest = read_json(cfg.work / "manifest.json")
    ex = ECRExtractor(_profile(cfg))
    pkg = Package(cfg.work / "package", {"name": cfg["project_name"], "role": "base", "producer": f"ecr-graph {__version__}",
                                         "non_ecr_sources": []})
    for d in manifest["documents"]:
        if d.get("role") != "source" or not d.get("derived_text"):
            continue
        lines = (cfg.work / d["derived_text"]).read_text(encoding="utf-8").splitlines()
        res = ex.extract(d["source_id"], lines, d["derived_text"], d["sha256"])
        if not res.change_points and not res.transitions:
            pkg.meta["non_ecr_sources"].append(d["source_id"])
            continue
        for e in res.entities.values():
            if e.id in pkg.entities:
                cur = pkg.entities[e.id]
                merge_attributes(cur.attributes, e.attributes)
                known = {x.evidence_id for x in cur.evidence}
                cur.evidence.extend(x for x in e.evidence if x.evidence_id not in known)
            else:
                pkg.entities[e.id] = e
        pkg.triples.extend(res.triples)
        pkg.transitions.extend(res.transitions)
        pkg.change_points.extend(res.change_points)
    pkg.save()
    print(f"extract: {len(pkg.entities)} entities, {len(pkg.triples)} triples, {len(pkg.change_points)} change points, "
          f"{len(pkg.transitions)} file rows → {pkg.root}")
    return pkg


def stage_resolve(cfg: Config) -> dict:
    from .resolve import resolve
    pkg = Package.load(cfg.work / "package")
    rep = resolve(pkg, _knowledge(cfg))
    pkg.save()
    write_json(cfg.work / "reports" / "resolve.json", rep)
    print(f"resolve: merged {rep['duplicate_triples_merged']} duplicate triples, {rep['possible_identity']} possible_identity "
          f"candidates, {rep['same_as_from_adjudication']} adjudicated same_as, "
          f"{len(rep['same_number_different_title'])} numbers with several titles")
    return rep


def stage_check(cfg: Config) -> dict:
    from .checks import check_package
    pkg = Package.load(cfg.work / "package")
    rep = check_package(pkg, _profile(cfg).get("version_pattern"))
    write_json(cfg.work / "reports" / "validation.json", rep)
    print("check: " + ", ".join(f"{k}={v}" for k, v in rep["counts"].items()))
    return rep


def _revised(cfg: Config, pkg: Package):
    from .sufficiency import index_revised
    manifest = read_json(cfg.work / "manifest.json")
    return index_revised(manifest, cfg.work, [t["file_number"] for t in pkg.transitions])


def stage_crossref(cfg: Config) -> dict:
    from .crossref import build, load_rulepack, write_table
    pkg = Package.load(cfg.work / "package")
    k = _knowledge(cfg)
    pack = load_rulepack(cfg.rulepack("cross_review"), k)
    rev = {n: r["lines"] for n, r in _revised(cfg, pkg).items()}
    rep = build(pkg, k, pack, rev)
    write_table(rep["rows"], cfg.work / "reports" / "association_table.csv")
    write_json(cfg.work / "reports" / "crossref.json", {"doc_classes": rep["doc_classes"], "findings": rep["findings"]})
    print(f"crossref: {len(rep['rows'])} association rows, {len(rep['findings'])} findings")
    return rep


def stage_sufficiency(cfg: Config) -> dict:
    from .crossref import load_rulepack
    from .sufficiency import review
    pkg = Package.load(cfg.work / "package")
    k = _knowledge(cfg)
    classes = load_rulepack(cfg.rulepack("cross_review"), k)["doc_classes"]
    rep = review(pkg, _revised(cfg, pkg), read_json(cfg.rulepack("sufficiency")), classes)
    write_jsonl(cfg.work / "reports" / "sufficiency_packets.jsonl", rep.pop("packets"))
    write_json(cfg.work / "reports" / "sufficiency.json", rep)
    print("sufficiency: " + ", ".join(f"{k}={v}" for k, v in rep["stats"].items()))
    return rep


def stage_axes(cfg: Config) -> dict:
    from .axes import build_axes
    pkg = Package.load(cfg.work / "package")
    findings = _all_findings(cfg)
    meta = build_axes(pkg, cfg.work / "axes", findings)
    print("axes: " + ", ".join(f"{k}={v['record_count']}" for k, v in meta.items()))
    return meta


def _all_findings(cfg: Config) -> List[dict]:
    out = []
    for name in ("validation", "crossref", "sufficiency", "sufficiency_agent"):
        p = cfg.work / "reports" / f"{name}.json"
        if p.exists():
            out.extend(read_json(p).get("findings", []))
    return out


def stage_grill(cfg: Config, regimpact: dict = None) -> dict:
    from .grill import build, to_markdown
    r = cfg.work / "reports"
    load = lambda n: read_json(r / f"{n}.json") if (r / f"{n}.json").exists() else None  # noqa: E731
    g = build(_knowledge(cfg), checks=load("validation"), resolve_report=load("resolve"), sufficiency=load("sufficiency"),
              crossref=load("crossref"), regimpact=regimpact)
    write_json(r / "grill.json", g)
    (r / "grill.md").write_text(to_markdown(g), encoding="utf-8")
    print(f"grill: {len(g['questions'])} question(s) → {r / 'grill.md'}")
    return g


def stage_report(cfg: Config) -> None:
    findings = _all_findings(cfg)
    write_jsonl(cfg.work / "reports" / "findings.jsonl", findings)
    from collections import Counter
    by = Counter((f["check"], f["severity"]) for f in findings)
    lines = ["# ECR-Graph run summary", "", "All findings are candidates for named reviewers; none is a compliance conclusion.", "",
             "| check | severity | count |", "|---|---|---:|"]
    lines += [f"| {c} | {s} | {n} |" for (c, s), n in sorted(by.items(), key=lambda x: (-x[1], x[0]))]
    (cfg.work / "reports" / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report: {len(findings)} findings → {cfg.work / 'reports' / 'summary.md'}")


# ------------------------------------------------------------------ commands
def cmd_init(a):
    d = Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    for sub in ("sources", "revised", "knowledge/experience"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    cfg = d / "ecr-graph.json"
    if not cfg.exists():
        write_default(cfg, a.name or d.name)
    kt = PACKAGE_ROOT / "examples" / "knowledge-templates"
    if kt.exists():  # copied as *.template.* — rename after filling in, so empty templates are never loaded
        for f in kt.iterdir():
            if f.is_file() and not (d / "knowledge" / f.name).exists():
                shutil.copy2(f, d / "knowledge" / f.name)
    print(f"initialised {d}. Put ECR files in sources/, revised documents in revised/, customer knowledge in knowledge/.\n"
          f"Next: ecr-graph run -c {cfg}")


def cmd_run(a):
    cfg = _cfg(a)
    stage_ingest(cfg)
    stage_extract(cfg)
    stage_resolve(cfg)
    stage_check(cfg)
    stage_crossref(cfg)
    stage_sufficiency(cfg)
    stage_axes(cfg)
    stage_report(cfg)
    stage_grill(cfg)


def cmd_regimpact(a):
    from .regimpact import assess, load_proposal, proposal_from_change_point, to_markdown
    cfg = _cfg(a)
    if a.change_point:
        pkg = Package.load(cfg.work / "package")
        cp = next((c for c in pkg.change_points if c["id"] == a.change_point), None)
        if not cp:
            sys.exit(f"change point {a.change_point} not found")
        prop = proposal_from_change_point(cp)
    else:
        prop = load_proposal(Path(a.proposal))
    res = assess(prop, read_json(cfg.rulepack("registration_impact")), _knowledge(cfg), read_json(cfg.rulepack("sufficiency")))
    out = cfg.work / "reports" / "regimpact"
    out.mkdir(parents=True, exist_ok=True)
    stem = str(prop.get("id") or "proposal").replace("/", "_")
    write_json(out / f"{stem}.json", res)
    (out / f"{stem}.md").write_text(to_markdown(res), encoding="utf-8")
    print(f"regimpact: candidate outcome = {res['candidate_outcome']} → {out / (stem + '.md')}")
    if res["knowledge_gaps"]:
        stage_grill(cfg, res)


def cmd_review_ingest(a):
    from .sufficiency import ingest_agent_review
    cfg = _cfg(a)
    pkts = {p["packet_id"]: p for p in read_jsonl(cfg.work / "reports" / "sufficiency_packets.jsonl")}
    pkg = Package.load(cfg.work / "package")
    rep = ingest_agent_review(Path(a.responses), pkts, lambda p: pkg.text_lines(p, cfg.work))
    write_json(cfg.work / "reports" / "sufficiency_agent.json", rep)
    print(f"agent review: {len(rep['findings'])} accepted finding(s), {len(rep['rejected'])} rejected (unverifiable)")


def cmd_candidates(a):
    from .extract.candidates import import_candidates
    cfg = _cfg(a)
    base = Package.load(cfg.work / "package")
    ents, trs, rej = import_candidates(Path(a.file), a.producer, lambda p: base.text_lines(p, cfg.work))
    pkg = Package(cfg.work / "candidates" / a.producer, {"name": a.producer, "role": "candidate"})
    pkg.entities = {e.id: e for e in ents}
    pkg.triples = trs
    pkg.save()
    write_jsonl(pkg.root / "rejected.jsonl", rej)
    print(f"candidates: {len(ents)} entities, {len(trs)} triples accepted; {len(rej)} rejected → {pkg.root}")


def cmd_merge(a):
    from .merge import merge_packages
    base = Package.load(Path(a.base))
    others = [Package.load(Path(p)) for p in a.candidates]
    meta = merge_packages(base, others, Path(a.out))
    print(json.dumps(meta, ensure_ascii=False, indent=2))


def cmd_export(a):
    from . import export
    cfg = _cfg(a)
    pkg = Package.load(Path(a.package) if a.package else cfg.work / "package")
    out = cfg.work / "export"
    if a.format in ("graphml", "all"):
        export.graphml(pkg, out / "graph.graphml")
    if a.format in ("neo4j", "all"):
        export.neo4j_csv(pkg, out / "neo4j")
    if a.format in ("obsidian", "all"):
        n = export.obsidian(pkg, out / "vault", _all_findings(cfg))
        print(f"obsidian: {n} notes")
    print(f"export → {out}")


def cmd_mineru(a):
    from .ingest import mineru
    if a.action == "doctor":
        import shutil as sh
        import os
        print(f"mineru-kit (4.x): {sh.which('mineru-kit') or 'not found'}")
        print(f"mineru (2.x):     {sh.which('mineru') or 'not found'}")
        print(f"MINERU_API_KEY:   {'set' if os.environ.get('MINERU_API_KEY') else 'not set'}")
        print(f"cloud pages used today (this machine): {mineru.quota_used_today()} / {mineru.DAILY_PRIORITY_PAGES} high-priority")
        print("Install locally: scripts/install_mineru.sh   |   Cloud key: https://mineru.net (see docs/LARGE-DOCUMENTS.md)")
        return
    src = Path(a.file)
    if a.action == "pages":
        print(mineru.count_pages(src))
    elif a.action == "split":
        for p in mineru.split_pdf(src, Path(a.out)):
            print(p)
    elif a.action == "parse":
        cfg = _cfg(a)
        mc = cfg["mineru"]
        out = Path(a.out)
        if a.cloud:
            mds = mineru.run_cloud(src, out, consent=bool(mc.get("cloud_upload_allowed")),
                                   model_version=mc.get("model_version", "vlm"),
                                   allow_low_priority=a.allow_low_priority or bool(mc.get("allow_low_priority")))
        else:
            mds = [mineru.run_local(src, out, tier=mc.get("tier", "standard"), template=mc.get("local_command"))]
        for m in mds:
            print(m)


def cmd_leakscan(a):
    from .leakscan import load_denylist, scan
    deny = load_denylist(Path(a.denylist)) if a.denylist else []
    hits = scan([Path(p) for p in a.paths], deny, a.allow or [])
    for h in hits:
        print(json.dumps(h, ensure_ascii=False))
    print(f"leakscan: {len(hits)} hit(s)")
    sys.exit(1 if hits else 0)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ecr-graph", description="Evidence-governed ECR change graph toolkit")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_cfg(p):
        p.add_argument("-c", "--config", default="ecr-graph.json")
        return p

    p = sub.add_parser("init", help="create a project folder")
    p.add_argument("dir")
    p.add_argument("--name")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("demo", help="write a fully fictional demo project (two ECRs, revised files, knowledge)")
    p.add_argument("dir")
    p.set_defaults(fn=lambda a: print(__import__("ecr_graph._synthetic", fromlist=["x"]).write_demo(Path(a.dir))))
    for name, fn, hlp in (("ingest", stage_ingest, "parse sources into line-numbered evidence text"),
                          ("extract", stage_extract, "extract ECRs, change points, file rows"),
                          ("resolve", stage_resolve, "dedupe + conservative disambiguation"),
                          ("check", stage_check, "deterministic validation"),
                          ("crossref", stage_crossref, "document association table + cross-review"),
                          ("sufficiency", stage_sufficiency, "change-content sufficiency review"),
                          ("axes", stage_axes, "build the five axis indexes"),
                          ("grill", stage_grill, "questions / document requests for the customer"),
                          ("report", stage_report, "collect findings + summary")):
        p = with_cfg(sub.add_parser(name, help=hlp))
        p.set_defaults(fn=lambda a, f=fn: f(_cfg(a)))
    p = with_cfg(sub.add_parser("run", help="ingest → extract → resolve → check → crossref → sufficiency → axes → report → grill"))
    p.set_defaults(fn=cmd_run)
    p = with_cfg(sub.add_parser("regimpact", help="registration-impact pre-assessment of a proposal"))
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--proposal")
    g.add_argument("--change-point")
    p.set_defaults(fn=cmd_regimpact)
    p = with_cfg(sub.add_parser("review-ingest", help="validate agent answers to sufficiency packets"))
    p.add_argument("responses")
    p.set_defaults(fn=cmd_review_ingest)
    p = with_cfg(sub.add_parser("candidates", help="import agent-proposed entities/triples (evidence-verified)"))
    p.add_argument("file")
    p.add_argument("--producer", required=True)
    p.set_defaults(fn=cmd_candidates)
    p = sub.add_parser("merge", help="merge a base package with candidate packages")
    p.add_argument("--base", required=True)
    p.add_argument("--candidates", nargs="+", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_merge)
    p = with_cfg(sub.add_parser("export", help="GraphML / Neo4j CSV / Obsidian vault"))
    p.add_argument("--format", choices=["graphml", "neo4j", "obsidian", "all"], default="all")
    p.add_argument("--package")
    p.set_defaults(fn=cmd_export)
    p = with_cfg(sub.add_parser("mineru", help="large-document parsing helpers"))
    p.add_argument("action", choices=["doctor", "pages", "split", "parse"])
    p.add_argument("file", nargs="?")
    p.add_argument("--out", default="mineru-out")
    p.add_argument("--cloud", action="store_true")
    p.add_argument("--allow-low-priority", action="store_true")
    p.set_defaults(fn=cmd_mineru)
    p = sub.add_parser("mcp", help="serve a work directory over read-only MCP (stdio)")
    p.add_argument("--work", required=True)
    p.set_defaults(fn=lambda a: __import__("ecr_graph.mcp_server", fromlist=["serve"]).serve(Path(a.work)))
    p = sub.add_parser("leakscan", help="scan files for confidential terms before sharing")
    p.add_argument("paths", nargs="+")
    p.add_argument("--denylist")
    p.add_argument("--allow", nargs="*")
    p.set_defaults(fn=cmd_leakscan)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
