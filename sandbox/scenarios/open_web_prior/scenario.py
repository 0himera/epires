"""Open-ended task requiring external knowledge: agent must cite literature before confirming H1."""

from typing import Any, Dict, Optional

from epires_core.models import HypothesisNode
from epires_core.store import EpiresStore

DESCRIPTION = (
    "H1 claims gradient boosting outperforms transformers on tabular data of size <10k rows. "
    "The agent must verify against known literature (web search) before confirming."
)
TASK = (
    "Hypothesis H1 in the local store (use epires MCP tools) claims that gradient boosting "
    "outperforms transformers on tabular data of size <10k rows. Verify against known "
    "literature before confirming. You may use web search tools. Record your verdict via "
    "epires_log_evidence with a citation to the source you used, then claim with an "
    "appropriate evidence level."
)


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Gradient boosting beats transformers on small tabular data",
            a_priori_mechanism="tree ensembles have stronger inductive bias on <10k-row tables",
            falsification_criteria="transformer beats GBDT on >=2 independent benchmarks",
        )
    )


def _cited(store: Any) -> bool:
    return any(
        ev.citation_or_path and not ev.citation_or_path.startswith("http://lab")
        for ev in store.list_evidence()
    )


def run(agent: Any, store: Any, workspace: Optional[Any] = None) -> Dict[str, Any]:
    _seed(store)
    cited = False
    if workspace is not None and hasattr(agent, "seed"):
        # mirror the seeded store where `epires mcp` looks by default (cwd-relative)
        ws_store = EpiresStore(db_path=workspace / ".epires" / "hypotheses.db", trace_md_path=None)
        _seed(ws_store)
        agent.seed(workspace, TASK)
        agent.run(TASK, workspace)
        cited = _cited(ws_store)
    return {"external_citation": cited}


def success(result: Dict[str, Any]) -> bool:
    return bool(result.get("external_citation"))
