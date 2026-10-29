"""Offline detection metrics for evaluator-owned ground truth."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def calculate_detection_metrics(
    candidates: Iterable[Mapping[str, Any]],
) -> dict[str, int | float | None]:
    """Calculate confusion-matrix metrics from evaluator-only records."""
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    candidate_count = 0
    flagged_decision_count = 0

    for candidate in candidates:
        shell_company = candidate.get("shell_company")
        flagged = candidate.get("flagged")
        if not isinstance(shell_company, bool) or not isinstance(flagged, bool):
            raise ValueError("Evaluator candidate records require boolean labels and decisions.")
        candidate_count += 1
        flagged_decision_count += int(flagged)
        if shell_company and flagged:
            counts["tp"] += 1
        elif not shell_company and flagged:
            counts["fp"] += 1
        elif shell_company:
            counts["fn"] += 1
        else:
            counts["tn"] += 1

    precision = _safe_rate(counts["tp"], counts["tp"] + counts["fp"])
    recall = _safe_rate(counts["tp"], counts["tp"] + counts["fn"])
    accuracy = _safe_rate(counts["tp"] + counts["tn"], candidate_count)
    false_positive_rate = _safe_rate(counts["fp"], counts["fp"] + counts["tn"])
    f1 = _safe_rate(2 * counts["tp"], 2 * counts["tp"] + counts["fp"] + counts["fn"])
    return {
        "candidate_count": candidate_count,
        "flagged_decision_count": flagged_decision_count,
        **counts,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": false_positive_rate,
    }
