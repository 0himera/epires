"""Minimal local eval harness: scenarios x prompt-variants x agents -> metrics JSON + report."""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, List, Optional

SANDBOX = Path(__file__).resolve().parent
RESULTS_DIR = SANDBOX / "results"
SCENARIOS = sorted(p.name for p in (SANDBOX / "scenarios").iterdir() if p.is_dir())
VARIANTS = sorted(p.stem for p in (SANDBOX / "variants").glob("*.md"))


def load_scenario(name: str) -> Any:
    path = SANDBOX / "scenarios" / name / "scenario.py"
    spec = importlib.util.spec_from_file_location(f"sandbox_scenario_{name}", path)
    assert spec and spec.loader, f"cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_variant(name: str) -> str:
    return (SANDBOX / "variants" / f"{name}.md").read_text(encoding="utf-8")


def make_agent(kind: str, variant_text: str, scenario_description: str, model: Optional[str] = None) -> Any:
    from .agents import LLMAgent, MockAgent

    if kind == "mock":
        return MockAgent(variant_text)
    if kind == "llm":
        return LLMAgent(variant_text, scenario_description, model=model)
    if kind == "opencode":
        from .agents import OpencodeAgent

        return OpencodeAgent(variant_text, model=model)
    raise ValueError(f"unknown agent kind: {kind}")


def run_one(
    scenario: str,
    variant: str,
    agent_kind: str = "mock",
    results_dir: Optional[str | Path] = None,
    model: Optional[str] = None,
) -> dict:
    from epires_core.store import EpiresStore

    from .metrics import collect, grade

    mod = load_scenario(scenario)
    rdir = Path(results_dir) if results_dir else RESULTS_DIR
    rdir.mkdir(parents=True, exist_ok=True)
    active_model = model or os.environ.get("EPIRES_EVAL_MODEL", "unknown")
    if agent_kind == "opencode":
        # persistent workspace: store lives there so the agent can inspect it via MCP
        td = None
        mtag = active_model.replace("/", "_")
        ws = rdir / f"ws_{scenario}__{variant}__{mtag}"
        if ws.exists():
            shutil.rmtree(ws)  # ponytail: fresh state — append-only ledger breaks reseeding
        ws.mkdir(parents=True)
        db_path = ws / "store.db"
    else:
        td = tempfile.TemporaryDirectory(prefix="epires_eval_")
        ws = Path(td.name)
        db_path = ws / "eval.db"
    try:
        store = EpiresStore(db_path=db_path, trace_md_path=None)
        agent = make_agent(agent_kind, load_variant(variant), getattr(mod, "DESCRIPTION", ""), model=model)
        extra = mod.run(agent, store, ws) if len(inspect.signature(mod.run).parameters) > 2 else mod.run(agent, store)
        result = {"scenario": scenario, "variant": variant, "agent": agent_kind, **collect(store, scenario), **extra}
    finally:
        if td is not None:
            td.cleanup()
    result["success"] = bool(mod.success(result))
    result["score"] = round(grade(result, scenario), 2)
    model_tag = ""
    if agent_kind == "opencode":
        model_tag = "__" + active_model.replace("/", "_")
    (rdir / f"{scenario}__{variant}{model_tag}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def run_all(agent_kind: str = "mock", results_dir: Optional[str | Path] = None) -> List[dict]:
    return [run_one(s, v, agent_kind, results_dir) for s in SCENARIOS for v in VARIANTS]


_COLS = [
    "scenario",
    "variant",
    "success",
    "score",
    "integrity_gap",
    "n_confirmed",
    "n_falsified",
    "n_blocked",
    "false_cascade_count",
    "bateson_hot",
]


def _fmt(v: Any) -> str:
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def report(results_dir: Optional[str | Path] = None) -> None:
    from .metrics import grade

    rdir = Path(results_dir) if results_dir else RESULTS_DIR
    files = sorted(rdir.glob("*__*.json"))
    if not files:
        print("no results yet — run: python -m sandbox.run_eval --all")
        return
    widths = [16, 12, 9, 9, 9, 9, 9, 9, 9, 9]
    print(" ".join(c.ljust(w) for c, w in zip(_COLS, widths)))
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        d.setdefault("score", round(grade(d, d.get("scenario", "")), 2))
        print(" ".join(_fmt(d.get(c)).ljust(w) for c, w in zip(_COLS, widths)))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario")
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--agent", default="mock", choices=["mock", "llm", "opencode"])
    ap.add_argument("--model", default=None, help="LLM or opencode model identifier (e.g. opencode/hy3-free)")
    ap.add_argument("--all", action="store_true", help="run all scenarios x all variants")
    ap.add_argument("--report", action="store_true", help="print table of stored results")
    args = ap.parse_args(argv)

    if args.report:
        report()
        return
    if args.all:
        results = [run_one(s, v, args.agent, model=args.model) for s in SCENARIOS for v in VARIANTS]
    elif args.scenario:
        results = [run_one(args.scenario, args.variant, args.agent, model=args.model)]
    else:
        ap.error("choose --scenario NAME or --all (or --report)")
    for r in results:
        print(f"{r['scenario']:<14} {r['variant']:<10} success={r['success']}")


if __name__ == "__main__":
    main()
