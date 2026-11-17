import { useEffect, useState } from "react";

interface TraceStep {
  step_index: number;
  tool_name: string;
  args_summary: string;
  status: string;
  tokens_used: number;
}

interface LoopThrashSummary {
  loop_events: number;
  wasted_steps: number;
  wasted_tokens: number;
  first_loop_step: number;
}

interface TraceCommit {
  commit_id: string;
  branch: string;
  task_id: string;
  agent_model: string;
  task_succeeded: boolean;
  step_merkle_root: string;
  total_tokens: number;
  total_cost_usd: number;
  total_latency_ms: number;
  thrash: LoopThrashSummary;
  steps: TraceStep[];
}

interface AlignedStepPair {
  op: "MATCH" | "SUBSTITUTE" | "DELETE_BASE" | "INSERT_CANDIDATE";
  base_step: TraceStep | null;
  candidate_step: TraceStep | null;
}

interface TraceDiffReport {
  backend: string;
  edit_distance: number;
  similarity_pct: number;
  first_divergence_step_base: number;
  first_divergence_step_candidate: number;
  token_delta: number;
  cost_delta_usd: number;
  alignment: AlignedStepPair[];
}

interface GateVerdict {
  passed: boolean;
  verdict: string;
  reasons: string[];
  diff_summary: TraceDiffReport;
}

interface OllamaTraceComparison {
  task_id: string;
  v1_steps: number;
  v2_steps: number;
  v1_tokens: number;
  v2_tokens: number;
  v1_verified: boolean;
  v2_verified: boolean;
  edit_distance: number;
  gate_v2_verdict: string;
}

interface RealTraceAuditReport {
  model_name: string;
  num_tasks: number;
  v1_verified_pct: number;
  v2_verified_pct: number;
  token_savings_pct: number;
  thrash_steps_eliminated: number;
  outcomes: OllamaTraceComparison[];
}

export default function App() {
  const [commits, setCommits] = useState<TraceCommit[]>([]);
  const [candIdx, setCandIdx] = useState<number>(1);
  const [gate, setGate] = useState<GateVerdict | null>(null);
  const [audit, setAudit] = useState<RealTraceAuditReport | null>(null);

  const evaluatePair = async (list: TraceCommit[], targetIdx: number) => {
    if (list.length < 2) return;
    const baseId = list[0].commit_id;
    const candId = list[Math.min(targetIdx, list.length - 1)].commit_id;
    const res = await fetch("/api/v1/gate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_commit_id: baseId, candidate_commit_id: candId }),
    });
    setGate(await res.json());
  };

  useEffect(() => {
    fetch("/api/v1/commits")
      .then((r) => r.json())
      .then((list: TraceCommit[]) => {
        setCommits(list);
        void evaluatePair(list, 1);
      });
    fetch("/api/v1/audit/ollama")
      .then((r) => r.json())
      .then((d: RealTraceAuditReport) => setAudit(d));
  }, []);

  const candCommit = commits[candIdx];

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <h1>tracegit — Git for AI Agent Execution Traces, Diff/Bisect &amp; MCP Server</h1>
          <p className="subtitle">
            Content-Addressable SHA-256 Merkle DAG · Native C++20 Wagner-Fischer Step Alignment &amp; Loop-Thrash Detector · CI Pre-Ship Gate · Drop-In Claude Code / Cursor MCP Server
          </p>
        </div>
        <div className="pills">
          <span className="pill pill-amber">{gate?.diff_summary.backend ?? "c++20-native (clang++ -O3)"}</span>
          <span className="pill pill-cyan">stdio MCP Server Ready</span>
          <span className="pill pill-emerald">SHA-256 Merkle Verified</span>
        </div>
      </header>

      <section className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-label">Trace Commits (Merkle DAG)</div>
          <div className="kpi-value">{commits.length} Commits</div>
          <div className="kpi-sub">Claude Code JSONL + OpenAI / Ollama Importers</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">CI Regression Gate</div>
          <div className="kpi-value" style={{ color: gate?.passed ? "#10b981" : "#fb7185" }}>
            {gate ? gate.verdict : "..."}
          </div>
          <div className="kpi-sub">
            {gate
              ? `Edit Distance ${gate.diff_summary.edit_distance} · ${gate.diff_summary.similarity_pct}% Match`
              : "Loading..."}
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">Bisect First Divergence</div>
          <div className="kpi-value">
            {gate ? `Step #${Math.max(0, gate.diff_summary.first_divergence_step_candidate)}` : "..."}
          </div>
          <div className="kpi-sub">
            {candCommit
              ? `${candCommit.thrash.wasted_steps} Thrash Steps (${candCommit.thrash.wasted_tokens} tok wasted)`
              : "Loading..."}
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">Live Qwen-3.5-4B Trajectory Gate</div>
          <div className="kpi-value">
            {audit ? `${audit.v1_verified_pct.toFixed(0)}% → ${audit.v2_verified_pct.toFixed(0)}%` : "..."}
          </div>
          <div className="kpi-sub">
            {audit
              ? `${audit.token_savings_pct.toFixed(1)}% Token Cut · ${audit.thrash_steps_eliminated} Loops Eliminated`
              : "Loading..."}
          </div>
        </div>
      </section>

      <section className="main-grid">
        <div className="panel">
          <div className="panel-header">
            <h2>1. Side-by-Side C++20 Step Alignment Diff &amp; Bisect</h2>
            <div style={{ display: "flex", gap: 8 }}>
              <select
                value={candIdx}
                onChange={(e) => {
                  const idx = Number(e.target.value);
                  setCandIdx(idx);
                  void evaluatePair(commits, idx);
                }}
                style={{
                  background: "#090e1a",
                  color: "#f1f5f9",
                  border: "1px solid #334155",
                  borderRadius: 6,
                  padding: "4px 8px",
                  fontSize: "0.78rem",
                }}
              >
                <option value={1}>Compare main vs. prompt-v1-regression (BLOCK)</option>
                <option value={2}>Compare main vs. prompt-v2-guarded (PASS)</option>
              </select>
              <button className="btn" onClick={() => void evaluatePair(commits, candIdx)}>
                Run C++20 Diff &amp; Gate
              </button>
            </div>
          </div>

          {gate && (
            <>
              <div
                style={{
                  fontSize: "0.78rem",
                  marginBottom: 8,
                  color: gate.passed ? "#6ee7b7" : "#fda4af",
                }}
              >
                <strong>Gate Reasons:</strong> {gate.reasons.join(" | ")}
              </div>
              <table>
                <thead>
                  <tr>
                    <th>Align Op</th>
                    <th>Base (main)</th>
                    <th>Candidate Trace</th>
                    <th>Tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {gate.diff_summary.alignment.map((pair, i) => {
                    const cls =
                      pair.op === "MATCH"
                        ? "ok"
                        : pair.op === "INSERT_CANDIDATE"
                          ? "bad"
                          : "warn";
                    return (
                      <tr key={i}>
                        <td className={cls}>{pair.op}</td>
                        <td>
                          {pair.base_step
                            ? `#${pair.base_step.step_index} ${pair.base_step.tool_name}(${pair.base_step.args_summary})`
                            : "—"}
                        </td>
                        <td>
                          {pair.candidate_step
                            ? `#${pair.candidate_step.step_index} ${pair.candidate_step.tool_name}(${pair.candidate_step.args_summary})`
                            : "—"}
                        </td>
                        <td>{pair.candidate_step?.tokens_used ?? pair.base_step?.tokens_used ?? 0}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}
        </div>

        <div className="panel">
          <div className="panel-header">
            <h2>2. Trace Commit DAG &amp; Drop-In Claude Code / Cursor MCP</h2>
            <span className="pill pill-cyan">4 MCP Tools Over stdio</span>
          </div>

          <table>
            <thead>
              <tr>
                <th>Commit</th>
                <th>Branch</th>
                <th>Steps</th>
                <th>Tokens</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {commits.map((c) => (
                <tr key={c.commit_id}>
                  <td>{c.commit_id}</td>
                  <td>{c.branch}</td>
                  <td>{c.steps.length}</td>
                  <td>{c.total_tokens}</td>
                  <td className={c.task_succeeded ? "ok" : "bad"}>
                    {c.task_succeeded ? "OK ✓" : `FAIL (${c.thrash.loop_events} loops)`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div style={{ fontSize: "0.78rem", color: "#cbd5e1", marginTop: 12 }}>
            <strong>Add to <code>.mcp.json</code> in Claude Code / Cursor:</strong>
          </div>
          <pre className="mcp-box">{`{
  "mcpServers": {
    "tracegit": {
      "command": "uvx",
      "args": ["tracegit", "mcp-stdio", "--db", ".tracegit/tracegit.db"]
    }
  }
}`}</pre>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>3. Zero-Mock Live Ollama (qwen3.5:4b) Multi-Step Coding &amp; Infra Trace Audit</h2>
          <span className="pill pill-emerald">
            {audit
              ? `v1 Verified: ${audit.v1_verified_pct}% → v2 Guarded: ${audit.v2_verified_pct}% (${audit.token_savings_pct}% Fewer Tokens)`
              : "Loading..."}
          </span>
        </div>
        {audit && (
          <table>
            <thead>
              <tr>
                <th>Task ID</th>
                <th>v1 Unbounded (Steps / Tokens)</th>
                <th>v2 Guarded (Steps / Tokens)</th>
                <th>v1 Sound</th>
                <th>v2 Sound</th>
                <th>C++20 Edit Dist</th>
              </tr>
            </thead>
            <tbody>
              {audit.outcomes.map((o) => (
                <tr key={o.task_id}>
                  <td>{o.task_id}</td>
                  <td>
                    {o.v1_steps} steps / {o.v1_tokens} tok
                  </td>
                  <td className="ok">
                    {o.v2_steps} steps / {o.v2_tokens} tok
                  </td>
                  <td className={o.v1_verified ? "ok" : "bad"}>{o.v1_verified ? "PASS ✓" : "FAIL ✗"}</td>
                  <td className={o.v2_verified ? "ok" : "bad"}>{o.v2_verified ? "PASS ✓" : "FAIL ✗"}</td>
                  <td>{o.edit_distance}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
