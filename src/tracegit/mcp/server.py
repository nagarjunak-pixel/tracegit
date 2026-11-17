"""Zero-Dependency JSON-RPC 2.0 Model Context Protocol (`MCP`) Server for Claude Code / Cursor.

Exposes 4 practical developer tools over stdio (`tracegit mcp-stdio`) and in-process RPC:
- `tracegit_list_commits`: Inspect recent SHA-256 Merkle trace commits & cost/thrash metrics
- `tracegit_diff_commits`: Run C++20 Wagner-Fischer trajectory alignment diff between two runs
- `tracegit_bisect_failure`: Pinpoint exact first divergence step & loop culprit between good/bad runs
- `tracegit_evaluate_gate`: Run pre-ship CI cost/latency/loop-thrash regression gate
"""

from __future__ import annotations

import json
import sys
from typing import IO, Any

from tracegit.gate.regression_gate import bisect_first_failure, evaluate_regression_gate
from tracegit.store.dag_store import TraceStore


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "tracegit_list_commits",
            "description": "List recent AI agent execution trace commits with SHA-256 Merkle roots, token/cost totals, and loop-thrash alerts.",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 20}},
            },
        },
        {
            "name": "tracegit_diff_commits",
            "description": "Compute exact C++20 dynamic-programming step alignment diff between a baseline trace commit and candidate trace commit.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "base_commit_id": {"type": "string"},
                    "candidate_commit_id": {"type": "string"},
                },
                "required": ["base_commit_id", "candidate_commit_id"],
            },
        },
        {
            "name": "tracegit_bisect_failure",
            "description": "Pinpoint the exact first step where a regressed agent run diverged from a known-good run and identify the culprit tool/loop.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "good_commit_id": {"type": "string"},
                    "bad_commit_id": {"type": "string"},
                },
                "required": ["good_commit_id", "bad_commit_id"],
            },
        },
        {
            "name": "tracegit_evaluate_gate",
            "description": "Evaluate whether a candidate agent trace commit passes or blocks pre-ship CI cost, latency, success, and loop-thrash guardrails.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "base_commit_id": {"type": "string"},
                    "candidate_commit_id": {"type": "string"},
                },
                "required": ["base_commit_id", "candidate_commit_id"],
            },
        },
    ]


class TraceGitMCPServer:
    def __init__(self, store: TraceStore) -> None:
        self.store = store

    def handle_request(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = str(msg.get("method", ""))
        req_id = msg.get("id")

        if method == "notifications/initialized" or req_id is None:
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "tracegit-mcp", "version": "1.0.0"},
                },
            }

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _tool_definitions()}}

        if method == "tools/call":
            params = msg.get("params", {})
            name = str(params.get("name", ""))
            args = params.get("arguments", {}) or {}
            try:
                payload = self._dispatch_tool(name, args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
                        "isError": False,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error in {name}: {exc}"}],
                        "isError": True,
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def _dispatch_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "tracegit_list_commits":
            limit = int(args.get("limit", 20))
            commits = self.store.list_commits(limit=limit)
            return {
                "commits": [
                    {
                        "commit_id": c.commit_id,
                        "branch": c.branch,
                        "task_id": c.task_id,
                        "agent_model": c.agent_model,
                        "succeeded": c.task_succeeded,
                        "total_tokens": c.total_tokens,
                        "total_cost_usd": c.total_cost_usd,
                        "loop_events": c.thrash.loop_events,
                        "step_merkle_root": c.step_merkle_root[:16],
                    }
                    for c in commits
                ]
            }
        if name == "tracegit_diff_commits":
            diff = self.store.diff_commits(
                str(args["base_commit_id"]), str(args["candidate_commit_id"])
            )
            return diff.model_dump(mode="json")
        if name == "tracegit_bisect_failure":
            return bisect_first_failure(
                self.store, str(args["good_commit_id"]), str(args["bad_commit_id"])
            )
        if name == "tracegit_evaluate_gate":
            verdict = evaluate_regression_gate(
                self.store, str(args["base_commit_id"]), str(args["candidate_commit_id"])
            )
            return verdict.model_dump(mode="json")
        raise ValueError(f"Unknown MCP tool: {name}")

    def serve_streams(
        self, in_stream: IO[str] | None = None, out_stream: IO[str] | None = None
    ) -> None:
        r = in_stream or sys.stdin
        w = out_stream or sys.stdout
        for raw in r:
            line = raw.strip()
            if not line:
                continue
            req = json.loads(line)
            resp = self.handle_request(req)
            if resp is not None:
                w.write(json.dumps(resp) + "\n")
                w.flush()
