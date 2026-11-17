"""Content-Addressable SQLite + SHA-256 Merkle DAG Store & Importers (Claude Code JSONL / OpenAI Traces)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from tracegit.kernels.native_diff import (
    active_backend_name,
    align_step_hashes,
    detect_loop_thrash,
    hash_step_signature,
)
from tracegit.types import AlignedStepPair, TraceCommit, TraceDiffReport, TraceStep


def compute_step_merkle_root(steps: list[TraceStep]) -> str:
    if not steps:
        return hashlib.sha256(b"EMPTY_TRACE").hexdigest()
    leaves = [
        hashlib.sha256(
            f"{s.step_index}:{s.tool_name}:{s.status}:{s.args_summary}".encode()
        ).hexdigest()
        for s in steps
    ]
    layer = leaves
    while len(layer) > 1:
        nxt: list[str] = []
        for idx in range(0, len(layer), 2):
            left = layer[idx]
            right = layer[idx + 1] if idx + 1 < len(layer) else left
            nxt.append(hashlib.sha256(f"{left}:{right}".encode()).hexdigest())
        layer = nxt
    return layer[0]


def import_claude_code_jsonl(jsonl_text: str) -> list[TraceStep]:
    """Parse Claude Code transcript JSONL lines containing `tool_use` blocks into normalized TraceSteps."""
    steps: list[TraceStep] = []
    for line in jsonl_text.splitlines():
        line_s = line.strip()
        if not line_s:
            continue
        obj = json.loads(line_s)
        content = obj.get("message", {}).get("content", obj.get("content", []))
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    name = str(item.get("name", "unknown_tool"))
                    inp = item.get("input", {})
                    summary = json.dumps(inp, sort_keys=True, separators=(",", ":"))[:140]
                    usage = obj.get("message", {}).get("usage", {})
                    toks = int(usage.get("output_tokens", 120) or 120)
                    steps.append(
                        TraceStep(
                            step_index=len(steps),
                            tool_name=name,
                            args_summary=summary,
                            status="ok",
                            tokens_used=toks,
                            cost_usd=round(toks * 0.000015, 6),
                            latency_ms=42.0,
                        )
                    )
    return steps


def import_openai_tool_trace(payload: dict[str, Any]) -> list[TraceStep]:
    """Parse OpenAI/OpenRouter responses or assistant `tool_calls` trace payloads into TraceSteps."""
    calls = payload.get("tool_calls", [])
    steps: list[TraceStep] = []
    for call in calls:
        fn = call.get("function", call)
        name = str(fn.get("name", "tool"))
        raw_args = fn.get("arguments", {})
        if isinstance(raw_args, str):
            try:
                args_obj = json.loads(raw_args)
                summary = json.dumps(args_obj, sort_keys=True, separators=(",", ":"))[:140]
            except json.JSONDecodeError:
                summary = raw_args[:140]
        else:
            summary = json.dumps(raw_args, sort_keys=True, separators=(",", ":"))[:140]
        toks = int(call.get("tokens_used", 90))
        steps.append(
            TraceStep(
                step_index=len(steps),
                tool_name=name,
                args_summary=summary,
                status=str(call.get("status", "ok")),
                tokens_used=toks,
                cost_usd=round(toks * 0.000012, 6),
                latency_ms=float(call.get("latency_ms", 35.0)),
            )
        )
    return steps


class TraceStore:
    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trace_commits (
                seq_no INTEGER PRIMARY KEY AUTOINCREMENT,
                commit_id TEXT UNIQUE NOT NULL,
                parent_id TEXT,
                branch TEXT NOT NULL,
                task_id TEXT NOT NULL,
                agent_model TEXT NOT NULL,
                prompt_summary TEXT NOT NULL,
                task_succeeded INTEGER NOT NULL,
                step_merkle_root TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def commit_trace(
        self,
        *,
        task_id: str,
        agent_model: str,
        prompt_summary: str,
        steps: list[TraceStep],
        branch: str = "main",
        parent_id: str | None = None,
        task_succeeded: bool = True,
    ) -> TraceCommit:
        merkle = compute_step_merkle_root(steps)
        prompt_hash = hashlib.sha256(prompt_summary.encode()).hexdigest()[:16]
        cid_raw = f"{parent_id or 'ROOT'}:{branch}:{task_id}:{agent_model}:{prompt_hash}:{merkle}"
        commit_id = hashlib.sha256(cid_raw.encode()).hexdigest()[:12]

        thrash = detect_loop_thrash(steps)
        total_toks = sum(s.tokens_used for s in steps)
        total_cost = round(sum(s.cost_usd for s in steps), 6)
        total_lat = round(sum(s.latency_ms for s in steps), 2)

        commit = TraceCommit(
            commit_id=commit_id,
            parent_id=parent_id,
            branch=branch,
            task_id=task_id,
            agent_model=agent_model,
            prompt_summary=prompt_summary,
            task_succeeded=task_succeeded,
            step_merkle_root=merkle,
            total_tokens=total_toks,
            total_cost_usd=total_cost,
            total_latency_ms=total_lat,
            thrash=thrash,
            steps=steps,
        )
        self._conn.execute(
            """
            INSERT OR REPLACE INTO trace_commits (
                commit_id, parent_id, branch, task_id, agent_model, prompt_summary,
                task_succeeded, step_merkle_root, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                commit.commit_id,
                commit.parent_id,
                commit.branch,
                commit.task_id,
                commit.agent_model,
                commit.prompt_summary,
                1 if commit.task_succeeded else 0,
                commit.step_merkle_root,
                commit.model_dump_json(),
            ),
        )
        self._conn.commit()
        return commit

    def get_commit(self, commit_id: str) -> TraceCommit:
        row = self._conn.execute(
            "SELECT payload_json FROM trace_commits WHERE commit_id = ?", (commit_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Commit {commit_id} not found in TraceStore")
        return TraceCommit.model_validate_json(str(row[0]))

    def list_commits(self, limit: int = 50) -> list[TraceCommit]:
        rows = self._conn.execute(
            "SELECT payload_json FROM trace_commits ORDER BY seq_no ASC LIMIT ?", (limit,)
        ).fetchall()
        return [TraceCommit.model_validate_json(str(r[0])) for r in rows]

    def diff_commits(self, base_commit_id: str, candidate_commit_id: str) -> TraceDiffReport:
        base = self.get_commit(base_commit_id)
        cand = self.get_commit(candidate_commit_id)

        seq_a = [hash_step_signature(s) for s in base.steps]
        seq_b = [hash_step_signature(s) for s in cand.steps]
        edit_dist, raw_ops, div_a, div_b = align_step_hashes(seq_a, seq_b)

        max_len = max(1, max(len(seq_a), len(seq_b)))
        sim_pct = round(max(0.0, (1.0 - (edit_dist / max_len)) * 100.0), 2)

        pairs = [
            AlignedStepPair(
                op=op,
                base_step=base.steps[ia] if ia >= 0 else None,
                candidate_step=cand.steps[ib] if ib >= 0 else None,
            )
            for op, ia, ib in raw_ops
        ]
        return TraceDiffReport(
            backend=active_backend_name(),
            base_commit_id=base.commit_id,
            candidate_commit_id=cand.commit_id,
            edit_distance=edit_dist,
            similarity_pct=sim_pct,
            first_divergence_step_base=div_a,
            first_divergence_step_candidate=div_b,
            token_delta=cand.total_tokens - base.total_tokens,
            cost_delta_usd=round(cand.total_cost_usd - base.total_cost_usd, 6),
            latency_delta_ms=round(cand.total_latency_ms - base.total_latency_ms, 2),
            alignment=pairs,
        )


def seed_default_demo_store(
    store: TraceStore | None = None,
) -> tuple[TraceStore, TraceCommit, TraceCommit, TraceCommit]:
    """Seed realistic Claude-Code-style agent commits: clean baseline -> looping buggy -> repaired v2."""
    db = store or TraceStore(":memory:")
    existing = db.list_commits()
    if len(existing) >= 3:
        return db, existing[0], existing[1], existing[2]

    baseline_steps = [
        TraceStep(
            step_index=0,
            tool_name="git_status",
            args_summary="repo=checkout-svc",
            tokens_used=110,
            cost_usd=0.00165,
            latency_ms=28,
        ),
        TraceStep(
            step_index=1,
            tool_name="read_file",
            args_summary="path=src/auth/jwt.py",
            tokens_used=420,
            cost_usd=0.00630,
            latency_ms=41,
        ),
        TraceStep(
            step_index=2,
            tool_name="grep_search",
            args_summary="pattern=verify_signature",
            tokens_used=190,
            cost_usd=0.00285,
            latency_ms=33,
        ),
        TraceStep(
            step_index=3,
            tool_name="edit_file",
            args_summary="path=src/auth/jwt.py#L42",
            tokens_used=310,
            cost_usd=0.00465,
            latency_ms=52,
        ),
        TraceStep(
            step_index=4,
            tool_name="run_pytest",
            args_summary="target=tests/test_jwt.py",
            tokens_used=240,
            cost_usd=0.00360,
            latency_ms=610,
        ),
    ]
    c_base = db.commit_trace(
        task_id="fix-jwt-exp-validation",
        agent_model="claude-opus-5.5",
        prompt_summary="Fix leeway expiry edge case in JWT verifier and run tests",
        steps=baseline_steps,
        branch="main",
        task_succeeded=True,
    )

    # Regressed candidate introduces a blind 3x retry loop reading/grepping and skips pytest
    buggy_steps = [
        baseline_steps[0],
        baseline_steps[1],
        TraceStep(
            step_index=2,
            tool_name="read_file",
            args_summary="path=src/auth/jwt.py",
            status="redundant",
            tokens_used=420,
            cost_usd=0.00630,
            latency_ms=41,
        ),
        TraceStep(
            step_index=3,
            tool_name="grep_search",
            args_summary="pattern=verify_signature",
            tokens_used=190,
            cost_usd=0.00285,
            latency_ms=33,
        ),
        TraceStep(
            step_index=4,
            tool_name="grep_search",
            args_summary="pattern=verify_signature",
            tokens_used=190,
            cost_usd=0.00285,
            latency_ms=33,
        ),
        TraceStep(
            step_index=5,
            tool_name="grep_search",
            args_summary="pattern=verify_signature",
            tokens_used=190,
            cost_usd=0.00285,
            latency_ms=33,
        ),
        TraceStep(
            step_index=6,
            tool_name="edit_file",
            args_summary="path=src/auth/jwt.py#L42",
            tokens_used=310,
            cost_usd=0.00465,
            latency_ms=52,
        ),
        TraceStep(
            step_index=7,
            tool_name="run_pytest",
            args_summary="target=tests/test_jwt.py",
            status="failed",
            tokens_used=390,
            cost_usd=0.00585,
            latency_ms=890,
        ),
    ]
    c_bug = db.commit_trace(
        task_id="fix-jwt-exp-validation",
        agent_model="agent-prompt-v1-unbounded",
        prompt_summary="Unbounded agent attempt after naive system prompt edit",
        steps=buggy_steps,
        branch="feature/prompt-v1-regression",
        parent_id=c_base.commit_id,
        task_succeeded=False,
    )

    # Guarded candidate eliminates thrash loops, verifies faster, and restores green tests
    fixed_steps = [
        baseline_steps[0],
        baseline_steps[1],
        baseline_steps[2],
        baseline_steps[3],
        TraceStep(
            step_index=4,
            tool_name="run_pytest",
            args_summary="target=tests/test_jwt.py",
            status="ok",
            tokens_used=220,
            cost_usd=0.00330,
            latency_ms=540,
        ),
    ]
    c_fix = db.commit_trace(
        task_id="fix-jwt-exp-validation",
        agent_model="agent-prompt-v2-guarded",
        prompt_summary="Verification-first prompt pinned after tracegit bisect",
        steps=fixed_steps,
        branch="feature/prompt-v2-guarded",
        parent_id=c_bug.commit_id,
        task_succeeded=True,
    )
    return db, c_base, c_bug, c_fix
