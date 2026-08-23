"""FastMCP Server for Epires Research Harness.

Exposes 28 deterministic tools for LLM agents:
- epires_get_schema (Canonical data format & python migration template)
- epires_register_hypothesis (Popperian criteria & DAG cycle detection)
- epires_register_experiment (Explicit reproducibility metadata & execution parameters)
- epires_list_experiments (Historical experiment provenance)
- epires_log_evidence (Collision-proof millisecond + SHA256 ID, E4 CI check, append-only)
- epires_retract_evidence (Recalculates status, demotes level, and cascades unblocking)
- epires_update_hypothesis (Explicit status update, target level, tags, fields)
- epires_add_relation (Explicit semantic relations: SUPERSEDES, CONFLICTS_WITH, REFINES, BLOCKS, GATED_BY)
- epires_list_relations (Query graph relation edges)
- epires_bulk_import (Fast batch transaction ingestion for all 5 entity types)
- epires_export_graph (Portable JSON bundle with SHA256 checksum)
- epires_import_graph (Reproducible full graph restoration)
- epires_query_graph
- epires_find_gaps (Empirical gap analysis across dimensions)
- epires_associative_search (Hybrid SQLite FTS5 + VSA cosine similarity search)
- epires_export_mermaid_dag (Visual graph diagram with all relation types)
- epires_parallel_web_search (Multi-query literature search via parallel-web)
- epires_parallel_extract (Guaranteed JSON markdown extraction from URLs)
- epires_record_trace (Real-time operational audit trail)
 - epires_system_status (Harness version, database status, and tools inventory)
"""

from __future__ import annotations
import hashlib
import json
import time
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
    RelationType,
    SearchQuery,
    SourceConfidence,
)
from epires_core import __version__
from epires_core.schema import get_canonical_schema
from epires_core.store import EpiresStore
from epires_core.tracer import AutoTracer
from tools.web_search import ParallelWebSearcher, get_parallel_api_key


def create_mcp_server(db_path: str = ".epires/hypotheses.db", trace_md: str = "docs/agent-trace.md") -> MCPServer:
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
        return json.dumps(
            {
                "version": __version__,
                "db_path": str(db_path),
                "total_hypotheses": len(hypotheses),
                "parallel_auth": bool(p_key),
                "tools_count": 30,
                "status": "ready",
            },
            indent=2,
        )

    @mcp.tool()
    def epires_summary() -> str:
        """Get an aggregated, lightweight (<1 KB) status overview of the research graph.

        Returns total hypotheses, counts by status (CONFIRMED, PROPOSED, IN_PROGRESS, FALSIFIED, BLOCKED),
        evidence levels distribution, active frontier hypotheses, and blocked branches.
        Use this instead of query_graph when you need a fast and compact progress overview.
        """
        summary = store.get_summary()
        return json.dumps(summary, indent=2, ensure_ascii=False)

    @mcp.tool()
    def epires_get_schema() -> str:
        """Returns the canonical JSON schema, supported enum values, and Python SDK quickstart for migrating custom/legacy project findings."""
        return json.dumps(get_canonical_schema(), indent=2)

    @mcp.tool()
    def epires_register_hypothesis(
        id: str,
        title: str,
        a_priori_mechanism: str,
        falsification_criteria: str,
        parent_ids: Optional[Union[List[str], str]] = None,
        tags: Optional[Union[List[str], str]] = None,
        entity_types: Optional[Union[List[str], str]] = None,
        entity_values: Optional[Union[List[str], str]] = None,
        entities: Optional[Union[List[Dict[str, str]], List[str], str]] = None,
        target_evidence_level: str = "E3",
        proposed_by: str = "Lead-PI",
        initial_confidence: float = 0.5,
    ) -> str:
        """Register a new hypothesis in the VSA Hypergraph.

        Requires theoretical a_priori_mechanism and Popperian falsification_criteria.
        Supports flexible list or comma-separated string tags, entities, and parent_ids.
        """
        # Parse entities
        ents: List[Any] = []
        if entities is not None:
            ents = entities if isinstance(entities, list) else [entities]
        elif entity_types is not None or entity_values is not None:
            t_list = [entity_types] if isinstance(entity_types, str) else (entity_types or [])
            v_list = [entity_values] if isinstance(entity_values, str) else (entity_values or [])
            if len(t_list) != len(v_list):
                raise ValueError("entity_types and entity_values must contain the same number of items")
            for t, v in zip(t_list, v_list):
                ents.append(Entity(type=str(t), value=str(v)))

        target_enum = (
            EvidenceLevel(target_evidence_level)
            if target_evidence_level in EvidenceLevel._value2member_map_
            else EvidenceLevel.E3
        )

        node = HypothesisNode(
            id=id,
            title=title,
            a_priori_mechanism=a_priori_mechanism,
            falsification_criteria=falsification_criteria,
            parent_ids=parent_ids or [],
            entities=ents,
            tags=tags or [],
            target_evidence_level=target_enum,
            current_evidence_level=EvidenceLevel.E0,
            status=HypothesisStatus.PROPOSED,
        )
        saved = store.register_hypothesis(node)
        return f"Successfully registered hypothesis '{saved.id}': {saved.title} (Level: {saved.current_evidence_level.value})"

    @mcp.tool()
    def epires_register_experiment(
        hypothesis_id: str,
        name: str,
        script_path: str,
        parameters: Optional[Union[Dict[str, Any], str]] = None,
        metrics: Optional[Union[Dict[str, float], str]] = None,
        commit_hash: Optional[str] = None,
        artifact_paths: Optional[List[str]] = None,
    ) -> str:
        """Register a concrete computational experiment linked to a hypothesis for auditability and reproducibility."""
        params_dict: Dict[str, Any] = {}
        if isinstance(parameters, dict):
            params_dict = parameters
        elif isinstance(parameters, str):
            try:
                params_dict = json.loads(parameters)
            except Exception:
                params_dict = {"raw": parameters}

        metrics_dict: Dict[str, float] = {}
        if isinstance(metrics, dict):
            metrics_dict = metrics
        elif isinstance(metrics, str):
            try:
                metrics_dict = json.loads(metrics)
            except Exception:
                pass

        exp_id = f"exp_{hypothesis_id}_{int(time.time() * 1000)}"
        exp_node = ExperimentNode(
            id=exp_id,
            hypothesis_id=hypothesis_id,
            name=name,
            script_path=script_path,
            commit_hash=commit_hash,
            parameters=params_dict,
            metrics=metrics_dict,
            artifact_paths=artifact_paths or [],
        )
        saved = store.register_experiment(exp_node)
        return f"Successfully registered experiment '{saved.id}' for hypothesis {hypothesis_id}: {saved.name}"

    @mcp.tool()
    def epires_list_experiments(hypothesis_id: Optional[str] = None) -> str:
        """List registered experiments, optionally filtered by target hypothesis ID."""
        experiments = store.list_experiments(hypothesis_id=hypothesis_id)
        return json.dumps([e.model_dump() for e in experiments], indent=2)

    @mcp.tool()
    def epires_log_evidence(
        hypothesis_id: str,
        claim: Optional[str] = None,
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
        assumption_ids: Optional[Union[List[str], str]] = None,
    ) -> str:
        """Record empirical evidence for a hypothesis.

        claim: Optional descriptive summary. If omitted, will be auto-generated from metric_name/metric_value.
        If falsification_triggered is True (or metrics violate falsification_criteria),
        the hypothesis is marked FALSIFIED and all dependent child hypotheses in the DAG are automatically BLOCKED.
        """
        claim_str = (claim or "").strip()
        if not claim_str:
            if metric_name and metric_value is not None:
                claim_str = f"Observed {metric_name}={metric_value}"
                if delta_vs_baseline is not None:
                    claim_str += f" (delta={delta_vs_baseline})"
            else:
                claim_str = f"Evidence claim for {hypothesis_id}"

        claim_hash = hashlib.sha256(claim_str.encode("utf-8")).hexdigest()[:8]
        timestamp_ms = int(time.time() * 1000)
        ev_id = f"ev_{hypothesis_id}_{timestamp_ms}_{claim_hash}"

        claim_obj = EvidenceClaim(
            id=ev_id,
            hypothesis_id=hypothesis_id,
            evidence_level=EvidenceLevel(evidence_level),
            source_confidence=SourceConfidence(source_confidence),
            claim=claim_str,
            metric_name=metric_name,
            metric_value=metric_value,
            delta_vs_baseline=delta_vs_baseline,
            ci_95_lower=ci_95_lower,
            ci_95_upper=ci_95_upper,
            falsification_triggered=falsification_triggered,
            citation_or_path=citation_or_path,
            artifact_hash=artifact_hash,
            assumption_ids=assumption_ids or [],
        )
        saved_ev, blocked_children = store.log_evidence(claim_obj)

        msg = f"Evidence [{saved_ev.evidence_level.value}, {saved_ev.source_confidence.value}] recorded for {hypothesis_id}."
        if saved_ev.falsification_triggered:
            msg += f"\n[ALERT] Falsification triggered! Marked {hypothesis_id} as FALSIFIED."
            if blocked_children:
                msg += f"\n[DAG CASCADE] Automatically BLOCKED downstream dependent hypotheses: {', '.join(blocked_children)}"
        return msg

    @mcp.tool()
    def epires_retract_evidence(evidence_id: str, reason: str, agent_role: str = "Lead-PI") -> str:
        """Retract or delete an erroneous evidence claim, recalculating the hypothesis status and evidence level, and unblocking dependent DAG child nodes if all their parents are valid."""
        retracted_ev, unblocked = store.retract_evidence(evidence_id=evidence_id, reason=reason, agent_role=agent_role)
        if not retracted_ev:
            return f"Evidence '{evidence_id}' not found."
        h = store.get_hypothesis(retracted_ev.hypothesis_id)
        msg = f"Evidence [{evidence_id}] for {retracted_ev.hypothesis_id} successfully retracted. Reason: {reason}."
        if h:
            msg += (
                f"\nHypothesis {h.id} status is now {h.status.value} (current level: {h.current_evidence_level.value})."
            )
        if unblocked:
            msg += f"\n[DAG CASCADE] Automatically UNBLOCKED downstream hypotheses: {', '.join(unblocked)}"
        return msg

    @mcp.tool()
    def epires_update_hypothesis(
        id: str,
        status: Optional[str] = None,
        target_evidence_level: Optional[str] = None,
        title: Optional[str] = None,
        a_priori_mechanism: Optional[str] = None,
        falsification_criteria: Optional[str] = None,
        parent_ids: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        entity_values: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        agent_role: str = "Lead-PI",
    ) -> str:
        """Explicitly update properties or status of an existing hypothesis (e.g. set REFINED, PAUSED, IN_PROGRESS, or edit target level/tags)."""
        entities = None
        if entity_types is not None and entity_values is not None:
            if len(entity_types) != len(entity_values):
                raise ValueError("entity_types and entity_values must match in length")
            entities = [Entity(type=t, value=v) for t, v in zip(entity_types, entity_values)]

        stat_enum = HypothesisStatus(status) if status else None
        target_enum = EvidenceLevel(target_evidence_level) if target_evidence_level else None

        updated = store.update_hypothesis(
            h_id=id,
            title=title,
            a_priori_mechanism=a_priori_mechanism,
            falsification_criteria=falsification_criteria,
            target_evidence_level=target_enum,
            status=stat_enum,
            parent_ids=parent_ids,
            entities=entities,
            tags=tags,
            agent_role=agent_role,
        )
        if not updated:
            return f"Hypothesis '{id}' not found."
        return f"Successfully updated hypothesis '{updated.id}': Status is {updated.status.value}, Target: {updated.target_evidence_level.value}."

    @mcp.tool()
    def epires_add_relation(
        source_id: str,
        target_id: str,
        relation_type: str = "REFINES",
        metadata: Optional[Union[Dict[str, Any], str]] = None,
    ) -> str:
        """Create a semantic graph relation between hypotheses, experiments, or evidence.

        Supported relation_type values:
        - DEPENDS_ON: Target depends on source premise (strict DAG dependency)
        - SUPERSEDES: Source hypothesis replaces/improves upon target
        - CONFLICTS_WITH: Source and target are competing/mutually exclusive
        - REFINES: Source provides higher precision / parameter specialization over target
        - BLOCKS: Source negative result blocks target from execution
        - FALSIFIES: Source evidence/experiment falsifies target
        - PRODUCES: Source experiment produces target artifact/evidence
        - GATED_BY: Source hypothesis requires passing target statistical gate
        """
        meta_dict: Dict[str, Any] = {}
        if isinstance(metadata, dict):
            meta_dict = metadata
        elif isinstance(metadata, str):
            try:
                meta_dict = json.loads(metadata)
            except Exception:
                meta_dict = {"raw": metadata}

        rel_enum = RelationType(relation_type.upper())
        edge = RelationEdge(
            source_id=source_id,
            target_id=target_id,
            relation_type=rel_enum,
            metadata=meta_dict,
        )
        saved = store.add_relation(edge)
        return f"Successfully linked {saved.source_id} ==[{saved.relation_type.value}]==> {saved.target_id}"

    @mcp.tool()
    def epires_list_relations(relation_type: Optional[str] = None) -> str:
        """List persisted graph relation edges, optionally filtered by relation type."""
        rel_enum = RelationType(relation_type.upper()) if relation_type else None
        relations = store.list_relations(relation_type=rel_enum)
        return json.dumps(
            [
                {
                    "source_id": r.source_id,
                    "target_id": r.target_id,
                    "relation_type": r.relation_type.value,
                    "metadata": r.metadata,
                }
                for r in relations
            ],
            indent=2,
        )

    @mcp.tool()
    def epires_bulk_import(hypotheses_json: str, evidence_json: Optional[str] = None, upsert: bool = True) -> str:
        """Bulk import a batch of hypotheses and/or evidence claims in a single transaction.

        hypotheses_json: JSON string representing an array of Hypothesis objects.
        evidence_json: Optional JSON string representing an array of Evidence objects.
        """
        raw_h = json.loads(hypotheses_json) if hypotheses_json else []
        raw_ev = json.loads(evidence_json) if evidence_json else []

        h_objs = []
        for item in raw_h:
            if "entities" in item and isinstance(item["entities"], list):
                item["entities"] = [Entity(**e) if isinstance(e, dict) else e for e in item["entities"]]
            h_objs.append(HypothesisNode(**item))

        ev_objs = [EvidenceClaim(**item) for item in raw_ev]
        res = store.bulk_import(hypotheses=h_objs, evidence=ev_objs, upsert=upsert)
        return json.dumps(res, indent=2)

    @mcp.tool()
    def epires_export_graph(project_name: str = "epires") -> str:
        """Export the entire research graph, evidence ledger, relations, and traces into a portable JSON bundle with SHA256 checksum."""
        from epires_core.importer import export_graph_bundle

        bundle = export_graph_bundle(store=store, project_name=project_name)
        return json.dumps(bundle, indent=2, ensure_ascii=False)

    @mcp.tool()
    def epires_import_graph(bundle_json: str, upsert: bool = True) -> str:
        """Import a research graph JSON bundle into the local database."""
        from epires_core.importer import import_graph_bundle

        bundle = json.loads(bundle_json)
        res = import_graph_bundle(store=store, bundle=bundle, upsert=upsert)
        return json.dumps(res, indent=2)

    @mcp.tool()
    def epires_query_graph(
        status: Optional[str] = None,
        h_id: Optional[str] = None,
        compact: bool = True,
    ) -> str:
        """Query hypotheses in the research graph by status (PROPOSED, CONFIRMED, FALSIFIED, BLOCKED) or ID.

        compact: If True (default), returns compact summary (id, title, status, level, parents) without verbose mechanisms.
        """
        if h_id:
            h = store.get_hypothesis(h_id)
            if not h:
                return f"Hypothesis '{h_id}' not found."
            evidence = store.get_evidence_for_hypothesis(h_id)
            return json.dumps(
                {"hypothesis": h.model_dump(), "evidence": [e.model_dump() for e in evidence]},
                indent=2,
                ensure_ascii=False,
            )

        stat_enum = HypothesisStatus(status) if status else None
        hypotheses = store.list_hypotheses(status=stat_enum)
        summary_list = []
        for h in hypotheses:
            if compact:
                summary_list.append(
                    {
                        "id": h.id,
                        "title": h.title,
                        "status": h.status.value,
                        "level": h.current_evidence_level.value,
                        "parents": h.parent_ids,
                        "tags": h.tags,
                    }
                )
            else:
                summary_list.append(
                    {
                        "id": h.id,
                        "title": h.title,
                        "a_priori_mechanism": h.a_priori_mechanism,
                        "falsification_criteria": h.falsification_criteria,
                        "status": h.status.value,
                        "current_level": h.current_evidence_level.value,
                        "target_level": h.target_evidence_level.value,
                        "parents": h.parent_ids,
                        "tags": h.tags,
                    }
                )
        return json.dumps(summary_list, indent=2, ensure_ascii=False)

    @mcp.tool()
    def epires_compute_gate(
        hypothesis_id: str,
        results_path: Optional[str] = None,
        metric_name: Optional[str] = None,
        metric_value: Optional[float] = None,
        delta_vs_baseline: Optional[float] = None,
        ci_95_lower: Optional[float] = None,
        ci_95_upper: Optional[float] = None,
        metrics_json: Optional[str] = None,
    ) -> str:
        """Automatically evaluate experiment results / bootstrap CI against hypothesis falsification criteria and statistical gates.

        Accepts either results_path (path to results.json), metrics_json (JSON string), or direct metric fields.
        Returns a structured verdict (PASS, FALSIFY, INCONCLUSIVE_NOISE) and actionable recommendations.
        """
        h = store.get_hypothesis(hypothesis_id)
        if not h:
            return json.dumps({"verdict": "ERROR", "reason": f"Hypothesis '{hypothesis_id}' not found"}, indent=2)

        payload: Dict[str, Any] = {}
        if results_path:
            payload = results_path  # evaluate_result_gate handles path
        elif metrics_json:
            try:
                payload = json.loads(metrics_json)
            except Exception as e:
                return json.dumps({"verdict": "ERROR", "reason": f"Invalid metrics_json: {e}"}, indent=2)
        else:
            payload = {
                "metric_name": metric_name,
                "metric_value": metric_value,
                "delta_vs_baseline": delta_vs_baseline,
                "ci_95_lower": ci_95_lower,
                "ci_95_upper": ci_95_upper,
            }

        from epires_core.gates import evaluate_result_gate

        res = evaluate_result_gate(hypothesis=h, results=payload)
        return json.dumps(res, indent=2, ensure_ascii=False)

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
    def epires_export_mermaid_dag(
        root_id: Optional[str] = None,
        depth: int = -1,
        frontier_only: bool = False,
        status_filter: Optional[Union[List[str], str]] = None,
    ) -> str:
        """Export the hypothesis dependency DAG as Mermaid markdown for visualization.

        root_id: Optional root hypothesis ID to export only its connected subtree / neighborhood.
        depth: Maximum hop depth from root_id (-1 for all reachable nodes).
        frontier_only: If True, only includes active hypotheses and their immediate parents.
        status_filter: Optional list or comma-separated string of statuses (e.g. 'CONFIRMED,IN_PROGRESS').
        """
        statuses = None
        if status_filter:
            if isinstance(status_filter, str):
                statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
            else:
                statuses = status_filter

        return store.export_mermaid_dag(
            root_id=root_id,
            depth=depth,
            frontier_only=frontier_only,
            statuses=statuses,
        )

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
            action=action, summary=summary, h_tag=h_tag, agent_role=agent_role, details=parsed_details
        )
        return f"Logged trace entry #{entry.id or 'auto'}: [{entry.action}] {entry.summary}"

    @mcp.tool()
    def audit_hypothesis(hypothesis_id: str) -> str:
        """Run an audit pass over a hypothesis (checks invariants, provenance, and ledger consistency)."""
        return json.dumps(store.audit_pass(hypothesis_id), indent=2)

    @mcp.tool()
    def algedonic_check(n_failures_threshold: int = 3) -> str:
        """Check algedonic triggers (pain signals) across the graph, filtered by failure threshold."""
        triggers = [t for t in store.check_algedonic() if t.get("n_failures", 0) >= n_failures_threshold]
        return json.dumps(triggers, indent=2)

    @mcp.tool()
    def algedonic_freeze(node_id: str) -> str:
        """Freeze a hypothesis branch (cascade FROZEN status down the DAG subtree)."""
        from epires_core.algedonic import freeze_branch

        frozen = freeze_branch(node_id, store)
        return f"Frozen branch rooted at {node_id}: {', '.join(frozen)}"

    @mcp.tool()
    def score_experiments(candidates: List[Dict[str, Any]], q: Dict[str, float]) -> str:
        """Score candidate experiment configs against a quality weight vector q."""
        ranked = store.score_experiments(candidates, q)
        return json.dumps([{"id": cid, "score": round(score, 4)} for cid, score in ranked], indent=2)

    @mcp.tool()
    def calibrated_p(agent_id: str, stated_p: float) -> str:
        """Compute the calibration-corrected probability for an agent's stated probability."""
        return json.dumps(
            {"agent_id": agent_id, "stated_p": stated_p, "calibrated_p": store.calibrated_p(agent_id, stated_p)}
        )

    @mcp.tool()
    def pheromone_rank() -> str:
        """Rank hypotheses by stigmergic pheromone weight (reinforcement from activity)."""
        from epires_core.stigmergy import pheromone_weight

        ranked = store.pheromone_rank()
        return json.dumps(
            [{"id": h.id, "title": h.title, "weight": round(pheromone_weight(h.id, store), 4)} for h in ranked],
            indent=2,
            ensure_ascii=False,
        )

    @mcp.tool()
    def compute_evidence_level(evidence_ids: List[str], hypothesis_id: str) -> str:
        """Recompute the aggregated EvidenceLevel for a hypothesis from specific evidence claim IDs."""
        from epires_core.gates import compute_level

        hypothesis = store.get_hypothesis(hypothesis_id)
        if not hypothesis:
            return f"Hypothesis '{hypothesis_id}' not found."
        evidence = []
        for ev_id in evidence_ids:
            ev = store.get_evidence(ev_id)
            if not ev:
                return f"Evidence '{ev_id}' not found."
            evidence.append(ev)
        level = compute_level(evidence, hypothesis)
        return json.dumps({"hypothesis_id": hypothesis_id, "evidence_count": len(evidence), "level": level.value})

    @mcp.tool()
    def s3_audit_confirmed() -> str:
        """Run the independent S3* auditor over all CONFIRMED hypotheses."""
        from epires_core.auditor import audit_confirmed

        return json.dumps(audit_confirmed(store), indent=2)

    return mcp


if __name__ == "__main__":
    import asyncio

    server = create_mcp_server()
    asyncio.run(server.run_stdio_async())
