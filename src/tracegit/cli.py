"""Rich CLI & Drop-In MCP Server Launcher for tracegit."""

from __future__ import annotations

from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from tracegit.api.app import create_app
from tracegit.audit.ollama_traces import run_real_trace_ollama_audit
from tracegit.gate.regression_gate import bisect_first_failure, evaluate_regression_gate
from tracegit.mcp.server import TraceGitMCPServer
from tracegit.store.dag_store import TraceStore, seed_default_demo_store

app = typer.Typer(
    name="tracegit",
    help="tracegit — Git for AI Agent Execution Traces, C++20 Diff/Bisect, CI Gate & Claude Code MCP Server.",
    no_args_is_help=True,
)
console = Console()


@app.command("demo")
def cmd_demo() -> None:
    """Demonstrate SHA-256 Merkle trace commits, C++20 trajectory alignment diff & CI gate blocking."""
    store, c_base, c_bug, c_fix = seed_default_demo_store()
    diff_bug = store.diff_commits(c_base.commit_id, c_bug.commit_id)
    verdict_bug = evaluate_regression_gate(store, c_base.commit_id, c_bug.commit_id)
    verdict_fix = evaluate_regression_gate(store, c_base.commit_id, c_fix.commit_id)
    bisect_info = bisect_first_failure(store, c_base.commit_id, c_bug.commit_id)

    tbl = Table(title=f"tracegit Trajectory Diff & CI Gate ({diff_bug.backend})")
    tbl.add_column("Metric / Commit Pair", style="cyan")
    tbl.add_column("Verified Value", justify="right", style="green")
    tbl.add_row(
        "Baseline Commit (main)",
        f"{c_base.commit_id} ({len(c_base.steps)} steps, {c_base.total_tokens} tok)",
    )
    tbl.add_row(
        "Regressed Commit (prompt-v1)",
        f"{c_bug.commit_id} ({len(c_bug.steps)} steps, {c_bug.thrash.wasted_steps} thrash steps)",
    )
    tbl.add_row(
        "Repaired Commit (prompt-v2)",
        f"{c_fix.commit_id} ({len(c_fix.steps)} steps, {c_fix.total_tokens} tok)",
    )
    tbl.add_row(
        "C++20 Edit Distance & Similarity (base vs v1)",
        f"{diff_bug.edit_distance} ops ({diff_bug.similarity_pct}%)",
    )
    tbl.add_row(
        "First Divergence Bisect",
        f"step #{bisect_info['first_divergence_step_bad']} ({bisect_info['culprit_tool']})",
    )
    tbl.add_row(
        "CI Gate Verdict (base vs prompt-v1)",
        f"[red]{verdict_bug.verdict}[/] ({len(verdict_bug.reasons)} violation(s))",
    )
    tbl.add_row("CI Gate Verdict (base vs prompt-v2)", f"[green]{verdict_fix.verdict}[/]")
    console.print(tbl)


@app.command("eval-ollama")
def cmd_eval_ollama(
    model: str = typer.Option("qwen3.5:4b", "--model"),
    live_only: bool = typer.Option(False, "--live-only"),
) -> None:
    """Run Zero-Mock Live Ollama (`qwen3.5:4b`) Multi-Step Agent Trajectory & CI Gate Benchmark."""
    rep = run_real_trace_ollama_audit(model=model, allow_offline_replay=not live_only)
    tbl = Table(title=f"Zero-Mock Live Ollama Agent Trace Diff Audit ({rep.model_name})")
    tbl.add_column("Task ID", style="cyan")
    tbl.add_column("v1 Steps / Tok", justify="right")
    tbl.add_column("v2 Steps / Tok", justify="right")
    tbl.add_column("v1 Verified", justify="right")
    tbl.add_column("v2 Verified", justify="right")
    for o in rep.outcomes:
        tbl.add_row(
            o.task_id,
            f"{o.v1_steps} / {o.v1_tokens}",
            f"{o.v2_steps} / {o.v2_tokens}",
            "[green]✓[/]" if o.v1_verified else "[red]✗[/]",
            "[green]✓[/]" if o.v2_verified else "[red]✗[/]",
        )
    console.print(tbl)
    console.print(
        f"Summary: v1_verified={rep.v1_verified_pct:.1f}% -> v2_verified={rep.v2_verified_pct:.1f}% | "
        f"Token Savings: {rep.token_savings_pct:.1f}% | Thrash Steps Cut: {rep.thrash_steps_eliminated}"
    )


@app.command("mcp-stdio")
def cmd_mcp_stdio(
    db: Path = typer.Option(Path(".tracegit/tracegit.db"), "--db"),
) -> None:
    """Launch drop-in JSON-RPC 2.0 MCP server over stdin/stdout for Claude Code & Cursor."""
    store, _, _, _ = seed_default_demo_store(TraceStore(db))
    TraceGitMCPServer(store).serve_streams()


@app.command("serve")
def cmd_serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8100, "--port"),
) -> None:
    """Launch the tracegit FastAPI & React Diff Workbench server."""
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    app()
