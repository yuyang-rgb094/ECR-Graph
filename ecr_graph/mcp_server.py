"""Read-only MCP server (stdio, JSON-RPC 2.0, no dependencies).

Exposes a finished work directory to an agent: search entities, read one
entity with evidence, list findings / conflicts / grill questions, look up an
axis index. It never writes, never adjudicates and never calls the network.

Register with an MCP client, e.g.::

    {"mcpServers": {"ecr-graph": {"command": "python3",
        "args": ["-m", "ecr_graph", "mcp", "--work", "/path/to/work"]}}}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from .package import Package
from .util import normalize_label, read_json, read_jsonl

PROTOCOL = "2024-11-05"

TOOLS = [
    {"name": "search_entities", "description": "Find entities whose id or label contains the query (case/width-insensitive).",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "type": {"type": "string"},
                                                      "limit": {"type": "integer"}}, "required": ["query"]}},
    {"name": "get_entity", "description": "Return one entity with its evidence and outgoing/incoming relations.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "list_findings", "description": "List review findings (candidates), filterable by check prefix, severity or subject.",
     "inputSchema": {"type": "object", "properties": {"check": {"type": "string"}, "severity": {"type": "string"},
                                                      "subject": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "list_conflicts", "description": "List the merge conflict ledger, if a merge was run.",
     "inputSchema": {"type": "object", "properties": {"kind": {"type": "string"}}}},
    {"name": "axis_lookup", "description": "Look up record ids in an axis index, then return the records.",
     "inputSchema": {"type": "object", "properties": {"axis": {"type": "string"}, "index": {"type": "string"},
                                                      "value": {"type": "string"}}, "required": ["axis", "index", "value"]}},
    {"name": "grill_questions", "description": "Open questions for the customer generated from detected gaps.",
     "inputSchema": {"type": "object", "properties": {}}},
]


class Server:
    def __init__(self, work: Path):
        self.work = Path(work)
        self.pkg = Package.load(self.work / "package")
        self._findings = None

    def findings(self):
        if self._findings is None:
            p = self.work / "reports" / "findings.jsonl"
            self._findings = list(read_jsonl(p)) if p.exists() else []
        return self._findings

    # ---------------------------------------------------------------- tools
    def call(self, name: str, a: Dict[str, Any]):
        if name == "search_entities":
            q = normalize_label(a["query"])
            hits = [e for e in self.pkg.entities.values()
                    if (q in normalize_label(e.id) or q in normalize_label(e.label)) and (not a.get("type") or e.type == a["type"])]
            return [{"id": e.id, "type": e.type, "label": e.label} for e in hits[: a.get("limit", 25)]]
        if name == "get_entity":
            e = self.pkg.entities.get(a["id"])
            if not e:
                return {"error": "not found"}
            out = [t.to_dict() for t in self.pkg.triples if t.subject == e.id][:200]
            inc = [t.to_dict() for t in self.pkg.triples if t.object == e.id][:200]
            return {"entity": e.to_dict(), "outgoing": out, "incoming": inc}
        if name == "list_findings":
            fs = [f for f in self.findings()
                  if f["check"].startswith(a.get("check", "")) and (not a.get("severity") or f["severity"] == a["severity"])
                  and (not a.get("subject") or a["subject"] in f["subject"])]
            return fs[: a.get("limit", 50)]
        if name == "list_conflicts":
            p = self.work / "merged" / "conflicts.jsonl"
            rows = list(read_jsonl(p)) if p.exists() else []
            return [r for r in rows if not a.get("kind") or r["kind"] == a["kind"]][:200]
        if name == "axis_lookup":
            p = self.work / "axes" / f"{a['axis']}.json"
            if not p.exists():
                return {"error": f"axis {a['axis']} not built"}
            ax = read_json(p)
            ids = ax["indexes"].get(a["index"], {}).get(a["value"], [])
            recs = {r["record_id"]: r for r in ax["records"]}
            return [recs[i] for i in ids[:50] if i in recs]
        if name == "grill_questions":
            p = self.work / "reports" / "grill.json"
            return read_json(p) if p.exists() else {"questions": []}
        raise ValueError(f"unknown tool {name}")

    # ---------------------------------------------------------------- protocol
    def handle(self, msg: dict):
        mid, method = msg.get("id"), msg.get("method")
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                                                            "serverInfo": {"name": "ecr-graph", "version": "0.1.0"}}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
        if method == "tools/call":
            p = msg.get("params", {})
            try:
                res = self.call(p.get("name"), p.get("arguments") or {})
                return {"jsonrpc": "2.0", "id": mid, "result": {"content": [
                    {"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}}
            except Exception as exc:  # report, do not crash the server
                return {"jsonrpc": "2.0", "id": mid, "result": {"isError": True, "content": [{"type": "text", "text": str(exc)}]}}
        if mid is None:  # notification
            return None
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def serve(work: Path) -> None:
    srv = Server(work)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            resp = srv.handle(json.loads(line))
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
