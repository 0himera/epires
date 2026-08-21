"""Minimal local eval harness: scenarios x prompt-variants x agents -> metrics JSON + report."""

from __future__ import annotations

import argparse
import importlib.util
import json
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


def make_agent(kind: str, variant_text: str, scenario_description: str) -> Any:
    from .agents import LLMAgent, MockAgent

    if kind == "mock":
        return MockAgent(variant_text)
    if kind == "llm":
        return LLMAgent(variant_text, scenario_description)
    raise ValueError(f"unknown agent kind: {kind}")


def run_one(
    scenario: str, variant: str, agent_kind: str = "mock", results_dir: Optional[str | Path] = None
) -> dict:
    from epires_core.store import EpiresStore

    from .metrics import collect

    mod = load_scenario(scenario)
    rdir = Path(results_dir) if results_dir else RESULTS_DIR
    rdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="epires_eval_") as td:
        store = EpiresStore(db_path=Path(td) / "eval.db", trace_md_path=None)
        agent = make_agent(agent_kind, load_variant(variant), getattr(mod, "DESCRIPTION", ""))
        extra = mod.run(agent, store)
        result = {"scenario": scenario, "variant": variant, "agent": agent_kind, **collect(store, scenario), **extra}
    result["success"] = bool(mod.success(result))
    (rdir / f"{scenario}__{variant}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def run_all(agent_kind: str = "mock", results_dir: Optional[str | Path] = None) -> List[dict]:
    return [run_one(s, v, agent_kind, results_dir) for s in SCENARIOS for v in VARIANTS]


_COLS = [
    "scenario",
    "variant",
    "success",
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
    rdir = Path(results_dir) if results_dir else RESULTS_DIR
    files = sorted(rdir.glob("*__*.json"))
    if not files:
        print("no results yet — run: python -m sandbox.run_eval --all")
        return
    widths = [16, 12, 9, 9, 9, 9, 9, 9, 9]
    print(" ".join(c.ljust(w) for c, w in zip(_COLS, widths)))
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        print(" ".join(_fmt(d.get(c)).ljust(w) for c, w in zip(_COLS, widths)))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario")
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--agent", default="mock", choices=["mock", "llm"])
    ap.add_argument("--all", action="store_true", help="run all scenarios x all variants")
    ap.add_argument("--report", action="store_true", help="print table of stored results")
    args = ap.parse_args(argv)

    if args.report:
        report()
        return
    if args.all:
        results = run_all(args.agent)
    elif args.scenario:
        results = [run_one(args.scenario, args.variant, args.agent)]
    else:
        ap.error("choose --scenario NAME or --all (or --report)")
    for r in results:
        print(f"{r['scenario']:<14} {r['variant']:<10} success={r['success']}")


if __name__ == "__main__":
    main()
