"""Golden tests on fully fictional data (python3 -m unittest discover -s tests)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ecr_graph import _synthetic  # noqa: E402
from ecr_graph.cli import (stage_check, stage_crossref, stage_extract, stage_ingest,  # noqa: E402
                           stage_resolve, stage_sufficiency, stage_axes, stage_report, stage_grill)
from ecr_graph.config import Config  # noqa: E402
from ecr_graph.extract.candidates import import_candidates  # noqa: E402
from ecr_graph.ingest.docx_text import read_docx  # noqa: E402
from ecr_graph.ingest import mineru  # noqa: E402
from ecr_graph.knowledge import Knowledge  # noqa: E402
from ecr_graph.leakscan import scan  # noqa: E402
from ecr_graph.merge import merge_packages  # noqa: E402
from ecr_graph.model import Triple  # noqa: E402
from ecr_graph.package import Package  # noqa: E402
from ecr_graph.regimpact import assess, parse_limit, within  # noqa: E402
from ecr_graph.util import read_json  # noqa: E402


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ecrgraph-"))
        _synthetic.write_demo(cls.tmp)
        cls.cfg = Config.load(cls.tmp / "ecr-graph.json")
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            stage_ingest(cls.cfg)
            stage_extract(cls.cfg)
            stage_resolve(cls.cfg)
            cls.checks = stage_check(cls.cfg)
            cls.cross = stage_crossref(cls.cfg)
            cls.suff = stage_sufficiency(cls.cfg)
            stage_axes(cls.cfg)
            stage_report(cls.cfg)
            cls.grill = stage_grill(cls.cfg)
        cls.pkg = Package.load(cls.cfg.work / "package")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def checks_of(self, findings, check):
        return [f for f in findings if f["check"] == check]

    # ---- parsing ----------------------------------------------------------
    def test_docx_tables_and_checkboxes(self):
        d = read_docx(self.tmp / "sources" / "EC-2601-001 工程更改申请单.docx")
        self.assertEqual(d.tables, 3)
        self.assertIn("[T2R2] 类型：□紧急 ■常规 | 产品所处阶段：□试产 ■量产", d.lines)

    def test_manifest_records_hashes(self):
        m = read_json(self.cfg.work / "manifest.json")
        self.assertEqual(len(m["documents"]), 5)
        self.assertTrue(all(len(d["sha256"]) == 64 for d in m["documents"]))

    # ---- extraction / keys ------------------------------------------------
    def test_change_point_keys(self):
        ids = sorted(c["id"] for c in self.pkg.change_points)
        self.assertEqual(ids, ["CP-EC-2601-001-S01P01", "CP-EC-2601-001-S01P02", "CP-EC-2601-001-S02P01",
                               "CP-EC-2602-004-S01P01"])
        ecr = self.pkg.entities["EC-2601-001"]
        self.assertEqual(ecr.attributes["sections"]["2"]["nature"], ["法规及注册要求"])

    def test_rows_link_to_change_points(self):
        row = next(t for t in self.pkg.transitions if t["file_number"] == "QD-IFU-002")
        self.assertEqual(row["change_point_ids"], ["CP-EC-2601-001-S02P01"])
        self.assertEqual(row["operation"], "upgrade")

    # ---- checks -----------------------------------------------------------
    def test_evidence_and_graph_integrity(self):
        c = self.checks["counts"]
        self.assertEqual(c["duplicate_spo"], 0)
        self.assertEqual(c["dangling_edges"], 0)
        self.assertEqual(c["evidence_quote_mismatch"], 0)
        self.assertEqual(c["evidence_text_missing"], 0)

    def test_version_chain_and_references(self):
        c = self.checks["counts"]
        self.assertEqual(c["rows_with_unresolved_change_point_refs"], 1)  # 更改点3 does not exist
        self.assertEqual(c["version_backwards"], 1)                     # V1.0 → V1.0
        self.assertEqual(c["version_gaps"], 1)                          # V4.0 then V5.0

    # ---- disambiguation ---------------------------------------------------
    def test_market_variants_not_merged(self):
        same = [t for t in self.pkg.triples if t.predicate == "same_as"]
        poss = [t for t in self.pkg.triples if t.predicate == "possible_identity"]
        self.assertEqual(same, [])
        self.assertEqual(len(poss), 3)

    def test_same_as_requires_human(self):
        with self.assertRaises(ValueError):
            Triple("A", "same_as", "B", "rule_derived")

    # ---- cross review -----------------------------------------------------
    def test_companion_rules(self):
        f = self.checks_of(self.cross["findings"], "crossref.companion_not_in_file_list")
        rules = {x["details"]["rule"] for x in f}
        self.assertTrue({"XR-001", "XR-002", "XR-004", "XR-006"} <= rules)
        ifu = next(x for x in f if x["details"]["rule"] == "XR-006")
        self.assertTrue(any(h["id"] == "IF-001" for h in ifu["details"]["related_experience"]))

    # ---- sufficiency (3a) -------------------------------------------------
    def test_sufficiency_detects_gaps(self):
        fs = self.suff["findings"]
        stale = {x["subject"] for x in self.checks_of(fs, "sufficiency.stale_old_value")}
        self.assertIn("CP-EC-2601-001-S01P01|QD-SW-010", stale)
        missing = [x for x in self.checks_of(fs, "sufficiency.new_value_missing") if x["subject"] == "CP-EC-2601-001-S02P01"]
        self.assertEqual(missing[0]["details"]["fact"]["value"], "禁止在强磁场环境下使用")
        nc = {x["subject"] for x in self.checks_of(fs, "sufficiency.not_checkable")}
        self.assertIn("CP-EC-2601-001-S01P02", nc)
        # the satisfied requirement (5 s in the SRS) must not be reported
        self.assertFalse(any("'5 s'" in x["message"] for x in fs))

    def test_agent_review_requires_verifiable_lines(self):
        from ecr_graph.sufficiency import ingest_agent_review
        lines = (self.cfg.work / "reports" / "sufficiency_packets.jsonl").read_text(encoding="utf-8").splitlines()
        pkts = {p["packet_id"]: p for p in map(json.loads, lines)}
        pid, pkt = next((k, v) for k, v in pkts.items() if v["document"]["file_number"] == "QD-IFU-002")
        resp = self.tmp / "resp.jsonl"
        good = {"packet_id": pid, "verdict_candidate": "gaps_found", "reviewer": "agent:test",
                "gaps": [{"description": "warning missing", "expected_content": "强磁场警示", "absent": True},
                         {"description": "fabricated", "evidence": [{"path": pkt["document"]["text_path"], "line_start": 2,
                                                                     "line_end": 2, "quote": "并不存在的句子"}]}]}
        resp.write_text(json.dumps(good, ensure_ascii=False) + "\n", encoding="utf-8")
        rep = ingest_agent_review(resp, pkts, lambda p: self.pkg.text_lines(p, self.cfg.work))
        self.assertEqual(len(rep["findings"]), 1)
        self.assertEqual(len(rep["rejected"]), 1)

    # ---- registration impact (3b) -----------------------------------------
    def test_limits(self):
        self.assertFalse(within(parse_limit("≤10 s"), 12))
        self.assertTrue(within(parse_limit("10~100 mm"), 50))
        self.assertTrue(within(parse_limit("50±5 Hz"), 54))

    def test_regimpact_outcomes(self):
        k = Knowledge.load(self.tmp / "knowledge")
        pack = read_json(ROOT / "rulepacks" / "registration-impact.template.json")
        sp = read_json(ROOT / "rulepacks" / "sufficiency.template.json")
        p1 = read_json(self.tmp / "proposals" / "PRP-001.json")
        self.assertEqual(assess(p1, pack, k, sp)["candidate_outcome"], "likely_registration_change")
        p2 = read_json(self.tmp / "proposals" / "PRP-002.json")
        r2 = assess(p2, pack, k, sp)
        sw = next(d for d in r2["dimensions"] if d["id"] == "RD-SOFTWARE")
        self.assertEqual(sw["comparisons"][0]["registration_relevant_changed"], [])
        empty = Knowledge(Path("/nonexistent"))
        r3 = assess(p1, pack, empty, sp)
        self.assertEqual(r3["candidate_outcome"], "insufficient_information")
        self.assertIn("registration_items", r3["knowledge_gaps"])

    # ---- grill ------------------------------------------------------------
    def test_grill_asks_for_missing_revisions(self):
        topics = {q["topic"] for q in self.grill["questions"]}
        self.assertIn("revised_documents", topics)
        self.assertIn("identity", topics)
        g = __import__("ecr_graph.grill", fromlist=["build"]).build(Knowledge(Path("/nonexistent")))
        self.assertTrue({"inspection_checklist", "inspection_experience", "registration_items"} <=
                        {q["topic"] for q in g["questions"]})

    # ---- axes / merge / candidates ----------------------------------------
    def test_axes_contract(self):
        for name in ("01-change-events", "04-controlled-files", "05-impact-relationships"):
            ax = read_json(self.cfg.work / "axes" / f"{name}.json")
            self.assertEqual(set(ax), {"metadata", "indexes", "records", "evidence_registry", "query_examples", "quality"})
            for r in ax["records"]:
                for e in r["evidence_ids"]:
                    self.assertIn(e, ax["evidence_registry"])

    def test_candidates_and_merge(self):
        ev = self.pkg.change_points[0]["evidence"]
        cand = self.tmp / "cand.jsonl"
        rows = [
            {"kind": "triple", "subject": "CP-EC-2601-001-S01P01", "predicate": "affects_object", "object": "OBJ-RECON",
             "evidence": [{**ev, "quote": "缩短图像重建时间", "evidence_id": ""}]},
            {"kind": "triple", "subject": "PRD-A", "predicate": "same_as", "object": "PRD-B",
             "evidence": [{**ev, "quote": "缩短图像重建时间", "evidence_id": ""}]},
            {"kind": "triple", "subject": "X", "predicate": "p", "object": "Y",
             "evidence": [{**ev, "quote": "invented text", "evidence_id": ""}]},
        ]
        cand.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        ents, trs, rej = import_candidates(cand, "agentX", lambda p: self.pkg.text_lines(p, self.cfg.work))
        self.assertEqual(len(trs), 2)
        self.assertEqual(len(rej), 1)
        self.assertEqual(trs[1].predicate, "possible_identity")
        other = Package(self.tmp / "cpkg", {"name": "agentX"})
        other.triples = trs
        meta = merge_packages(Package.load(self.cfg.work / "package"), [other], self.tmp / "merged")
        self.assertEqual(meta["stats"]["agentX"]["candidates"], 2)
        self.assertGreaterEqual(meta["conflicts"], 1)

    # ---- mineru / leakscan -------------------------------------------------
    def test_mineru_page_ranges(self):
        self.assertEqual(mineru.page_ranges(450), ["1-200", "201-400", "401-450"])
        self.assertEqual(mineru.page_ranges(None), [None])
        with self.assertRaises(mineru.MinerUError):
            mineru.run_cloud(self.tmp / "ecr-graph.json", self.tmp / "m", consent=False)

    def test_leakscan(self):
        import re
        hits = scan([self.tmp / "knowledge"], [re.compile("LumaScan")])
        self.assertEqual(hits, [])
        hits = scan([self.tmp / "revised"], [re.compile("LumaScan")])
        self.assertTrue(hits)


if __name__ == "__main__":
    unittest.main()
