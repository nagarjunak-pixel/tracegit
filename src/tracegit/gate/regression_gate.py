"""CI Pre-Ship Regression Gate & Trajectory Bisect Root-Cause Locator."""

from __future__ import annotations

from tracegit.store.dag_store import TraceStore
from tracegit.types import GatePolicyConfig, GateVerdict


def evaluate_regression_gate(
    store: TraceStore,
    base_commit_id: str,
    candidate_commit_id: str,
    policy: GatePolicyConfig | None = None,
) -> GateVerdict:
    cfg = policy or GatePolicyConfig()
    base = store.get_commit(base_commit_id)
    cand = store.get_commit(candidate_commit_id)
    diff = store.diff_commits(base_commit_id, candidate_commit_id)

    reasons: list[str] = []
    if cfg.require_task_success and not cand.task_succeeded:
        reasons.append(f"Candidate {cand.commit_id} failed task completion.")

    if cfg.forbid_new_loop_thrash and cand.thrash.loop_events > base.thrash.loop_events:
        reasons.append(
            f"Introduced {cand.thrash.loop_events} loop thrash event(s) wasting "
            f"{cand.thrash.wasted_steps} steps / {cand.thrash.wasted_tokens} tokens "
            f"(first loop at step #{cand.thrash.first_loop_step})."
        )

    base_cost = max(1e-9, base.total_cost_usd)
    cost_pct = ((cand.total_cost_usd - base.total_cost_usd) / base_cost) * 100.0
    if cost_pct > cfg.max_cost_increase_pct:
        reasons.append(
            f"Cost regression +{cost_pct:.1f}% exceeds max budget +{cfg.max_cost_increase_pct:.1f}%."
        )

    base_lat = max(1e-9, base.total_latency_ms)
    lat_pct = ((cand.total_latency_ms - base.total_latency_ms) / base_lat) * 100.0
    if lat_pct > cfg.max_latency_increase_pct:
        reasons.append(
            f"Latency regression +{lat_pct:.1f}% exceeds max budget +{cfg.max_latency_increase_pct:.1f}%."
        )

    if diff.edit_distance > cfg.max_edit_distance:
        reasons.append(
            f"Trajectory drift edit_distance={diff.edit_distance} exceeds max allowed {cfg.max_edit_distance}."
        )

    if not reasons:
        reasons.append(
            f"All guardrails passed (similarity={diff.similarity_pct:.1f}%, edit_distance={diff.edit_distance}, loop_events={cand.thrash.loop_events})."
        )

    passed = len(reasons) == 1 and reasons[0].startswith("All guardrails passed")
    return GateVerdict(
        passed=passed,
        verdict="PASS" if passed else "BLOCK",
        base_commit_id=base.commit_id,
        candidate_commit_id=cand.commit_id,
        reasons=reasons,
        diff_summary=diff,
    )


def bisect_first_failure(
    store: TraceStore, good_commit_id: str, bad_commit_id: str
) -> dict[str, object]:
    """Identify the exact divergence step and culprit tool between a passing trace and a regressed trace."""
    bad = store.get_commit(bad_commit_id)
    diff = store.diff_commits(good_commit_id, bad_commit_id)
    div_b = diff.first_divergence_step_candidate
    culprit = (
        bad.steps[div_b]
        if 0 <= div_b < len(bad.steps)
        else (
            bad.steps[diff.first_divergence_step_base]
            if 0 <= diff.first_divergence_step_base < len(bad.steps)
            else None
        )
    )
    return {
        "good_commit_id": good_commit_id,
        "bad_commit_id": bad_commit_id,
        "edit_distance": diff.edit_distance,
        "first_divergence_step_good": diff.first_divergence_step_base,
        "first_divergence_step_bad": diff.first_divergence_step_candidate,
        "first_loop_step": bad.thrash.first_loop_step,
        "culprit_tool": culprit.tool_name if culprit else "none",
        "culprit_args": culprit.args_summary if culprit else "",
    }
