"""Unit & Hypothesis tests for C++20 Trajectory Alignment, Loop-Thrash Detection & Merkle DAG Store."""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tracegit.kernels.native_diff import (
    active_backend_name,
    align_step_hashes,
    detect_loop_thrash,
    hash_step_signature,
    python_align_step_hashes,
    python_detect_loop_thrash,
)
from tracegit.store.dag_store import (
    TraceStore,
    compute_step_merkle_root,
    import_claude_code_jsonl,
    import_openai_tool_trace,
    seed_default_demo_store,
)
from tracegit.types import AlignOp, TraceStep


@settings(max_examples=35, deadline=None)
@given(
    seq_a=st.lists(st.integers(min_value=1, max_value=6), min_size=0, max_size=14),
    seq_b=st.lists(st.integers(min_value=1, max_value=6), min_size=0, max_size=14),
)
def test_hypothesis_cpp20_alignment_matches_python_and_obeys_metric_axioms(
    seq_a: list[int], seq_b: list[int]
) -> None:
    dist_c, ops_c, div_a_c, div_b_c = align_step_hashes(seq_a, seq_b)
    dist_p, ops_p, div_a_p, div_b_p = python_align_step_hashes(seq_a, seq_b)

    assert dist_c == dist_p
    assert div_a_c == div_a_p
    assert div_b_c == div_b_p
    assert ops_c == ops_p

    # Exact symmetry: edit_distance(A, B) == edit_distance(B, A)
    dist_rev, _, _, _ = align_step_hashes(seq_b, seq_a)
    assert dist_c == dist_rev

    # Exact edit count equals number of non-MATCH ops emitted
    assert dist_c == sum(1 for op, _, _ in ops_c if op != AlignOp.MATCH)
    if seq_a == seq_b:
        assert dist_c == 0
        assert div_a_c == -1 and div_b_c == -1


@settings(max_examples=25, deadline=None)
@given(tools=st.lists(st.integers(min_value=0, max_value=3), min_size=0, max_size=16))
def test_hypothesis_cpp20_loop_thrash_parity(tools: list[int]) -> None:
    steps = [
        TraceStep(step_index=i, tool_name=f"tool_{t}", args_summary="x", tokens_used=50 + i)
        for i, t in enumerate(tools)
    ]
    res_c = detect_loop_thrash(steps)
    res_p = python_detect_loop_thrash(steps)
    assert res_c == res_p
    assert 0 <= res_c.wasted_steps <= len(steps)


def test_merkle_store_importers_and_demo_seed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert compute_step_merkle_root([])
    assert "c++20" in active_backend_name() or "python" in active_backend_name()

    # Deterministic step hash ignores token/latency jitter while locking tool+status+args
    s1 = TraceStep(step_index=0, tool_name="read_file", args_summary="a.py", tokens_used=100)
    s2 = TraceStep(step_index=0, tool_name="read_file", args_summary="a.py", tokens_used=999)
    assert hash_step_signature(s1) == hash_step_signature(s2)

    jsonl = "\n".join(
        [
            "",
            json.dumps(
                {
                    "message": {
                        "usage": {"output_tokens": 88},
                        "content": [
                            {"type": "tool_use", "name": "read_file", "input": {"path": "x.py"}}
                        ],
                    }
                }
            ),
        ]
    )
    cc_steps = import_claude_code_jsonl(jsonl)
    assert len(cc_steps) == 1 and cc_steps[0].tool_name == "read_file"

    oai_steps = import_openai_tool_trace(
        {
            "tool_calls": [
                {"function": {"name": "edit_file", "arguments": '{"path": "x.py"}'}},
                {"function": {"name": "run_pytest", "arguments": "raw-arg-str"}},
            ]
        }
    )
    assert len(oai_steps) == 2

    db_file = tmp_path / "trace.db"
    store, c_base, c_bug, c_fix = seed_default_demo_store(TraceStore(db_file))
    # Calling seed again returns already persisted commits cleanly
    store2, b2, _, _ = seed_default_demo_store(store)
    assert b2.commit_id == c_base.commit_id
    with pytest.raises(KeyError, match="not found"):
        store2.get_commit("nonexistent")
    diff = store2.diff_commits(c_base.commit_id, c_bug.commit_id)
    assert diff.edit_distance >= 3
    assert c_bug.thrash.loop_events >= 1
    assert c_fix.task_succeeded is True
    store2.close()
