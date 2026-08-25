"""CLI for the isolated OpenCode + Epires performance A/B benchmark."""

from __future__ import annotations

import argparse
import json
import os
import random
import uuid
from pathlib import Path

from .runner import Condition, RunConfig, run_trial


def _conditions(value: str) -> list[Condition]:
    groups = {
        "both": [Condition.BARE, Condition.EPIRES],
        "delegation_ablation": [Condition.EPIRES, Condition.EPIRES_DIRECT],
        "ablation": [
            Condition.EPIRES,
            Condition.EPIRES_DIRECT,
            Condition.EPIRES_MINIMAL,
            Condition.EPIRES_PROBE,
            Condition.EPIRES_MCP_ONLY,
        ],
        "all": [
            Condition.BARE,
            Condition.EPIRES,
            Condition.EPIRES_DIRECT,
            Condition.EPIRES_MINIMAL,
            Condition.EPIRES_PROBE,
            Condition.EPIRES_MCP_ONLY,
        ],
        "web_ablation": [
            Condition.BARE,
            Condition.EPIRES_PROBE_NO_WEB,
            Condition.EPIRES_WEB_TASK_SKILL,
            Condition.EPIRES_WEB_TASK_AGENTS,
            Condition.EPIRES_WEB_BASELINE_SKILL,
        ],
    }
    if value in groups:
        return groups[value]
    return [Condition(value)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True, help="task directory containing project/ and hidden/")
    parser.add_argument("--model", default=os.getenv("EPIRES_EVAL_MODEL", ""), help="OpenCode provider/model")
    parser.add_argument("--variant", help="provider-specific model variant, for example low or high")
    parser.add_argument(
        "--condition",
        choices=[
            "bare",
            "epires",
            "epires_direct",
            "epires_minimal",
            "epires_probe",
            "epires_mcp_only",
            "epires_probe_no_web",
            "epires_web_task_skill",
            "epires_web_task_agents",
            "epires_web_baseline_skill",
            "both",
            "delegation_ablation",
            "ablation",
            "all",
            "web_ablation",
        ],
        default="both",
    )
    parser.add_argument("--trials", type=int, default=1, help="repetitions per condition")
    parser.add_argument("--order-seed", type=int, default=42, help="seed for deterministic treatment counterbalancing")
    parser.add_argument("--timeout", type=float, default=600.0, help="agent timeout in seconds")
    parser.add_argument("--grader-timeout", type=float, default=180.0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--workspace-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--opencode-bin", default="opencode")
    parser.add_argument("--epires-bin", default=None)
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument(
        "--enable-web-auth",
        action="store_true",
        help="opt in to copying only Epires web credentials into each isolated HOME",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.model:
        raise SystemExit("--model is required (or set EPIRES_EVAL_MODEL)")
    if args.trials < 1:
        raise SystemExit("--trials must be at least 1")

    records: list[dict[str, object]] = []
    batch_id = uuid.uuid4().hex[:12]
    first_order = _conditions(args.condition)
    random.Random(args.order_seed).shuffle(first_order)
    for repetition in range(args.trials):
        conditions = first_order if repetition % 2 == 0 else list(reversed(first_order))
        pair_id = f"{args.task.resolve().name}-{batch_id}-rep{repetition}"
        for condition in conditions:
            config = RunConfig(
                task_dir=args.task,
                condition=condition,
                model=args.model,
                variant=args.variant,
                timeout_seconds=args.timeout,
                grader_timeout_seconds=args.grader_timeout,
                output_dir=args.output,
                workspace_root=args.workspace_root,
                opencode_bin=args.opencode_bin,
                epires_bin=args.epires_bin,
                keep_workspace=args.keep_workspace,
                enable_web_auth=args.enable_web_auth,
                pair_id=pair_id,
                replicate=repetition,
            )
            record = run_trial(config)
            records.append(record)
            print(
                json.dumps(
                    {
                        "repetition": repetition,
                        "trial_id": record["trial_id"],
                        "condition": record["condition"],
                        "pair_id": record["pair_id"],
                        "status": record["status"],
                        "result_dir": record["result_dir"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    return 0 if all(record["status"] == "completed" for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
