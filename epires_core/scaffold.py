"""Automated Experiment Harness & Template Scaffolder for Epires."""

from __future__ import annotations
import re


def generate_experiment_scaffold(
    hypothesis_id: str,
    title: str = "",
    mechanism: str = "",
    falsification_criteria: str = "",
    primary_metric: str = "RMSLE",
) -> str:
    """Generates a standardized Python experiment runner script."""
    hid_clean = re.sub(r"[^a-zA-Z0-9_]", "_", hypothesis_id.lower())

    return f'''#!/usr/bin/env python3
"""Automated Experiment Evaluator for [{hypothesis_id}]: {title}
Mechanism: {mechanism}
Falsification Criteria: {falsification_criteria}
"""

from __future__ import annotations
import argparse
import json
import time
import os
from pathlib import Path
import numpy as np


def paired_bootstrap_ci(
    baseline_scores: np.ndarray,
    candidate_scores: np.ndarray,
    n_resamples: int = 2000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Calculates paired candidate-minus-baseline delta and its bootstrap confidence interval."""
    rng = np.random.default_rng(seed)
    deltas = candidate_scores - baseline_scores
    observed_mean = float(np.mean(deltas))

    indices = rng.integers(0, len(deltas), size=(n_resamples, len(deltas)))
    boot_means = np.mean(deltas[indices], axis=1)

    alpha = (1.0 - confidence) / 2.0
    lower = float(np.percentile(boot_means, 100 * alpha))
    upper = float(np.percentile(boot_means, 100 * (1.0 - alpha)))
    return observed_mean, lower, upper


def main():
    parser = argparse.ArgumentParser(description="Experiment runner for {hypothesis_id}")
    parser.add_argument("--output", "-o", default="artifacts/metrics/{hid_clean}.json", help="Path to output JSON")
    parser.add_argument("--n-samples", type=int, default=1000, help="Number of evaluation samples")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    start_time = time.perf_counter()

    # =========================================================================
    # TODO: Implement candidate model scoring & baseline comparison below
    # =========================================================================
    rng = np.random.default_rng(args.seed)
    baseline_losses = rng.normal(loc=1.6885, scale=0.1, size=args.n_samples)
    # Example: candidate evaluation
    candidate_losses = baseline_losses - rng.normal(loc=0.0040, scale=0.02, size=args.n_samples)

    # Compute paired bootstrap statistics
    delta_mean, ci_lower, ci_upper = paired_bootstrap_ci(
        baseline_losses, candidate_losses, n_resamples=2000, confidence=0.95, seed=args.seed
    )

    elapsed_sec = time.perf_counter() - start_time

    # Standardized Epires Artifact Output
    payload = {{
        "hypothesis_id": "{hypothesis_id}",
        "title": "{title}",
        "metric_name": "{primary_metric}",
        "baseline_metric": float(np.mean(baseline_losses)),
        "candidate_metric": float(np.mean(candidate_losses)),
        "delta_vs_baseline": delta_mean,
        "ci_95_lower": ci_lower,
        "ci_95_upper": ci_upper,
        "n_samples": args.n_samples,
        "seed": args.seed,
        "falsification_criteria": "{falsification_criteria}",
        "resource_usage": {{
            "elapsed_seconds": round(elapsed_sec, 3),
        }},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }}

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[+] Saved experiment artifact to: {{out_path}}")
    print(f"    Delta vs Baseline: {{delta_mean:+.6f}} [95% CI: {{ci_lower:.6f}}, {{ci_upper:.6f}}]")


if __name__ == "__main__":
    main()
'''
