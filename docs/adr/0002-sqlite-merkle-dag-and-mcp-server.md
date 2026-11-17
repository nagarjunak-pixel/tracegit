# ADR 0002: Content-Addressable SHA-256 Merkle DAG & Zero-Dependency `stdio` MCP Server

- **Status**: Accepted
- **Context**: Coding-agent harnesses (`Claude Code`, `Cursor`, CI runners) need local-first trace diffing and failure bisection without SaaS vendor lock-in or external dependencies.
- **Decision**: Persist normalized execution trajectories in local SQLite keyed by SHA-256 Merkle commit roots (`commit_id`) and expose `tracegit_list_commits`, `tracegit_diff_commits`, `tracegit_bisect_failure`, and `tracegit_evaluate_gate` directly via JSON-RPC 2.0 `stdio` MCP (`tracegit mcp-stdio`).
- **Consequences**: Developers drop a 6-line `.mcp.json` block into any repo and immediately empower coding agents to debug and gate their own trace regressions locally.
