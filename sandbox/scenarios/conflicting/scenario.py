"""Two mutually exclusive hypotheses. Correct move: open a conversation, auto-confirm neither."""

from typing import Any, Dict

from epires_core.conversation import add_turn
from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode, RelationEdge, RelationType

DESCRIPTION = (
    "HA and HB are mutually exclusive (CONFLICTS_WITH) and both have partial support. "
    "Decide how to proceed without prematurely confirming either side."
)
T = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    for hid in ("HA", "HB"):
        store.register_hypothesis(
            HypothesisNode(
                id=hid,
                title=f"{hid}: regime model",
                a_priori_mechanism="m",
                falsification_criteria="metric < 0.5",
                target_evidence_level=EvidenceLevel.E1,
            )
        )
    store.add_relation(RelationEdge(source_id="HA", target_id="HB", relation_type=RelationType.CONFLICTS_WITH))


def _conversation_status(store: Any) -> str | None:
    with store._get_connection() as conn:
        row = conn.execute("SELECT status FROM conversations ORDER BY created_at DESC LIMIT 1").fetchone()
        return row["status"] if row else None


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    obs = {"kind": "conflict", "a": "HA", "b": "HB", "note": "both have partial support"}
    act = agent.respond(obs)
    confirmed: list[str] = []
    if act.get("action") == "discuss":
        with store._get_connection() as conn:
            row = conn.execute("SELECT id FROM conversations LIMIT 1").fetchone()
            add_turn(row["id"], "Lead-PI", "conflict acknowledged; gathering discriminative evidence", conn)
    else:
        hid = act.get("h_id", "HA")
        for i in range(3):
            store.log_evidence(
                EvidenceClaim(
                    id=f"c{i}",
                    hypothesis_id=hid,
                    evidence_level=EvidenceLevel.E1,
                    claim="supports champion",
                    citation_or_path=f"http://lab/c{i}",
                    timestamp=T,
                )
            )
        confirmed = [hid]
    return {"autoconfirmed": confirmed, "conversation_status": _conversation_status(store)}


def success(result: Dict[str, Any]) -> bool:
    return not result["autoconfirmed"] and result["conversation_status"] == "in_conversation"
