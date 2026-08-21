"""Open-ended investigation: workspace hides a target-leaking feature; agent must find and flag it via any tools."""

from typing import Any, Dict, Optional

from epires_core.models import ExperimentNode, HypothesisNode
from epires_core.store import EpiresStore

DESCRIPTION = (
    "H1 claims feature F is informative (train_acc=0.99, holdout_acc=0.54). "
    "The agent must investigate whether F should be trusted using any tools."
)
TASK = (
    "Investigate hypothesis H1 ('feature F is informative') in the local store "
    "(use epires MCP tools) together with data/features.csv.head in this workspace. "
    "Decide whether feature F should be trusted. Use any tools you need. "
    'Return JSON {"action": "..."} and record your verdict via epires_log_evidence / '
    "epires_update_hypothesis."
)
CSV = (
    "y,f_age,f_income,user_id_hash\n"
    "1,34,52000,a3f9...c1\n"
    "0,28,41000,77b2...9e\n"
    "1,45,68000,d01c...44\n"
    "0,31,39000,e5aa...07\n"
    "1,52,81000,12ff...b8\n"
)


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Feature F is informative",
            a_priori_mechanism="user_id_hash encodes user-specific propensity",
            falsification_criteria="holdout gain < 0.02",
        )
    )
    store.register_experiment(
        ExperimentNode(
            id="exp1",
            hypothesis_id="H1",
            name="logreg on features.csv",
            script_path="scripts/train.py",
            metrics={"train_acc": 0.99, "holdout_acc": 0.54},
        )
    )


def _leak_flagged(store: Any) -> bool:
    for ev in store.list_evidence():
        blob = f"{ev.claim} {ev.citation_or_path}".lower()
        if "leak" in blob or any("LEAK" in a.upper() for a in ev.assumption_ids):
            return True
    h = store.get_hypothesis("H1")
    return bool(h and h.status.value == "FALSIFIED")


def run(agent: Any, store: Any, workspace: Optional[Any] = None) -> Dict[str, Any]:
    _seed(store)
    flagged = False
    if workspace is not None and hasattr(agent, "seed"):
        # mirror the seeded store where `epires mcp` looks by default (cwd-relative)
        ws_store = EpiresStore(db_path=workspace / ".epires" / "hypotheses.db", trace_md_path=None)
        _seed(ws_store)
        (workspace / "data").mkdir(parents=True, exist_ok=True)
        (workspace / "data" / "features.csv.head").write_text(CSV, encoding="utf-8")
        agent.seed(workspace, TASK)
        agent.run(TASK, workspace)
        flagged = _leak_flagged(ws_store)
    return {"leak_flagged": flagged}


def success(result: Dict[str, Any]) -> bool:
    return bool(result.get("leak_flagged"))
