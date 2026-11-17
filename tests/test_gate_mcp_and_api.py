"""Unit tests for Regression Gate, Bisect, JSON-RPC 2.0 MCP Server, Live Audit Replay, FastAPI & CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from tracegit.api.app import create_app
from tracegit.audit.ollama_traces import build_trace_task_suite, run_real_trace_ollama_audit
from tracegit.cli import app as cli_app
from tracegit.gate.regression_gate import bisect_first_failure, evaluate_regression_gate
from tracegit.mcp.server import TraceGitMCPServer
from tracegit.store.dag_store import seed_default_demo_store
from tracegit.types import GatePolicyConfig


def test_regression_gate_blocks_thrash_cost_latency_and_passes_clean_fix() -> None:
    store, c_base, c_bug, c_fix = seed_default_demo_store()

    verdict_bug = evaluate_regression_gate(store, c_base.commit_id, c_bug.commit_id)
    assert verdict_bug.passed is False
    assert verdict_bug.verdict == "BLOCK"
    assert any("loop thrash" in r for r in verdict_bug.reasons)

    # Tight policy also triggers edit_distance & latency check
    strict = evaluate_regression_gate(
        store,
        c_base.commit_id,
        c_bug.commit_id,
        GatePolicyConfig(
            max_cost_increase_pct=5.0,
            max_latency_increase_pct=5.0,
            max_edit_distance=1,
        ),
    )
    assert any("Cost regression" in r for r in strict.reasons)
    assert any("Latency regression" in r for r in strict.reasons)
    assert any("Trajectory drift" in r for r in strict.reasons)

    verdict_fix = evaluate_regression_gate(store, c_base.commit_id, c_fix.commit_id)
    assert verdict_fix.passed is True
    assert verdict_fix.verdict == "PASS"

    bisect = bisect_first_failure(store, c_base.commit_id, c_bug.commit_id)
    assert bisect["culprit_tool"] == "read_file"


def test_mcp_stdio_jsonrpc_protocol_dispatch() -> None:
    store, c_base, c_bug, _ = seed_default_demo_store()
    mcp = TraceGitMCPServer(store)

    # Notification returns None
    assert mcp.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    # Initialize + tools/list + all 4 tool calls + error handling
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "tracegit_list_commits", "arguments": {"limit": 5}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "tracegit_diff_commits",
                "arguments": {
                    "base_commit_id": c_base.commit_id,
                    "candidate_commit_id": c_bug.commit_id,
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "tracegit_bisect_failure",
                "arguments": {"good_commit_id": c_base.commit_id, "bad_commit_id": c_bug.commit_id},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "tracegit_evaluate_gate",
                "arguments": {
                    "base_commit_id": c_base.commit_id,
                    "candidate_commit_id": c_bug.commit_id,
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "unknown_tool", "arguments": {}},
        },
        {"jsonrpc": "2.0", "id": 8, "method": "unknown/method", "params": {}},
    ]

    in_buf = io.StringIO("\n".join(json.dumps(r) for r in reqs) + "\n\n")
    out_buf = io.StringIO()
    mcp.serve_streams(in_buf, out_buf)
    responses = [json.loads(line) for line in out_buf.getvalue().splitlines()]
    assert len(responses) == 8
    assert responses[0]["result"]["serverInfo"]["name"] == "tracegit-mcp"
    assert len(responses[1]["result"]["tools"]) == 4
    assert responses[5]["result"]["isError"] is False
    assert responses[6]["result"]["isError"] is True
    assert responses[7]["error"]["code"] == -32601


def test_ollama_audit_mocked_and_offline_replay(tmp_path: Path) -> None:
    suite = build_trace_task_suite()
    assert len(suite) == 6
    fake_art = tmp_path / "trace_audit.json"

    class DummyResp:
        def __init__(self, status_code: int, payload: dict[str, object]) -> None:
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self._payload

    calls = {"i": 0}

    def fake_post(url: str, **kwargs: object) -> DummyResp:
        task_idx = calls["i"] // 2
        is_v2 = calls["i"] % 2 == 1
        calls["i"] += 1
        target = suite[task_idx].required_target
        if not is_v2:
            steps = [
                {"tool": "read_file", "arg": target},
                {"tool": "read_file", "arg": target},
                {"tool": "edit_file", "arg": target},
            ]
        else:
            steps = [
                {"tool": "read_file", "arg": target},
                {"tool": "edit_file", "arg": target},
                {"tool": "run_pytest", "arg": target},
            ]
        return DummyResp(
            200, {"response": json.dumps({"steps": steps}), "eval_count": 150 if not is_v2 else 90}
        )

    with (
        patch("httpx.get", return_value=DummyResp(200, {"models": []})),
        patch("httpx.post", side_effect=fake_post),
    ):
        rep = run_real_trace_ollama_audit(save_path=fake_art)
        assert rep.v1_verified_pct == 0.0
        assert rep.v2_verified_pct == 100.0
        assert rep.thrash_steps_eliminated == 6

    with patch("httpx.get", side_effect=httpx.ConnectError("offline")):
        replayed = run_real_trace_ollama_audit(save_path=fake_art, allow_offline_replay=True)
        assert replayed.num_tasks == 6
        with pytest.raises(RuntimeError, match="unreachable"):
            run_real_trace_ollama_audit(
                save_path=tmp_path / "missing.json", allow_offline_replay=False
            )


def test_fastapi_endpoints_and_cli() -> None:
    app = create_app()
    client = TestClient(app)

    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/").status_code == 200
    commits = client.get("/api/v1/commits").json()
    assert len(commits) == 3

    c0, c1 = commits[0]["commit_id"], commits[1]["commit_id"]
    assert (
        client.post(
            "/api/v1/diff", json={"base_commit_id": c0, "candidate_commit_id": c1}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/gate", json={"base_commit_id": c0, "candidate_commit_id": c1}
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/bisect?good_id={c0}&bad_id={c1}").status_code == 200
    assert client.get("/api/v1/audit/ollama").status_code == 200

    runner = CliRunner()
    assert runner.invoke(cli_app, ["demo"]).exit_code == 0
    assert runner.invoke(cli_app, ["eval-ollama"]).exit_code == 0
