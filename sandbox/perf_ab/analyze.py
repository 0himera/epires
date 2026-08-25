"""Pair and summarize external performance A/B trial records."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping


def _primary_score(record: Mapping[str, object]) -> float | None:
    if record.get("status") != "completed":
        return None
    grader = record.get("grader")
    if not isinstance(grader, Mapping):
        return None
    grade = grader.get("result")
    if not isinstance(grade, Mapping) or grade.get("status") != "ok":
        return None
    correctness = grade.get("correctness")
    if not isinstance(correctness, Mapping) or correctness.get("passed") is not True:
        return None
    score = grade.get("primary_score")
    if not isinstance(score, (int, float)):
        return None
    value = float(score)
    return value if math.isfinite(value) and value > 0.0 else None


def analyze_records(
    records: Iterable[Mapping[str, object]],
    minimum_pairs: int = 3,
    control_condition: str = "bare",
    treatment_condition: str = "epires",
) -> dict[str, object]:
    """Return a paired Epires/bare summary without imputing failed trials."""

    if minimum_pairs < 1:
        raise ValueError("minimum_pairs must be positive")
    if not control_condition or not treatment_condition or control_condition == treatment_condition:
        raise ValueError("control and treatment conditions must be distinct and non-empty")
    rows = list(records)
    statuses = Counter(str(row.get("status", "missing")) for row in rows)
    grouped: dict[tuple[str, str, str], dict[str, Mapping[str, object]]] = {}
    invalid_pair_ids = 0
    for row in rows:
        pair_id = row.get("pair_id")
        condition = str(row.get("condition", ""))
        if not pair_id or condition not in {control_condition, treatment_condition}:
            invalid_pair_ids += 1
            continue
        key = (str(row.get("task_id", "")), str(row.get("model", "")), str(pair_id))
        grouped.setdefault(key, {})[condition] = row

    pairs: list[dict[str, object]] = []
    exclusions: Counter[str] = Counter()
    for (task_id, model, pair_id), arms in sorted(grouped.items()):
        if set(arms) != {control_condition, treatment_condition}:
            exclusions["missing_arm"] += 1
            continue
        control = _primary_score(arms[control_condition])
        treatment = _primary_score(arms[treatment_condition])
        if control is None or treatment is None:
            exclusions["invalid_or_failed_arm"] += 1
            continue
        ratio = treatment / control
        pairs.append(
            {
                "task_id": task_id,
                "model": model,
                "pair_id": pair_id,
                "control_score": control,
                "treatment_score": treatment,
                "treatment_over_control": ratio,
                "paired_log2_ratio": math.log2(ratio),
            }
        )

    log_ratios = [float(pair["paired_log2_ratio"]) for pair in pairs]
    ratios = [float(pair["treatment_over_control"]) for pair in pairs]
    enough = len(pairs) >= minimum_pairs
    summary: dict[str, object] = {
        "valid_pairs": len(pairs),
        "minimum_pairs": minimum_pairs,
        "interpretation": "pilot_estimate" if enough else "smoke_only",
        "treatment_wins": sum(value > 0 for value in log_ratios),
        "ties": sum(value == 0 for value in log_ratios),
        "control_wins": sum(value < 0 for value in log_ratios),
        "geomean_treatment_over_control": (
            math.exp(statistics.fmean(math.log(value) for value in ratios)) if ratios else None
        ),
        "median_paired_log2_ratio": statistics.median(log_ratios) if log_ratios else None,
    }
    return {
        "schema_version": 1,
        "benchmark": "epires_external_perf_ab",
        "control_condition": control_condition,
        "treatment_condition": treatment_condition,
        "primary_analysis": "paired log-ratio of hidden geomean speedup",
        "records_seen": len(rows),
        "record_statuses": dict(sorted(statuses.items())),
        "records_without_valid_pair_identity": invalid_pair_ids,
        "excluded_pairs": dict(sorted(exclusions.items())),
        "summary": summary,
        "pairs": pairs,
        "caveat": "A smoke or pilot estimate is not a causal component attribution to VSA.",
    }


def load_records(root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(root.rglob("result.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            records.append(value)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, help="directory containing trial result.json files")
    parser.add_argument("--minimum-pairs", type=int, default=3)
    parser.add_argument("--control-condition", default="bare")
    parser.add_argument("--treatment-condition", default="epires")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = analyze_records(
        load_records(args.results),
        minimum_pairs=args.minimum_pairs,
        control_condition=args.control_condition,
        treatment_condition=args.treatment_condition,
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
