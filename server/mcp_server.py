"""Model Context Protocol (MCP) Server for Epires Research Engine."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from mcp.server.mcpserver import MCPServer

from epires_core.models import (
    Entity,
    EvidenceClaim,
    EvidenceLevel,
    GapQuery,
    HypothesisNode,
    HypothesisStatus,
    SearchQuery,
    SourceConfidence,
    TraceEntry,
)
from epires_core.store import EpiresStore
from epires_core.tracer import AutoTracer
from tools.web_search import ParallelWebSearcher


def create_mcp_server(
    db_path: str = ".epires/hypotheses.db",
    trace_md: str = "docs/agent-trace.md",
    name: str = "epires",
) -> MCPServer:
    mcp = MCPServer(name=name)
    store = EpiresStore(db_path=db_path)
    tracer = AutoTracer(store=store, trace_md_path=trace_md)
    web_searcher = ParallelWebSearcher()

    @mcp.tool()
    def epires_register_hypothesis(
        id: str,
        title: str,
        a_priori_mechanism: str,
        falsification_criteria: str,
        target_evidence_level: str = "E3",
        parent_ids: Optional[List[str]] = None,
        entities: Optional[List[Dict[str, str]]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Register a new hypothesis in the VSA Hypergraph prior to any execution.
        
        Requires a priori justification and Popperian falsification criteria.
        """
        p_ids = parent_ids or []
        ent_list = [Entity(type=e["type"], value=e["value"]) for e in (entities or [])]
        t_list = tags or []

        h = HypothesisNode(
            id=id,
            title=title,
            a_priori_mechanism=a_priori_mechanism,
            falsification_criteria=falsification_criteria,
            target_evidence_level=EvidenceLevel(target_evidence_level),
            current_evidence_level=EvidenceLevel.E0,
            status=HypothesisStatus.PROPOSED,
            parent_ids=p_ids,
            entities=ent_list,
            tags=t_list,
        )
        saved = store.register_hypothesis(h)
        tracer.record(
            action="REGISTER_HYPOTHESIS",
            summary=f"Registered {saved.id}: {saved.title}",
            h_tag=saved.id,
            agent_role="Lead-PI",
            details={"parents": p_ids, "target_level": target_evidence_level}
        )
        return f"Successfully registered hypothesis {saved.id} (Status: {saved.status.value}, Vectorized into VSA Hypergraph)"

    @mcp.tool()
    def epires_log_evidence(
        hypothesis_id: str,
        claim: str,
        evidence_level: str = "E2",
        source_confidence: str = "V",
        metric_name: Optional[str] = None,
        metric_value: Optional[float] = None,
        delta_vs_baseline: Optional[float] = None,
        ci_95_lower: Optional[float] = None,
        ci_95_upper: Optional[float] = None,
        falsification_triggered: bool = False,
        citation_or_path: str = "",
        artifact_hash: Optional[str] = None,
    ) -> str:
        """Record empirical evidence for a hypothesis.
        
        If falsification_triggered is True, the hypothesis is marked FALSIFIED and all
        dependent child hypotheses in the DAG are automatically BLOCKED.
        """
        ev_id = f"ev_{hypothesis_id}_{int(Path(db_path).stat().st_mtime if Path(db_path).exists() else 0)}_{hash(claim) % 100000}"
        claim_obj = EvidenceClaim(
            id=ev_id,
            hypothesis_id=hypothesis_id,
            evidence_level=EvidenceLevel(evidence_level),
            source_confidence=SourceConfidence(source_confidence),
            claim=claim,
            metric_name=metric_name,
            metric_value=metric_value,
            delta_vs_baseline=delta_vs_baseline,
            ci_95_lower=ci_95_lower,
            ci_95_upper=ci_95_upper,
            falsification_triggered=falsification_triggered,
            citation_or_path=citation_or_path,
            artifact_hash=artifact_hash,
        )
        saved_ev, blocked_children = store.log_evidence(claim_obj)
        
        msg = f"Evidence [{saved_ev.evidence_level.value}, {saved_ev.source_confidence.value}] recorded for {hypothesis_id}."
        if falsification_triggered:
            msg += f"\n[ALERT] Falsification triggered! Marked {hypothesis_id} as FALSIFIED."
            if blocked_children:
                msg += f"\n[DAG CASCADE] Automatically BLOCKED downstream dependent hypotheses: {', '.join(blocked_children)}"
        return msg

    @mcp.tool()
    def epires_query_graph(
        status: Optional[str] = None,
        h_id: Optional[str] = None,
    ) -> str:
        """Query hypotheses in the research graph by status (PROPOSED, CONFIRMED, FALSIFIED, BLOCKED) or ID."""
        if h_id:
            h = store.get_hypothesis(h_id)
            if not h:
                return f"Hypothesis '{h_id}' not found."
            evidence = store.get_evidence_for_hypothesis(h_id)
            return json.dumps({
                "hypothesis": h.model_dump(),
                "evidence": [e.model_dump() for e in evidence]
            }, indent=2, ensure_ascii=False)

        stat_enum = HypothesisStatus(status) if status else None
        hypotheses = store.list_hypotheses(status=stat_enum)
        summary_list = []
        for h in hypotheses:
            summary_list.append({
                "id": h.id,
                "title": h.title,
                "status": h.status.value,
                "current_level": h.current_evidence_level.value,
                "parents": h.parent_ids,
                "falsification_criteria": h.falsification_criteria
            })
        return json.dumps(summary_list, indent=2, ensure_ascii=False)

    @mcp.tool()
    def epires_find_gaps(
        dimensions: List[str],
        min_tested: int = 1,
    ) -> str:
        """Find untested or under-explored parameter/feature/model combinations (White Spot Gap Analysis)."""
        gaps = store.find_gaps(GapQuery(dimensions=dimensions, min_tested=min_tested))
        return json.dumps(gaps, indent=2, ensure_ascii=False)

    @mcp.tool()
    def epires_associative_search(
        query: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 5,
    ) -> str:
        """Perform VSA cosine similarity search across the hypothesis hypergraph."""
        stat_enum = HypothesisStatus(status) if status else None
        results = store.search(SearchQuery(query=query, status=stat_enum, limit=limit))
        output = [
            {"id": h.id, "title": h.title, "status": h.status.value, "similarity": round(score, 4)}
            for h, score in results
        ]
        return json.dumps(output, indent=2, ensure_ascii=False)

    @mcp.tool()
    def epires_export_mermaid_dag() -> str:
        """Export the complete hypothesis dependency DAG as Mermaid markdown for visualization."""
        return store.export_mermaid_dag()

    @mcp.tool()
    def epires_parallel_web_search(
        queries: List[str],
        objective: Optional[str] = None,
        mode: str = "fast",
    ) -> str:
        """Execute parallel multi-topic literature and web search using parallel-web 1.3.0 SDK."""
        res = web_searcher.search(queries=queries, objective=objective, mode=mode)
        return json.dumps(res, indent=2, ensure_ascii=False)

    @mcp.tool()
    def epires_record_trace(
        action: str,
        summary: str,
        h_tag: Optional[str] = None,
        agent_role: str = "Lead-PI",
        details_json: Optional[str] = None,
    ) -> str:
        """Record an action and rationale into SQLite traces and docs/agent-trace.md."""
        details = json.loads(details_json) if details_json else {}
        entry = tracer.record(
            action=action,
            summary=summary,
            h_tag=h_tag,
            agent_role=agent_role,
            details=details
        )
        return f"Logged trace entry #{entry.id or 'auto'}: [{entry.action}] {entry.summary}"

    return mcp


if __name__ == "__main__":
    import asyncio
    server = create_mcp_server()
    asyncio.run(server.run_stdio_async())
