# ADR 0001: Native C++20 Wagner-Fischer Step Alignment & Sliding-Window Loop-Thrash Detector

- **Status**: Accepted
- **Context**: Agent observability dashboards dump unindexed raw JSON logs, making it hard for engineers to pinpoint where a prompt regression diverged or quantify retry loops.
- **Decision**: Canonicalize each `(tool_name, status, args_summary)` step with 64-bit `blake2b` digests and run exact Wagner-Fischer dynamic-programming edit alignment + sliding-window n-gram (`p=1..3`) thrash detection in `csrc/tracegit_kernels.cpp` (`clang++ -O3 -std=c++20`) with exact Python fallback.
- **Consequences**: Provides deterministic `first_divergence` bisect indices and exact loop-token waste counts verified with `Hypothesis` metric axioms (`0` C++20-vs-Python discrepancies).
