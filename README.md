# tracegit — Git for AI Agent Execution Traces

[![CI](https://github.com/nagarjunak-pixel/tracegit/actions/workflows/ci.yml/badge.svg)](https://github.com/nagarjunak-pixel/tracegit/actions/workflows/ci.yml)
[![Python 3.13](https://img.shields.io/badge/python-3.13-3776AB.svg)](https://www.python.org/)
[![C++20 Native](https://img.shields.io/badge/C%2B%2B20-Wagner--Fischer%20%2B%20Thrash-00599C.svg)](csrc/tracegit_kernels.cpp)
[![MCP Ready](https://img.shields.io/badge/MCP-Claude%20Code%20%7C%20Cursor-8B5CF6.svg)](src/tracegit/mcp/server.py)
[![Coverage 97.55%](https://img.shields.io/badge/coverage-97.55%25-10B981.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-F59E0B.svg)](LICENSE)

> **Stop losing hours reading giant JSON logs when an AI agent loops, skips tests, or blows up token budgets.**
> `tracegit` brings **`git log`**, **`git diff`**, **`git bisect`**, a **CI pre-ship regression gate**, and a **drop-in Claude Code / Cursor `MCP` server** to local AI agent trajectories.

---

## Why Developers Install `tracegit`

1. **GitHub-PR-Style Step Alignment (`diff` + `bisect`)**: Powered by a native **`C++20` (`clang++ -O3`) Wagner–Fischer dynamic-programming aligner** over 64-bit `blake2b` step hashes (`MATCH`, `SUBSTITUTE`, `DELETE_BASE`, `INSERT_CANDIDATE`), pinpointing the **exact first divergent tool call** between a working run and a failing run.
2. **Runaway Retry Loop (`Loop-Thrash`) Detector**: Sliding-window n-gram (`p = 1, 2, 3`) cycle detector quantifies exact wasted steps and tokens when an agent gets stuck re-reading or re-grepping the same file.
3. **Content-Addressable SQLite + SHA-256 Merkle DAG**: Stores normalized **Claude Code JSONL**, **OpenAI/OpenRouter tool traces**, and local **Ollama** runs in `.tracegit/tracegit.db` with tamper-evident SHA-256 step Merkle roots—100% local, zero cloud lock-in.
4. **Drop-In `MCP` Server for Claude Code & Cursor**: Exposes 4 tools over `stdio` JSON-RPC 2.0 (`tracegit_list_commits`, `tracegit_diff_commits`, `tracegit_bisect_failure`, `tracegit_evaluate_gate`) so your coding agent can debug its own trajectory regressions.

---

## Drop-In Claude Code / Cursor `.mcp.json` Setup (30 Seconds)

Add this to `.mcp.json` in your repository (or run `tracegit mcp-stdio`):

```json
{
  "mcpServers": {
    "tracegit": {
      "command": "uvx",
      "args": ["tracegit", "mcp-stdio", "--db", ".tracegit/tracegit.db"]
    }
  }
}
```

---

## Verified Zero-Mock Benchmarks

Every metric below is reproducibly measured via CLI (`tracegit ...`) and `pytest` + `Hypothesis` (`97.55%` line coverage):

| Benchmark | Measured Result | Engineering Guarantee |
| :--- | :--- | :--- |
| **`C++20` Wagner-Fischer Diff** | Baseline `3aaf3dbc9382` (`5` steps) vs Regressed `bfba399ad924` (`8` steps): **`4` edit ops (`50.0%` match)** | Exact C++20-vs-Python parity & metric symmetry (`Hypothesis`-verified) |
| **`bisect` & Loop-Thrash** | First divergence: **`step #2 (read_file)`**; **`2` wasted thrash steps (`610` tok)** detected | CI Gate **BLOCK**s regressed candidate (`4` violations) & **PASS**es repaired `bf3386185537` |
| **Live `qwen3.5:4b` Audit** | 6 multi-step coding/K8s/CI agent tasks: **`v1: 0.0% -> v2 Guarded: 100.0%` verified (`20.6%` token cut)** | Zero duplicate retries; mandatory `read -> edit -> run_pytest` completion (`benchmarks/real_qwen_tracegit.json`) |

---

## Quickstart

```bash
# 1. Install Python 3.13 deps & compile C++20 alignment kernel
uv sync --python 3.13 --all-extras

# 2. Run strict lint, typing & Hypothesis test suite (97.55% coverage)
uv run ruff check src tests
uv run mypy src tests
uv run pytest --cov=tracegit --cov-report=term-missing --cov-fail-under=95

# 3. Run demo diff/gate + live Ollama trace audit
uv run tracegit demo
uv run tracegit eval-ollama

# 4. Build interactive Diff Workbench UI & launch server on :8100
cd ui && npm ci && npm run build && cd ..
uv run tracegit serve --host 127.0.0.1 --port 8100
```

---

## Author & License

Designed and engineered by **Nagarjuna Kamireddy** (`@nagarjunak-pixel`). Released under the [MIT License](LICENSE).
