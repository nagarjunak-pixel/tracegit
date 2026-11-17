"""FastAPI backend serving TraceGit Commit DAG, C++20 Trajectory Diff, CI Gate, MCP Schema & UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from tracegit.audit.ollama_traces import default_trace_audit_path, run_real_trace_ollama_audit
from tracegit.gate.regression_gate import bisect_first_failure, evaluate_regression_gate
from tracegit.kernels.native_diff import active_backend_name
from tracegit.store.dag_store import TraceStore, seed_default_demo_store
from tracegit.types import GateVerdict, RealTraceAuditReport, TraceCommit, TraceDiffReport


class DiffRequest(BaseModel):
    base_commit_id: str
    candidate_commit_id: str


def create_app(db_path: Path | str = ":memory:") -> FastAPI:
    app = FastAPI(
        title="tracegit — Git for AI Agent Execution Traces, CI Gate & MCP Server",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    store, _, _, _ = seed_default_demo_store(TraceStore(db_path))

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "tracegit",
            "version": "1.0.0",
            "kernel_backend": active_backend_name(),
        }

    @app.get("/api/v1/commits", response_model=list[TraceCommit])
    def api_list_commits() -> list[TraceCommit]:
        return store.list_commits()

    @app.post("/api/v1/diff", response_model=TraceDiffReport)
    def api_diff(req: DiffRequest) -> TraceDiffReport:
        return store.diff_commits(req.base_commit_id, req.candidate_commit_id)

    @app.post("/api/v1/gate", response_model=GateVerdict)
    def api_gate(req: DiffRequest) -> GateVerdict:
        return evaluate_regression_gate(store, req.base_commit_id, req.candidate_commit_id)

    @app.get("/api/v1/bisect")
    def api_bisect(good_id: str, bad_id: str) -> dict[str, object]:
        return bisect_first_failure(store, good_id, bad_id)

    @app.get("/api/v1/audit/ollama", response_model=RealTraceAuditReport)
    def api_audit_ollama(refresh: bool = False) -> RealTraceAuditReport:
        art = default_trace_audit_path()
        if not refresh and art.exists():
            return RealTraceAuditReport.model_validate_json(art.read_text(encoding="utf-8"))
        return run_real_trace_ollama_audit(allow_offline_replay=True)

    ui_dist = Path(__file__).resolve().parents[3] / "ui" / "dist"
    assets_dir = ui_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", response_model=None)
    def serve_spa() -> FileResponse | HTMLResponse:
        index_html = ui_dist / "index.html"
        if index_html.exists():
            return FileResponse(str(index_html))
        return HTMLResponse(
            "<h1>tracegit API Online</h1><p>Build UI via <code>cd ui && npm run build</code>.</p>"
        )

    return app
