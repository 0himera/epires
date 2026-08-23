"""Real multi-model evaluation benchmark for Epires via Opencode."""

from __future__ import annotations

import sys
import time
from typing import List, Dict, Any

from sandbox.run_eval import run_one

MODELS = [
    "opencode/nemotron-3-ultra-free",
    "opencode/hy3-free",
    "opencode/mimo-v2.5-free",
    "opencode/x-preview-f-free",
]

BENCHMARK_SCENARIOS = [
    "planted_bug",
    "cascade_quarantine",
    "inconclusive_ci",
    "vacuous_confirm",
    "selection_bias",
    "goal_metric_mismatch",
    "commitment_trap",
    "conflicting",
]


import concurrent.futures


def _run_task(task_args: tuple[int, int, str, str, str]) -> Dict[str, Any]:
    idx, total, model, scenario, variant = task_args
    t0 = time.perf_counter()
    try:
        res = run_one(scenario=scenario, variant=variant, agent_kind="opencode", model=model)
        elapsed = time.perf_counter() - t0
        res["model"] = model
        res["elapsed_seconds"] = round(elapsed, 2)
        success_icon = "✅" if res.get("success") else "❌"
        model_name = model.split("/")[-1]
        print(
            f"  [{idx:02d}/{total:02d}] {model_name:<22} | {scenario:<20} | {variant:<10} | "
            f"{success_icon} Success: {str(res.get('success')):<5} | Score: {res.get('score', 0):.2f} | {elapsed:.1f}s"
        )
        return res
    except Exception as e:
        elapsed = time.perf_counter() - t0
        model_name = model.split("/")[-1]
        print(
            f"  [{idx:02d}/{total:02d}] {model_name:<22} | {scenario:<20} | {variant:<10} | ⚠️ ERROR: {e} ({elapsed:.1f}s)"
        )
        return {
            "scenario": scenario,
            "variant": variant,
            "model": model,
            "success": False,
            "score": 0.0,
            "error": str(e),
            "elapsed_seconds": round(elapsed, 2),
        }


def run_benchmark(
    models: List[str] = MODELS,
    scenarios: List[str] = BENCHMARK_SCENARIOS,
    variants: List[str] = ["protocol", "baseline"],
    max_workers: int = 4,
) -> List[Dict[str, Any]]:
    tasks = []
    total = len(models) * len(scenarios) * len(variants)
    idx = 0

    for model in models:
        for scenario in scenarios:
            for variant in variants:
                idx += 1
                tasks.append((idx, total, model, scenario, variant))

    print(
        f"[*] Starting Parallel Real Agent Benchmark ({len(models)} models, {len(scenarios)} scenarios, {len(variants)} variants, workers={max_workers})"
    )
    print("=" * 105)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_run_task, t) for t in tasks]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    return results


def print_summary_table(results: List[Dict[str, Any]]) -> str:
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append("📊 REAL AGENT MULTI-MODEL BENCHMARK RESULTS")
    lines.append("=" * 80)
    lines.append(
        f"{'Model':<25} | {'Variant':<10} | {'Passed':<8} | {'Total':<6} | {'Accuracy':<10} | {'Avg Score':<10}"
    )
    lines.append("-" * 80)

    by_model_variant: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for r in results:
        key = (r["model"].split("/")[-1], r["variant"])
        by_model_variant.setdefault(key, []).append(r)

    for (model, variant), runs in sorted(by_model_variant.items()):
        total = len(runs)
        passed = sum(1 for r in runs if r.get("success"))
        acc = (passed / total * 100.0) if total else 0.0
        avg_score = (sum(r.get("score", 0.0) for r in runs) / total) if total else 0.0
        lines.append(f"{model:<25} | {variant:<10} | {passed:<8} | {total:<6} | {acc:>8.1f}% | {avg_score:>9.2f}")

    lines.append("=" * 80)
    summary_text = "\n".join(lines)
    print(summary_text)
    return summary_text


if __name__ == "__main__":
    # Allow filtering via CLI
    models_to_run = [m for m in sys.argv[1:] if m.startswith("opencode/")] or MODELS
    scenarios_to_run = [s for s in sys.argv[1:] if not s.startswith("opencode/")] or BENCHMARK_SCENARIOS
    results = run_benchmark(models=models_to_run, scenarios=scenarios_to_run)
    print_summary_table(results)
