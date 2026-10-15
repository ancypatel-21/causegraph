"""Calibration metrics (spec section 9.3): "Whether confidence tracks
empirical correctness (ECE/Brier score)." Pure functions over
(confidence, was_correct) pairs -- no knowledge of scenarios, runs, or
the benchmark harness. See benchmark/evaluator/calibration_runner.py for
how the pairs actually get collected (repeated runs across seeds and
scenarios).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CalibrationResult:
    brier_score: float
    expected_calibration_error: float
    n_samples: int
    n_bins: int
    bin_details: list[dict] = field(default_factory=list)


def brier_score(pairs: list[tuple[float, bool]]) -> float:
    """Mean squared error between stated confidence and 0/1 correctness.
    0 is perfect, 1 is maximally wrong; always defined, unlike ECE, which
    needs non-empty bins."""
    if not pairs:
        return float("nan")
    return sum((confidence - float(correct)) ** 2 for confidence, correct in pairs) / len(pairs)


def expected_calibration_error(pairs: list[tuple[float, bool]], n_bins: int = 5) -> CalibrationResult:
    """Buckets predictions by confidence and compares each bucket's mean
    confidence to its actual accuracy. `n_bins` defaults low (5, not the
    usual 10-15) because this project has few samples -- finer bins would
    mostly be empty and the number would be noise, not signal. Report
    `n_samples` alongside any ECE value for exactly this reason.
    """
    if not pairs:
        return CalibrationResult(
            brier_score=float("nan"),
            expected_calibration_error=float("nan"),
            n_samples=0,
            n_bins=n_bins,
        )

    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for confidence, correct in pairs:
        idx = min(max(int(confidence * n_bins), 0), n_bins - 1)
        buckets[idx].append((confidence, correct))

    n = len(pairs)
    ece = 0.0
    bin_details = []
    for i, bucket in enumerate(buckets):
        detail = {"bin": i, "range": [i / n_bins, (i + 1) / n_bins], "n": len(bucket)}
        if bucket:
            avg_confidence = sum(c for c, _ in bucket) / len(bucket)
            accuracy = sum(1 for _, correct in bucket if correct) / len(bucket)
            ece += (len(bucket) / n) * abs(avg_confidence - accuracy)
            detail["avg_confidence"] = avg_confidence
            detail["accuracy"] = accuracy
        bin_details.append(detail)

    return CalibrationResult(
        brier_score=brier_score(pairs),
        expected_calibration_error=ece,
        n_samples=n,
        n_bins=n_bins,
        bin_details=bin_details,
    )
