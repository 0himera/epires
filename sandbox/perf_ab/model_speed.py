"""Small end-to-end latency smoke test for OpenCode models."""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import statistics
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .runner import Condition, RunConfig, _execute, _isolated_env


DEFAULT_FREE_MODELS = (
    "opencode/hy3-free",
    "opencode/mimo-v2.5-free",
    "opencode/muse-spark-1.2-contributor-free",
    "opencode/nemotron-3-ultra-free",
    "opencode/nemotron-3.5-lightning-free",
    "opencode/x-preview-f-free",
)
PROMPT = (
    "Do not use tools. Reply with one short paragraph of exactly 80 English words "
    "explaining why hidden tests matter in performance optimization."
)


def _parse_jsonl(stdout: str) -> dict[str, Any]:
    text_parts: list[str] = []
    token_totals = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0}
    step_started_ms: int | None = None
    first_text_ms: int | None = None
    final_event_ms: int | None = None
    parse_errors = 0
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        timestamp = event.get("timestamp")
        if isinstance(timestamp, int):
            final_event_ms = timestamp
        kind = event.get("type")
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        if kind == "step_start" and step_started_ms is None and isinstance(timestamp, int):
            step_started_ms = timestamp
        if kind == "text":
            value = part.get("text")
            if isinstance(value, str):
                text_parts.append(value)
            if first_text_ms is None and isinstance(timestamp, int):
                first_text_ms = timestamp
        if kind == "step_finish":
            tokens = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
            token_totals["input"] += int(tokens.get("input", 0) or 0)
            token_totals["output"] += int(tokens.get("output", 0) or 0)
            token_totals["reasoning"] += int(tokens.get("reasoning", 0) or 0)
            cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
            token_totals["cache_read"] += int(cache.get("read", 0) or 0)
    text = "\n".join(text_parts).strip()
    return {
        "text": text,
        "characters": len(text),
        "words": len(text.split()),
        "tokens": token_totals,
        # OpenCode JSON is event-level rather than token streaming.  This is
        # time to the first completed text event, not provider-native TTFT.
        "first_text_event_seconds": (
            (first_text_ms - step_started_ms) / 1000
            if first_text_ms is not None and step_started_ms is not None
            else None
        ),
        "event_span_seconds": (
            (final_event_ms - step_started_ms) / 1000
            if final_event_ms is not None and step_started_ms is not None
            else None
        ),
        "parse_errors": parse_errors,
    }


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def run_speed_smoke(
    models: Sequence[str],
    *,
    repeats: int,
    timeout_seconds: float,
    output_dir: Path,
    seed: int,
    opencode_bin: str = "opencode",
) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if not models or any(not model.strip() for model in models):
        raise ValueError("at least one non-empty model is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    rng = random.Random(seed)
    sequence: list[tuple[int, str]] = []
    for replicate in range(repeats):
        block = list(models)
        rng.shuffle(block)
        sequence.extend((replicate, model) for model in block)

    for ordinal, (replicate, model) in enumerate(sequence):
        safe_model = model.replace("/", "__")
        run_id = f"{ordinal:02d}-r{replicate}-{safe_model}"
        run_dir = output_dir / run_id
        run_dir.mkdir()
        workspace = Path(tempfile.mkdtemp(prefix="opencode-model-speed-workspace-"))
        isolation = Path(tempfile.mkdtemp(prefix="opencode-model-speed-env-"))
        config = RunConfig(task_dir=workspace, condition=Condition.BARE, model=model)
        env, auth_copied, _ = _isolated_env(config, "epires", isolation)
        env["PWD"] = str(workspace)
        try:
            result = _execute(
                [opencode_bin, "run", "--pure", "--model", model, "--format", "json", PROMPT],
                cwd=workspace,
                env=env,
                timeout=timeout_seconds,
            )
            parsed = _parse_jsonl(result.stdout)
            status = "timeout" if result.timed_out else "ok" if result.returncode == 0 else "error"
            record = {
                "run_id": run_id,
                "replicate": replicate,
                "ordinal": ordinal,
                "model": model,
                "status": status,
                "returncode": result.returncode,
                "wall_seconds": result.duration_seconds,
                "auth_copied": auth_copied,
                **parsed,
            }
            (run_dir / "stdout.jsonl").write_text(result.stdout, encoding="utf-8")
            (run_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")
            (run_dir / "result.json").write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            runs.append(record)
            print(
                json.dumps(
                    {
                        "model": model,
                        "replicate": replicate,
                        "status": status,
                        "wall_seconds": round(result.duration_seconds, 3),
                        "output_tokens": parsed["tokens"]["output"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
            shutil.rmtree(isolation, ignore_errors=True)

    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_model[run["model"]].append(run)
    summaries: list[dict[str, Any]] = []
    for model in models:
        model_runs = by_model[model]
        successes = [run for run in model_runs if run["status"] == "ok" and run["text"]]
        walls = [float(run["wall_seconds"]) for run in successes]
        event_latencies = [
            float(run["first_text_event_seconds"])
            for run in successes
            if isinstance(run["first_text_event_seconds"], (int, float))
            and math.isfinite(float(run["first_text_event_seconds"]))
        ]
        summaries.append(
            {
                "model": model,
                "runs": len(model_runs),
                "successes": len(successes),
                "timeouts": sum(run["status"] == "timeout" for run in model_runs),
                "errors": sum(run["status"] == "error" for run in model_runs),
                "median_wall_seconds": _median(walls),
                "median_first_text_event_seconds": _median(event_latencies),
                "median_output_tokens": _median(
                    [float(run["tokens"]["output"]) for run in successes]
                ),
            }
        )
    summaries.sort(
        key=lambda row: (
            -int(row["successes"]),
            float(row["median_wall_seconds"] or math.inf),
        )
    )
    report = {
        "schema_version": 1,
        "benchmark": "opencode_free_model_speed_smoke",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "prompt": PROMPT,
        "repeats": repeats,
        "timeout_seconds": timeout_seconds,
        "seed": seed,
        "execution": "sequential randomized blocks",
        "metric_note": "wall time is end-to-end OpenCode latency; first-text is an event latency, not provider-native TTFT",
        "summaries": summaries,
        "runs": runs,
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--opencode-bin", default="opencode")
    args = parser.parse_args(argv)
    run_speed_smoke(
        args.models or DEFAULT_FREE_MODELS,
        repeats=args.repeats,
        timeout_seconds=args.timeout,
        output_dir=args.output,
        seed=args.seed,
        opencode_bin=args.opencode_bin,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
