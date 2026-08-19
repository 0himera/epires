"""FastAPI Application for Epires Research Engine."""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from epires_core.models import (
    EvidenceClaim,
    GapQuery,
    HypothesisNode,
    HypothesisStatus,
    SearchQuery,
    TraceEntry,
)
from epires_core.store import EpiresStore
from epires_core.tracer import AutoTracer
from tools.web_search import ParallelWebSearcher


class WebSearchRequest(BaseModel):
    queries: List[str]
    objective: Optional[str] = None
    mode: str = "fast"
    max_chars: Optional[int] = None


def create_app(db_path: str = ".epires/hypotheses.db", trace_md: str = "docs/agent-trace.md") -> FastAPI:
    app = FastAPI(
        title="Epires Research Engine",
        version="0.1.0",
        description="Minimalist Cybernetic Research Engine: VSA Hypergraph, Hypothesis Falsification DAG & Automated Tracing"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = EpiresStore(db_path=db_path)
    tracer = AutoTracer(store=store, trace_md_path=trace_md)
    web_searcher = ParallelWebSearcher()

    @app.get("/health")
    def health_check() -> Dict[str, Any]:
        hypotheses = store.list_hypotheses()
        status_counts = {}
        for h in hypotheses:
            status_counts[h.status.value] = status_counts.get(h.status.value, 0) + 1
        return {
            "status": "ok",
            "hypotheses_total": len(hypotheses),
            "status_distribution": status_counts,
            "traces_total": len(store.list_traces(limit=1000))
        }

    # -------------------------------------------------------------------------
    # Hypotheses Endpoints
    # -------------------------------------------------------------------------
    @app.post("/hypotheses", response_model=HypothesisNode)
    def register_hypothesis(h: HypothesisNode) -> HypothesisNode:
        saved = store.register_hypothesis(h)
        return saved

    @app.get("/hypotheses", response_model=List[HypothesisNode])
    def list_hypotheses(status: Optional[HypothesisStatus] = None) -> List[HypothesisNode]:
        return store.list_hypotheses(status=status)

    @app.get("/hypotheses/{h_id}")
    def get_hypothesis_detail(h_id: str) -> Dict[str, Any]:
        h = store.get_hypothesis(h_id)
        if not h:
            raise HTTPException(status_code=404, detail=f"Hypothesis '{h_id}' not found")
        evidence = store.get_evidence_for_hypothesis(h_id)
        return {
            "hypothesis": h,
            "evidence": evidence
        }

    # -------------------------------------------------------------------------
    # Evidence & Falsification
    # -------------------------------------------------------------------------
    @app.post("/evidence")
    def log_evidence(ev: EvidenceClaim) -> Dict[str, Any]:
        saved_ev, blocked_children = store.log_evidence(ev)
        return {
            "evidence": saved_ev,
            "blocked_children": blocked_children
        }

    # -------------------------------------------------------------------------
    # VSA Search & Gap Analysis
    # -------------------------------------------------------------------------
    @app.post("/search")
    def associative_search(sq: SearchQuery) -> List[Dict[str, Any]]:
        results = store.search(sq)
        return [
            {"hypothesis": h, "similarity_score": score}
            for h, score in results
        ]

    @app.post("/gaps")
    def find_gaps(gq: GapQuery) -> List[Dict[str, Any]]:
        return store.find_gaps(gq)

    # -------------------------------------------------------------------------
    # Graph Visualization & Tracing
    # -------------------------------------------------------------------------
    @app.get("/graph/mermaid")
    def export_mermaid() -> Dict[str, str]:
        mermaid_code = store.export_mermaid_dag()
        return {"mermaid": mermaid_code}

    @app.get("/traces", response_model=List[TraceEntry])
    def list_traces(limit: int = Query(default=50, ge=1, le=500)) -> List[TraceEntry]:
        return store.list_traces(limit=limit)

    @app.post("/traces", response_model=TraceEntry)
    def record_trace(entry: TraceEntry) -> TraceEntry:
        return tracer.record(
            action=entry.action,
            summary=entry.summary,
            h_tag=entry.h_tag,
            agent_role=entry.agent_role,
            details=entry.details
        )

    # -------------------------------------------------------------------------
    # Parallel Web Search
    # -------------------------------------------------------------------------
    @app.post("/search/web")
    async def parallel_web_search(req: WebSearchRequest) -> Dict[str, Any]:
        return await web_searcher.asearch(
            queries=req.queries,
            objective=req.objective,
            mode=req.mode,
            max_chars=req.max_chars
        )

    return app


app = create_app()
