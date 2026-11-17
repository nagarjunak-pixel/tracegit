"""Native C++20 trajectory alignment and loop-thrashing kernels."""

from tracegit.kernels.native_diff import (
    active_backend_name,
    align_step_hashes,
    detect_loop_thrash,
    hash_step_signature,
)

__all__ = [
    "active_backend_name",
    "align_step_hashes",
    "detect_loop_thrash",
    "hash_step_signature",
]
