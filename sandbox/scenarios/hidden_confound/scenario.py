"""+11pp but arms differ in embedder too — hidden confound, suspects NOT given. Correct: attribute embedder/baseline."""

from typing import Any, Dict

from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode, TraceEntry

DESCRIPTION = (
    "H1: module M improves QA. Comparison M(embedder=E5) vs RAG(embedder=MiniLM) shows +11pp. "
    "No suspect list is provided: the arms differ in architecture AND embedder — the confound must be named."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Module M improves QA",
            a_priori_mechanism="m",
            falsification_criteria="delta < 0",
            target_evidence_level=EvidenceLevel.E3,
        )
    )
    store.log_trace(
        TraceEntry(
            timestamp=T0,
            action="COMPARISON",
            h_tag="H1",
            summary="M vs RAG baseline, +11pp",
            details={
                "arms": {
                    "M": {"architecture": "M", "embedder": "E5"},
                    "RAG": {"architecture": "RAG", "embedder": "MiniLM"},
                }
            },
        )
    )


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    obs = {"kind": "result", "delta_pp": 11, "configs_differ": ["architecture", "embedder"]}
    act = agent.respond(obs)
    attributed = act.get("action") == "attribute"
    aids = [str(a) for a in act.get("assumption_ids", [])] if attributed else []
    blamed = any(k in a.upper() for a in aids for k in ("EMBEDDER", "BASELINE"))
    level = EvidenceLevel.E1 if attributed else EvidenceLevel.E3
    store.log_evidence(
        EvidenceClaim(
            id="res1",
            hypothesis_id="H1",
            evidence_level=level,
            claim="+11pp over RAG baseline (arms differ in architecture and embedder)",
            citation_or_path="http://lab/res1",
            assumption_ids=aids,
            timestamp=T1,
        )
    )
    return {
        "attributed": attributed,
        "blamed_embedder_or_baseline": blamed,
        "status": store.get_hypothesis("H1").status.value,
    }


def success(result: Dict[str, Any]) -> bool:
    return result["attributed"] and result["status"] != "CONFIRMED"
