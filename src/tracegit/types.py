"""Strongly-typed Pydantic schemas for Trace Commits, Step Alignments, Loop Thrashing, CI Gates & Audits."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AlignOp(StrEnum):
    MATCH = "MATCH"
    SUBSTITUTE = "SUBSTITUTE"
    DELETE_BASE = "DELETE_BASE"
    INSERT_CANDIDATE = "INSERT_CANDIDATE"


class TraceStep(BaseModel):
    step_index: int
    tool_name: str
    args_summary: str
    status: str = "ok"
    tokens_used: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    latency_ms: float = Field(default=0.0, ge=0.0)


class LoopThrashSummary(BaseModel):
    loop_events: int
    wasted_steps: int
    wasted_tokens: int
    first_loop_step: int


class TraceCommit(BaseModel):
    commit_id: str
    parent_id: str | None = None
    branch: str = "main"
    task_id: str
    agent_model: str
    prompt_summary: str
    task_succeeded: bool = True
    step_merkle_root: str
    total_tokens: int
    total_cost_usd: float
    total_latency_ms: float
    thrash: LoopThrashSummary
    steps: list[TraceStep]


class AlignedStepPair(BaseModel):
    op: AlignOp
    base_step: TraceStep | None = None
    candidate_step: TraceStep | None = None


class TraceDiffReport(BaseModel):
    backend: str
    base_commit_id: str
    candidate_commit_id: str
    edit_distance: int
    similarity_pct: float
    first_divergence_step_base: int
    first_divergence_step_candidate: int
    token_delta: int
    cost_delta_usd: float
    latency_delta_ms: float
    alignment: list[AlignedStepPair]


class GatePolicyConfig(BaseModel):
    max_cost_increase_pct: float = 15.0
    max_latency_increase_pct: float = 25.0
    forbid_new_loop_thrash: bool = True
    require_task_success: bool = True
    max_edit_distance: int = 8


class GateVerdict(BaseModel):
    passed: bool
    verdict: str
    base_commit_id: str
    candidate_commit_id: str
    reasons: list[str]
    diff_summary: TraceDiffReport


class OllamaTraceComparison(BaseModel):
    task_id: str
    title: str
    v1_commit_id: str
    v2_commit_id: str
    v1_steps: int
    v2_steps: int
    v1_tokens: int
    v2_tokens: int
    v1_wasted_loop_steps: int
    v2_wasted_loop_steps: int
    v1_verified: bool
    v2_verified: bool
    edit_distance: int
    gate_v1_verdict: str
    gate_v2_verdict: str


class RealTraceAuditReport(BaseModel):
    model_name: str
    num_tasks: int
    v1_verified_pct: float
    v2_verified_pct: float
    token_savings_pct: float
    thrash_steps_eliminated: int
    outcomes: list[OllamaTraceComparison]
