"""FastMCP Server for Epires Research Harness.

Exposes 11 deterministic tools for LLM agents:
- epires_register_hypothesis
- epires_log_evidence (Collision-proof millisecond + SHA256 ID)
- epires_retract_evidence (Recalculates status, demotes level, and cascades unblocking)
- epires_query_graph
- epires_find_gaps
- epires_associative_search
- epires_export_mermaid_dag
- epires_parallel_web_search
- epires_parallel_extract (Guaranteed JSON serialization)
- epires_record_trace (Accepts both dict and JSON-string)
- epires_system_status
"""

from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from mcp.server.mcpserver import MCPServer

from epires_core.models import (
    Entity,
    EvidenceClaim,
    EvidenceLevel,
    ExperimentNode,
    GapQuery,
    HypothesisNode,
    HypothesisStatus,
    RelationEdge,
    SearchQuery,
    SourceConfidence,
)
from epires_core.store import EpiresStore
from epires_core.tracer import AutoTracer
from tools.web_search import ParallelWebSearcher, get_parallel_api_key


def create_mcp_server(
    db_path: str = ".epires/hypotheses.db",
    trace_md: str = "docs/agent-trace.md"
) -> MCPServer:
    """Creates and configures an MCPServer instance for Epires."""
    mcp = MCPServer("epires")
    store = EpiresStore(db_path=db_path)
    tracer = AutoTracer(store=store, trace_md_path=trace_md)
    web_searcher = ParallelWebSearcher()

    @mcp.tool()
    def epires_system_status() -> str:
        """Get Epires harness version, database status, and Parallel Web Search connectivity."""
        p_key = get_parallel_api_key()
        hypotheses = store.list_hypotheses()
        return json.dumps({
            "version": "0.1.1",
            "db_path": str(db_path),
            "total_hypotheses": len(hypotheses),
            "parallel_auth": bool(p_key),
            "tools_count": 11,
            "status": "ready"
        }, indent=2)

    @mcp.tool()
    def epires_register_hypothesis(
        id: str,
        title: str,
        a_priori_mechanism: str,
        falsification_criteria: str,
        parent_ids: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        entity_values: Optional[List[str]] = None,
        proposed_by: str = "Lead-PI",
        initial_confidence: float = 0.5,
    ) -> str:
        """Register a new hypothesis in the VSA Hypergraph.
        
        Requires theoretical a_priori_mechanism and Popperian falsification_criteria.
        """
        entity_types = entity_types or []
        entity_values = entity_values or []
        if len(entity_types) != len(entity_values):
            raise ValueError(
                "entity_types and entity_values must contain the same number of items"
            )
        node = HypothesisNode(
            id=id,
            title=title,
            a_priori_mechanism=a_priori_mechanism,
            falsification_criteria=falsification_criteria,
            parent_ids=parent_ids or [],
            entities=[Entity(type=entity_type, value=entity_value)
                      for entity_type, entity_value in zip(entity_types, entity_values)],
            current_evidence_level=EvidenceLevel.E0,
            status=HypothesisStatus.PROPOSED,
        )
        saved = store.register_hypothesis(node)
        return f"Successfully registered hypothesis '{saved.id}': {saved.title} (Level: {saved.current_evidence_level.value})"

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
        claim_hash = hashlib.sha256(claim.encode("utf-8")).hexdigest()[:8]
        timestamp_ms = int(time.time() * 1000)
        ev_id = f"ev_{hypothesis_id}_{timestamp_ms}_{claim_hash}"

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
    def epires_retract_evidence(
        evidence_id: str,
        reason: str,
        agent_role: str = "Lead-PI"
    ) -> str:
        """Retract or delete an erroneous evidence claim, recalculating the hypothesis status and evidence level, and unblocking dependent DAG child nodes if all their parents are valid."""
        retracted_ev, unblocked = store.retract_evidence(evidence_id=evidence_id, reason=reason, agent_role=agent_role)
        if not retracted_ev:
            return f"Evidence '{evidence_id}' not found."
        h = store.get_hypothesis(retracted_ev.hypothesis_id)
        msg = f"Evidence [{evidence_id}] for {retracted_ev.hypothesis_id} successfully retracted. Reason: {reason}."
        if h:
            msg += f"\nHypothesis {h.id} status is now {h.status.value} (current level: {h.current_evidence_level.value})."
        if unblocked:
            msg += f"\n[DAG CASCADE] Automatically UNBLOCKED downstream hypotheses: {', '.join(unblocked)}"
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
        """Find untested or under-explored parameter/feature/model combinations (White Spot Gap Analysis).
        
        Searches Cartesian space across dimensions (e.g. ['Model', 'Feature', 'Regime']) and returns
        combinations with fewer than 'min_tested' experiments in the VSA hypergraph.
        """
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
        max_chars: Optional[int] = None,
        max_results: Optional[int] = None,
        **kwargs,
    ) -> str:
        """Execute parallel multi-topic literature and web search using parallel-web 1.3.0 SDK.
        
        If Parallel API key is not configured, returns a fallback status allowing the agent
        to use native harness search tools seamlessly.
        """
        res = web_searcher.search(
            queries=queries,
            objective=objective,
            mode=mode,
            max_chars=max_chars,
            max_results=max_results,
            **kwargs,
        )
        return json.dumps(res, indent=2, ensure_ascii=False)

    @mcp.tool()
    def epires_parallel_extract(
        urls: List[str],
        objective: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Extract structured full text/markdown from specific research URLs via Parallel SDK."""
        res = web_searcher.extract(urls=urls, objective=objective, **kwargs)
        return json.dumps(res, indent=2, ensure_ascii=False)

    @mcp.tool()
    def epires_record_trace(
        action: str,
        summary: str,
        h_tag: Optional[str] = None,
        agent_role: str = "Lead-PI",
        details: Optional[Any] = None,
        details_json: Optional[Any] = None,
    ) -> str:
        """Record an action and rationale into SQLite traces and docs/agent-trace.md.
        
        'details' can be provided either as a dictionary or as a JSON-formatted string.
        """
        raw = details if details is not None else details_json
        if isinstance(raw, dict):
            parsed_details = raw
        elif isinstance(raw, str):
            try:
                parsed_details = json.loads(raw)
            except Exception:
                parsed_details = {"text": raw}
        elif raw is not None:
            parsed_details = {"data": str(raw)}
        else:
            parsed_details = {}

        entry = tracer.record(
            action=action,
            summary=summary,
            h_tag=h_tag,
            agent_role=agent_role,
            details=parsed_details
        )
        return f"Logged trace entry #{entry.id or 'auto'}: [{entry.action}] {entry.summary}"

    return mcp


if __name__ == "__main__":
    import asyncio
    server = create_mcp_server()
    asyncio.run(server.run_stdio_async())
