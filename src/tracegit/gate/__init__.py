"""CI regression gate and bisect evaluator for agent traces."""

from tracegit.gate.regression_gate import bisect_first_failure, evaluate_regression_gate

__all__ = ["bisect_first_failure", "evaluate_regression_gate"]
