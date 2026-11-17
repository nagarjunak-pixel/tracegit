#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <vector>

extern "C" {

// 1. Exact Dynamic-Programming Agent Trajectory Alignment (Wagner-Fischer over integer-interned step hashes)
// Alignment ops written backwards into rev_ops[0..out_ops_len-1], paired with rev_idx_a & rev_idx_b:
//   0 = MATCH, 1 = SUBSTITUTE, 2 = DELETE_FROM_A, 3 = INSERT_IN_B
int32_t tracegit_align_trajectories(
    const uint64_t* seq_a,
    int32_t len_a,
    const uint64_t* seq_b,
    int32_t len_b,
    int32_t* out_ops,
    int32_t* out_idx_a,
    int32_t* out_idx_b,
    int32_t max_ops_cap,
    int32_t* out_ops_len,
    int32_t* out_first_div_a,
    int32_t* out_first_div_b
) {
    const int32_t m = std::max<int32_t>(0, len_a);
    const int32_t n = std::max<int32_t>(0, len_b);
    const std::size_t cols = static_cast<std::size_t>(n + 1);
    std::vector<int32_t> dp(static_cast<std::size_t>(m + 1) * cols, 0);

    for (int32_t i = 0; i <= m; ++i) {
        dp[static_cast<std::size_t>(i) * cols] = i;
    }
    for (int32_t j = 0; j <= n; ++j) {
        dp[static_cast<std::size_t>(j)] = j;
    }

    for (int32_t i = 1; i <= m; ++i) {
        for (int32_t j = 1; j <= n; ++j) {
            const int32_t cost_sub = (seq_a[i - 1] == seq_b[j - 1]) ? 0 : 1;
            const int32_t d_sub = dp[static_cast<std::size_t>(i - 1) * cols + static_cast<std::size_t>(j - 1)] + cost_sub;
            const int32_t d_del = dp[static_cast<std::size_t>(i - 1) * cols + static_cast<std::size_t>(j)] + 1;
            const int32_t d_ins = dp[static_cast<std::size_t>(i) * cols + static_cast<std::size_t>(j - 1)] + 1;
            dp[static_cast<std::size_t>(i) * cols + static_cast<std::size_t>(j)] = std::min({d_sub, d_del, d_ins});
        }
    }

    // Backtrace deterministic alignment path (prefer MATCH/SUB -> INSERT_B -> DELETE_A on ties)
    std::vector<int32_t> rev_ops;
    std::vector<int32_t> rev_a;
    std::vector<int32_t> rev_b;
    rev_ops.reserve(static_cast<std::size_t>(m + n));

    int32_t i = m;
    int32_t j = n;
    while (i > 0 || j > 0) {
        const int32_t cur = dp[static_cast<std::size_t>(i) * cols + static_cast<std::size_t>(j)];
        if (i > 0 && j > 0) {
            const int32_t diag = dp[static_cast<std::size_t>(i - 1) * cols + static_cast<std::size_t>(j - 1)];
            const bool eq = (seq_a[i - 1] == seq_b[j - 1]);
            if (cur == diag + (eq ? 0 : 1)) {
                rev_ops.push_back(eq ? 0 : 1);
                rev_a.push_back(i - 1);
                rev_b.push_back(j - 1);
                --i;
                --j;
                continue;
            }
        }
        if (j > 0 && cur == dp[static_cast<std::size_t>(i) * cols + static_cast<std::size_t>(j - 1)] + 1) {
            rev_ops.push_back(3);  // INSERT_IN_B
            rev_a.push_back(-1);
            rev_b.push_back(j - 1);
            --j;
        } else {
            rev_ops.push_back(2);  // DELETE_FROM_A
            rev_a.push_back(i - 1);
            rev_b.push_back(-1);
            --i;
        }
    }

    const int32_t total = static_cast<int32_t>(rev_ops.size());
    const int32_t emit_len = std::min(total, max_ops_cap);
    *out_ops_len = emit_len;

    int32_t div_a = -1;
    int32_t div_b = -1;
    for (int32_t k = 0; k < emit_len; ++k) {
        const std::size_t src = static_cast<std::size_t>(total - 1 - k);
        out_ops[k] = rev_ops[src];
        out_idx_a[k] = rev_a[src];
        out_idx_b[k] = rev_b[src];
        if (div_a < 0 && div_b < 0 && out_ops[k] != 0) {
            div_a = out_idx_a[k];
            div_b = out_idx_b[k];
        }
    }
    *out_first_div_a = div_a;
    *out_first_div_b = div_b;
    return dp[static_cast<std::size_t>(m) * cols + static_cast<std::size_t>(n)];
}

// 2. Sliding-Window Agent Tool-Call Loop / Thrash Cycle Detector (contiguous period p in {1, 2, 3})
int32_t tracegit_detect_loop_thrash(
    const uint64_t* seq,
    const int32_t* step_tokens,
    int32_t len,
    int32_t* out_wasted_steps,
    int32_t* out_wasted_tokens,
    int32_t* out_first_loop_start
) {
    std::vector<uint8_t> wasted(static_cast<std::size_t>(std::max<int32_t>(0, len)), 0);
    int32_t loop_events = 0;
    int32_t first_start = -1;

    for (int32_t i = 0; i < len; ++i) {
        if (wasted[static_cast<std::size_t>(i)] != 0) {
            continue;
        }
        bool matched_here = false;
        for (int32_t p = 1; p <= 3; ++p) {
            if (i + 2 * p <= len) {
                bool same = true;
                for (int32_t off = 0; off < p; ++off) {
                    if (seq[i + off] != seq[i + p + off]) {
                        same = false;
                        break;
                    }
                }
                if (same) {
                    ++loop_events;
                    if (first_start < 0) {
                        first_start = i + p;
                    }
                    // Mark repeated contiguous periods beyond the initial execution as thrash
                    int32_t pos = i + p;
                    while (pos + p <= len) {
                        bool rep = true;
                        for (int32_t off = 0; off < p; ++off) {
                            if (seq[i + off] != seq[pos + off]) {
                                rep = false;
                                break;
                            }
                        }
                        if (!rep) {
                            break;
                        }
                        for (int32_t off = 0; off < p; ++off) {
                            wasted[static_cast<std::size_t>(pos + off)] = 1;
                        }
                        pos += p;
                    }
                    matched_here = true;
                    break;
                }
            }
        }
        (void)matched_here;
    }

    int32_t w_steps = 0;
    int32_t w_toks = 0;
    for (int32_t i = 0; i < len; ++i) {
        if (wasted[static_cast<std::size_t>(i)] != 0) {
            ++w_steps;
            if (step_tokens != nullptr) {
                w_toks += step_tokens[i];
            }
        }
    }
    *out_wasted_steps = w_steps;
    *out_wasted_tokens = w_toks;
    *out_first_loop_start = first_start;
    return loop_events;
}

}  // extern "C"
