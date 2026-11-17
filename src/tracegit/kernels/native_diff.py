"""Native C++20 bridge (`clang++ -O3`) for Wagner-Fischer Trajectory Alignment & Loop-Thrash Detection."""

from __future__ import annotations

import ctypes
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from tracegit.types import AlignOp, LoopThrashSummary, TraceStep


def _compile_native_lib() -> tuple[ctypes.CDLL | None, str]:
    src_path = Path(__file__).resolve().parents[3] / "csrc" / "tracegit_kernels.cpp"
    clang = shutil.which("clang++") or shutil.which("g++")
    if not src_path.exists() or clang is None:
        return None, "python-fallback"

    digest = hashlib.sha256(src_path.read_bytes()).hexdigest()[:16]
    out_dir = Path(tempfile.gettempdir()) / "tracegit_native_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = ".dylib" if Path("/System/Library").exists() else ".so"
    lib_path = out_dir / f"libtracegit_kernels_{digest}{ext}"

    if not lib_path.exists():
        cmd = [clang, "-O3", "-std=c++20", "-shared", "-fPIC", str(src_path), "-o", str(lib_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return None, "python-fallback"

    lib = ctypes.CDLL(str(lib_path))
    lib.tracegit_align_trajectories.argtypes = [
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_int32,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.c_int32,
        ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_int32),
        ctypes.c_int32,
        ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_int32),
    ]
    lib.tracegit_align_trajectories.restype = ctypes.c_int32

    lib.tracegit_detect_loop_thrash.argtypes = [
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_int32),
        ctypes.c_int32,
        ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_int32),
    ]
    lib.tracegit_detect_loop_thrash.restype = ctypes.c_int32
    return lib, "c++20-native (clang++ -O3)"


_NATIVE_LIB, _BACKEND_NAME = _compile_native_lib()

_OP_MAP: dict[int, AlignOp] = {
    0: AlignOp.MATCH,
    1: AlignOp.SUBSTITUTE,
    2: AlignOp.DELETE_BASE,
    3: AlignOp.INSERT_CANDIDATE,
}


def active_backend_name() -> str:
    return _BACKEND_NAME


def hash_step_signature(step: TraceStep) -> int:
    payload = f"{step.tool_name}|{step.status}|{step.args_summary}".encode()
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "little")


def python_align_step_hashes(
    seq_a: list[int], seq_b: list[int]
) -> tuple[int, list[tuple[AlignOp, int, int]], int, int]:
    m, n = len(seq_a), len(seq_b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if seq_a[i - 1] == seq_b[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j - 1] + cost, dp[i - 1][j] + 1, dp[i][j - 1] + 1)

    rev: list[tuple[AlignOp, int, int]] = []
    i, j = m, n
    while i > 0 or j > 0:
        cur = dp[i][j]
        if i > 0 and j > 0:
            eq = seq_a[i - 1] == seq_b[j - 1]
            if cur == dp[i - 1][j - 1] + (0 if eq else 1):
                rev.append((AlignOp.MATCH if eq else AlignOp.SUBSTITUTE, i - 1, j - 1))
                i -= 1
                j -= 1
                continue
        if j > 0 and cur == dp[i][j - 1] + 1:
            rev.append((AlignOp.INSERT_CANDIDATE, -1, j - 1))
            j -= 1
        else:
            rev.append((AlignOp.DELETE_BASE, i - 1, -1))
            i -= 1

    rev.reverse()
    div_a, div_b = -1, -1
    for op, ia, ib in rev:
        if op != AlignOp.MATCH:
            div_a, div_b = ia, ib
            break
    return dp[m][n], rev, div_a, div_b


def align_step_hashes(
    seq_a: list[int], seq_b: list[int], *, force_python: bool = False
) -> tuple[int, list[tuple[AlignOp, int, int]], int, int]:
    if _NATIVE_LIB is None or force_python:
        return python_align_step_hashes(seq_a, seq_b)

    m, n = len(seq_a), len(seq_b)
    cap = max(1, m + n + 4)
    arr_a = (ctypes.c_uint64 * max(1, m))(*(seq_a or [0]))
    arr_b = (ctypes.c_uint64 * max(1, n))(*(seq_b or [0]))
    out_ops = (ctypes.c_int32 * cap)()
    out_ia = (ctypes.c_int32 * cap)()
    out_ib = (ctypes.c_int32 * cap)()
    out_len = ctypes.c_int32(0)
    out_da = ctypes.c_int32(-1)
    out_db = ctypes.c_int32(-1)

    dist = int(
        _NATIVE_LIB.tracegit_align_trajectories(
            arr_a,
            m,
            arr_b,
            n,
            out_ops,
            out_ia,
            out_ib,
            cap,
            ctypes.byref(out_len),
            ctypes.byref(out_da),
            ctypes.byref(out_db),
        )
    )
    ops_list = [
        (_OP_MAP[int(out_ops[k])], int(out_ia[k]), int(out_ib[k])) for k in range(out_len.value)
    ]
    return dist, ops_list, int(out_da.value), int(out_db.value)


def python_detect_loop_thrash(steps: list[TraceStep]) -> LoopThrashSummary:
    seq = [hash_step_signature(s) for s in steps]
    n = len(seq)
    wasted = [False] * n
    events = 0
    first_start = -1
    for i in range(n):
        if wasted[i]:
            continue
        for p in (1, 2, 3):
            if i + 2 * p <= n and seq[i : i + p] == seq[i + p : i + 2 * p]:
                events += 1
                if first_start < 0:
                    first_start = i + p
                pos = i + p
                while pos + p <= n and seq[i : i + p] == seq[pos : pos + p]:
                    for off in range(p):
                        wasted[pos + off] = True
                    pos += p
                break
    return LoopThrashSummary(
        loop_events=events,
        wasted_steps=sum(1 for w in wasted if w),
        wasted_tokens=sum(s.tokens_used for s, w in zip(steps, wasted, strict=True) if w),
        first_loop_step=first_start,
    )


def detect_loop_thrash(steps: list[TraceStep], *, force_python: bool = False) -> LoopThrashSummary:
    if not steps or _NATIVE_LIB is None or force_python:
        return python_detect_loop_thrash(steps)

    seq = [hash_step_signature(s) for s in steps]
    toks = [s.tokens_used for s in steps]
    n = len(steps)
    arr_seq = (ctypes.c_uint64 * n)(*seq)
    arr_tok = (ctypes.c_int32 * n)(*toks)
    w_steps = ctypes.c_int32(0)
    w_toks = ctypes.c_int32(0)
    first_loop = ctypes.c_int32(-1)
    events = int(
        _NATIVE_LIB.tracegit_detect_loop_thrash(
            arr_seq,
            arr_tok,
            n,
            ctypes.byref(w_steps),
            ctypes.byref(w_toks),
            ctypes.byref(first_loop),
        )
    )
    return LoopThrashSummary(
        loop_events=events,
        wasted_steps=int(w_steps.value),
        wasted_tokens=int(w_toks.value),
        first_loop_step=int(first_loop.value),
    )
