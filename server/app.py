"""FastAPI Application for Epires Research Engine & Web Dashboard."""

from __future__ import annotations
from datetime import datetime, timezone
import itertools
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from epires_core.config import EpiresProjectConfig, find_project_root
from epires_core.models import (
    EvidenceClaim,
    ExperimentNode,
    GapQuery,
    HypothesisNode,
    HypothesisStatus,
    SearchQuery,
    TraceEntry,
)
from epires_core.store import EpiresStore
from epires_core.tracer import AutoTracer
from tools.web_search import ParallelWebSearcher


class WebSocketHub:
    """Manages active browser WebSocket connections for real-time delta pushes."""

    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active_connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active_connections:
            self.active_connections.remove(ws)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        for ws in list(self.active_connections):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(ws)


ws_hub = WebSocketHub()


class WebSearchRequest(BaseModel):
    queries: List[str]
    objective: Optional[str] = None
    mode: str = "fast"
    max_chars: Optional[int] = None


def create_app(db_path: str = ".epires/hypotheses.db", trace_md: str = "docs/agent-trace.md") -> FastAPI:
    app = FastAPI(
        title="Epires Research Engine",
        version="0.1.0",
        description="Epistemic Research Engine: VSA Hypergraph, Hypothesis Falsification DAG & Automated Tracing",
    )

    # ponytail: CORS from env; * -> credentials False per spec
    cors_raw = os.getenv("EPIRES_CORS_ORIGINS", "*").strip()
    if cors_raw == "*" or cors_raw == "":
        cors_origins = ["*"]
        cors_credentials = False
    else:
        cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
        cors_credentials = True
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # ponytail: bearer auth if EPIRES_API_TOKEN set — minimal middleware
    _api_token = os.getenv("EPIRES_API_TOKEN")

    @app.middleware("http")
    async def _auth_guard(request: Request, call_next):  # type: ignore
        if _api_token and request.method in ("POST", "DELETE"):
            if request.url.path not in ("/health",):
                auth = request.headers.get("authorization", "")
                if auth != f"Bearer {_api_token}":
                    return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        return await call_next(request)

    store = EpiresStore(db_path=db_path)
    tracer = AutoTracer(store=store, trace_md_path=trace_md)
    web_searcher = ParallelWebSearcher()

    def atlas_envelope(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Wrap read-only Atlas resources in the versioned response envelope."""
        return {
            "schema_version": "atlas.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **payload,
        }

    def atlas_records() -> Dict[str, Any]:
        """Read a consistent set of current records for Atlas projections."""
        hypotheses = store.list_hypotheses()
        evidence = store.list_evidence()
        relations = store.list_relations()
        experiments = store.list_experiments()
        traces = store.list_traces(limit=500)
        status_distribution: Dict[str, int] = {}
        level_distribution: Dict[str, int] = {}
        for hypothesis in hypotheses:
            status_distribution[hypothesis.status.value] = status_distribution.get(hypothesis.status.value, 0) + 1
            level_distribution[hypothesis.current_evidence_level.value] = (
                level_distribution.get(hypothesis.current_evidence_level.value, 0) + 1
            )
        return {
            "hypotheses": hypotheses,
            "evidence": evidence,
            "relations": relations,
            "experiments": experiments,
            "traces": traces,
            "summary": {
                "hypotheses_total": len(hypotheses),
                "evidence_total": len(evidence),
                "relations_total": len(relations),
                "experiments_total": len(experiments),
                "traces_total": len(traces),
                "status_distribution": status_distribution,
                "evidence_level_distribution": level_distribution,
            },
        }

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # -------------------------------------------------------------------------
    # Web Dashboard SPA
    # -------------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    @app.get("/dashboard", response_class=HTMLResponse)
    def serve_dashboard() -> FileResponse:
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse("<h1>Epires Research Engine API is running.</h1>")

    @app.get("/config")
    def get_project_config() -> Dict[str, Any]:
        """Returns dynamic project profile, domain, and metric settings from .epires/config.json."""
        conf = EpiresProjectConfig.load()
        return conf.model_dump()

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
            "traces_total": len(store.list_traces(limit=1000)),
        }

    @app.get("/version")
    @app.get("/atlas/version")
    def get_state_version() -> Dict[str, Any]:
        """Lightweight fingerprint endpoint for ultra-low overhead polling check."""
        p = Path(db_path)
        mtime = p.stat().st_mtime if p.exists() else 0
        h_list = store.list_hypotheses()
        t_list = store.list_traces(limit=10)
        return {
            "version": f"{mtime}_{len(h_list)}_{len(t_list)}",
            "db_mtime": mtime,
            "hypotheses_count": len(h_list),
            "traces_count": len(t_list),
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket for live zero-latency event streaming and instant delta notifications."""
        await ws_hub.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            ws_hub.disconnect(websocket)
        except Exception:
            ws_hub.disconnect(websocket)

    # -------------------------------------------------------------------------
    # Research Atlas projections (read-only, versioned for dashboard clients)
    # -------------------------------------------------------------------------
    @app.get("/atlas/snapshot")
    def atlas_snapshot() -> Dict[str, Any]:
        """Return the current research graph and its persisted evidence ledger."""
        records = atlas_records()
        return atlas_envelope(
            {
                "summary": records["summary"],
                "hypotheses": records["hypotheses"],
                "relations": records["relations"],
                "evidence": records["evidence"],
                "experiments": records["experiments"],
            }
        )

    @app.get("/atlas/stratigraphy")
    def atlas_stratigraphy() -> Dict[str, Any]:
        """Return chronological research events from persisted records.

        The projection deliberately does not infer agent actions that were not
        written to the hypothesis/evidence/trace tables.
        """
        records = atlas_records()
        events: List[Dict[str, Any]] = []
        for hypothesis in records["hypotheses"]:
            events.append(
                {
                    "kind": "hypothesis",
                    "timestamp": hypothesis.created_at,
                    "id": hypothesis.id,
                    "hypothesis_id": hypothesis.id,
                    "status": hypothesis.status.value,
                    "evidence_level": hypothesis.current_evidence_level.value,
                    "title": hypothesis.title,
                }
            )
        for evidence in records["evidence"]:
            events.append(
                {
                    "kind": "evidence",
                    "timestamp": evidence.timestamp,
                    "id": evidence.id,
                    "hypothesis_id": evidence.hypothesis_id,
                    "evidence_level": evidence.evidence_level.value,
                    "source_confidence": evidence.source_confidence.value,
                    "falsification_triggered": evidence.falsification_triggered,
                    "metric_name": evidence.metric_name,
                    "metric_value": evidence.metric_value,
                    "claim": evidence.claim,
                }
            )
        for trace in records["traces"]:
            events.append(
                {
                    "kind": "trace",
                    "timestamp": trace.timestamp,
                    "id": trace.id,
                    "hypothesis_id": trace.h_tag,
                    "action": trace.action,
                    "agent_role": trace.agent_role,
                    "summary": trace.summary,
                    "details": trace.details,
                }
            )

        def chronological_key(event: Dict[str, Any]) -> tuple[int, datetime, str, str]:
            """Sort ISO-8601 timestamps by instant, retaining malformed legacy rows."""
            raw = event["timestamp"] or ""
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return (0, parsed.astimezone(timezone.utc), event["kind"], str(event["id"]))
            except (TypeError, ValueError):
                return (1, datetime.max.replace(tzinfo=timezone.utc), event["kind"], str(event["id"]))

        events.sort(key=chronological_key)
        return atlas_envelope(
            {
                "summary": {
                    "events_total": len(events),
                    "hypotheses_total": len(records["hypotheses"]),
                    "evidence_total": len(records["evidence"]),
                    "traces_total": len(records["traces"]),
                },
                "events": events,
            }
        )

    @app.get("/atlas/coverage")
    def atlas_coverage(
        dimensions: Optional[str] = Query(default=None, description="Comma-separated entity dimensions"),
    ) -> Dict[str, Any]:
        """Project entity-combination coverage from hypothesis declarations.

        This is intentionally *not* experiment coverage: no experiment rows are
        required and no unsupported performance claim is made.
        """
        if dimensions is None or not dimensions.strip():
            requested_dimensions = ["Model", "Feature", "Regime"]
        else:
            requested_dimensions = [part.strip() for part in dimensions.split(",") if part.strip()]
        if not requested_dimensions:
            raise HTTPException(status_code=400, detail="dimensions must contain at least one dimension")
        if len(set(requested_dimensions)) != len(requested_dimensions):
            raise HTTPException(status_code=400, detail="dimensions must not contain duplicates")
        if len(requested_dimensions) > 6:
            raise HTTPException(status_code=400, detail="at most 6 dimensions are supported")

        hypotheses = store.list_hypotheses()
        dimension_values: Dict[str, List[str]] = {dimension: [] for dimension in requested_dimensions}
        combo_hypotheses: Dict[tuple[str, ...], List[str]] = {}
        for hypothesis in hypotheses:
            entity_map: Dict[str, set[str]] = {}
            for entity in hypothesis.entities:
                entity_map.setdefault(entity.type, set()).add(entity.value)
            for dimension in requested_dimensions:
                for value in entity_map.get(dimension, set()):
                    if value not in dimension_values[dimension]:
                        dimension_values[dimension].append(value)
            if all(dimension in entity_map for dimension in requested_dimensions):
                for combo in itertools.product(*(sorted(entity_map[dimension]) for dimension in requested_dimensions)):
                    combo_hypotheses.setdefault(combo, []).append(hypothesis.id)
        for values in dimension_values.values():
            values.sort()

        cells: List[Dict[str, Any]] = []
        value_sets = [dimension_values[dimension] for dimension in requested_dimensions]
        possible_cells = math.prod(len(values) for values in value_sets)
        if possible_cells > 5_000:
            raise HTTPException(
                status_code=400,
                detail="requested dimensions produce more than 5000 cells; narrow the dimensions",
            )
        for combo in itertools.product(*value_sets) if all(value_sets) else []:
            hypothesis_ids = sorted(combo_hypotheses.get(combo, []))
            count = len(hypothesis_ids)
            cells.append(
                {
                    "combination": dict(zip(requested_dimensions, combo)),
                    "hypothesis_ids": hypothesis_ids,
                    "hypothesis_count": count,
                    "presence": "PRESENT" if count else "ABSENT",
                }
            )
        present = sum(cell["presence"] == "PRESENT" for cell in cells)
        return atlas_envelope(
            {
                "basis": "hypothesis_entities",
                "dimensions": requested_dimensions,
                "dimension_values": dimension_values,
                "cells": cells,
                "summary": {
                    "hypotheses_considered": len(hypotheses),
                    "possible_cells": len(cells),
                    "present_cells": present,
                    "absent_cells": len(cells) - present,
                },
            }
        )

    def get_artifacts_dir() -> Optional[Path]:
        conf = EpiresProjectConfig.load()
        art_dir_setting = conf.paths.artifacts_dir if conf and conf.paths and conf.paths.artifacts_dir else "artifacts"
        project_root = find_project_root()

        candidates = [
            project_root / art_dir_setting,
            project_root / "artifacts",
            project_root / ".epires" / "artifacts",
        ]
        for cand in candidates:
            if cand and cand.exists() and cand.is_dir():
                return cand.resolve()
        return (project_root / art_dir_setting).resolve()

    @app.get("/atlas/provenance")
    def atlas_provenance() -> Dict[str, Any]:
        """Expose persisted source, artifact, relation, and trace provenance."""
        records = atlas_records()
        links: List[Dict[str, Any]] = []

        # Scan filesystem artifacts from configured directory
        art_dir = get_artifacts_dir()
        fs_artifacts: List[Dict[str, Any]] = []
        if art_dir and art_dir.exists() and art_dir.is_dir():
            for p in sorted(art_dir.glob("**/*")):
                if p.is_file() and not p.name.startswith("."):
                    rel_path = str(p.relative_to(art_dir))
                    fs_artifacts.append(
                        {
                            "name": p.name,
                            "path": rel_path,
                            "size_bytes": p.stat().st_size,
                            "mtime": p.stat().st_mtime,
                        }
                    )

        for evidence in records["evidence"]:
            links.append(
                {
                    "source_type": "evidence",
                    "source_id": evidence.id,
                    "target_type": "hypothesis",
                    "target_id": evidence.hypothesis_id,
                    "relation": "EVIDENCES",
                }
            )
            if evidence.citation_or_path:
                links.append(
                    {
                        "source_type": "evidence",
                        "source_id": evidence.id,
                        "target_type": "citation",
                        "target_id": evidence.citation_or_path,
                        "relation": "CITES",
                    }
                )
            if evidence.artifact_hash:
                links.append(
                    {
                        "source_type": "evidence",
                        "source_id": evidence.id,
                        "target_type": "artifact",
                        "target_id": evidence.artifact_hash,
                        "relation": "HAS_ARTIFACT",
                    }
                )
        for experiment in records["experiments"]:
            links.append(
                {
                    "source_type": "experiment",
                    "source_id": experiment.id,
                    "target_type": "hypothesis",
                    "target_id": experiment.hypothesis_id,
                    "relation": "TESTS",
                }
            )
            links.append(
                {
                    "source_type": "experiment",
                    "source_id": experiment.id,
                    "target_type": "script",
                    "target_id": experiment.script_path,
                    "relation": "USES_SCRIPT",
                }
            )
            if experiment.commit_hash:
                links.append(
                    {
                        "source_type": "experiment",
                        "source_id": experiment.id,
                        "target_type": "commit",
                        "target_id": experiment.commit_hash,
                        "relation": "AT_COMMIT",
                    }
                )
            for artifact_path in experiment.artifact_paths:
                links.append(
                    {
                        "source_type": "experiment",
                        "source_id": experiment.id,
                        "target_type": "artifact",
                        "target_id": artifact_path,
                        "relation": "PRODUCES",
                    }
                )
        for relation in records["relations"]:
            links.append(
                {
                    "source_type": "hypothesis",
                    "source_id": relation.source_id,
                    "target_type": "hypothesis",
                    "target_id": relation.target_id,
                    "relation": relation.relation_type.value,
                    "metadata": relation.metadata,
                }
            )
        for trace in records["traces"]:
            if trace.h_tag:
                links.append(
                    {
                        "source_type": "trace",
                        "source_id": str(trace.id),
                        "target_type": "hypothesis",
                        "target_id": trace.h_tag,
                        "relation": "ABOUT",
                    }
                )

        db_artifacts = set()
        for ev in records["evidence"]:
            if ev.citation_or_path:
                db_artifacts.add(ev.citation_or_path)
            if ev.artifact_hash:
                db_artifacts.add(ev.artifact_hash)
        for exp in records["experiments"]:
            for ap in exp.artifact_paths:
                db_artifacts.add(ap)

        total_artifacts_count = max(
            len(fs_artifacts), len(db_artifacts), len(set(a["path"] for a in fs_artifacts) | db_artifacts)
        )

        return atlas_envelope(
            {
                "basis": "persisted_store_records",
                "artifact_count": total_artifacts_count,
                "artifact_files": fs_artifacts,
                "hypotheses": records["hypotheses"],
                "evidence": records["evidence"],
                "experiments": records["experiments"],
                "relations": records["relations"],
                "traces": records["traces"],
                "links": links,
            }
        )

    @app.get("/artifacts")
    def list_artifacts() -> Dict[str, Any]:
        """List all discovered research artifacts from filesystem and ledger."""
        art_dir = get_artifacts_dir()
        files = []
        if art_dir and art_dir.exists() and art_dir.is_dir():
            for p in sorted(art_dir.glob("**/*")):
                if p.is_file() and not p.name.startswith("."):
                    rel_path = str(p.relative_to(art_dir))
                    files.append(
                        {
                            "name": p.name,
                            "path": rel_path,
                            "size_bytes": p.stat().st_size,
                            "mtime": p.stat().st_mtime,
                        }
                    )
        return {"artifacts": files, "count": len(files)}

    @app.get("/artifacts/{artifact_path:path}")
    def get_artifact_content(artifact_path: str) -> Any:
        """Serve artifact file content directly with strict path traversal sandboxing."""
        art_dir = get_artifacts_dir()
        if not art_dir or not art_dir.exists():
            raise HTTPException(status_code=404, detail="Artifacts directory not found.")

        target = (art_dir / artifact_path).resolve()
        # Security: verify path does not escape the artifacts directory
        if not str(target).startswith(str(art_dir.resolve())) or not target.is_relative_to(art_dir.resolve()):
            raise HTTPException(status_code=403, detail="Access denied: path escapes artifacts directory.")

        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="Artifact not found.")

        return FileResponse(target)

    # -------------------------------------------------------------------------
    # Hypotheses Endpoints
    # -------------------------------------------------------------------------
    @app.post("/hypotheses", response_model=HypothesisNode)
    async def register_hypothesis(h: HypothesisNode) -> HypothesisNode:
        saved = store.register_hypothesis(h)
        await ws_hub.broadcast({"event": "HYPOTHESIS_UPDATED", "hypothesis_id": saved.id, "status": saved.status.value})
        return saved

    @app.get("/hypotheses", response_model=List[HypothesisNode])
    def list_hypotheses(status: Optional[HypothesisStatus] = None) -> List[HypothesisNode]:
        return store.list_hypotheses(status=status)

    @app.get("/hypotheses/{h_id}")
    def get_hypothesis_detail(h_id: str) -> Dict[str, Any]:
        h = store.get_hypothesis(h_id)
        if not h:
            raise HTTPException(status_code=404, detail=f"Hypothesis {h_id} not found")
        evidence = store.get_evidence_for_hypothesis(h_id)
        experiments = store.list_experiments(hypothesis_id=h_id)
        return {
            "hypothesis": h,
            "evidence": evidence,
            "experiments": experiments,
        }

    # -------------------------------------------------------------------------
    # Experiments Registry
    # -------------------------------------------------------------------------
    @app.post("/experiments", response_model=ExperimentNode)
    async def register_experiment(exp: ExperimentNode) -> ExperimentNode:
        saved = store.register_experiment(exp)
        await ws_hub.broadcast(
            {"event": "EXPERIMENT_REGISTERED", "experiment_id": saved.id, "hypothesis_id": saved.hypothesis_id}
        )
        return saved

    @app.get("/experiments", response_model=List[ExperimentNode])
    def list_experiments(hypothesis_id: Optional[str] = None) -> List[ExperimentNode]:
        return store.list_experiments(hypothesis_id=hypothesis_id)

    # -------------------------------------------------------------------------
    # Evidence & Falsification
    # -------------------------------------------------------------------------
    @app.post("/evidence")
    async def log_evidence(ev: EvidenceClaim) -> Dict[str, Any]:
        saved_ev, blocked_children = store.log_evidence(ev)
        await ws_hub.broadcast(
            {
                "event": "EVIDENCE_LOGGED",
                "evidence_id": saved_ev.id,
                "hypothesis_id": saved_ev.hypothesis_id,
                "falsification_triggered": saved_ev.falsification_triggered,
                "blocked_children": blocked_children,
            }
        )
        return {"evidence": saved_ev, "blocked_children": blocked_children}

    @app.get("/evidence/{evidence_id}")
    def get_evidence_detail(evidence_id: str) -> EvidenceClaim:
        ev = store.get_evidence(evidence_id)
        if not ev:
            raise HTTPException(status_code=404, detail=f"Evidence {evidence_id} not found")
        return ev

    @app.delete("/evidence/{evidence_id}")
    @app.post("/evidence/{evidence_id}/retract")
    async def retract_evidence(
        evidence_id: str,
        reason: str = Query(default="Retracted erroneous evidence claim"),
        agent_role: str = Query(default="Lead-PI"),
    ) -> Dict[str, Any]:
        retracted_ev, unblocked_children = store.retract_evidence(
            evidence_id=evidence_id, reason=reason, agent_role=agent_role
        )
        if not retracted_ev:
            raise HTTPException(status_code=404, detail=f"Evidence {evidence_id} not found")
        h = store.get_hypothesis(retracted_ev.hypothesis_id)
        await ws_hub.broadcast(
            {
                "event": "EVIDENCE_RETRACTED",
                "evidence_id": evidence_id,
                "hypothesis_id": retracted_ev.hypothesis_id,
                "unblocked_children": unblocked_children,
            }
        )
        return {
            "retracted_evidence": retracted_ev,
            "hypothesis": h,
            "unblocked_children": unblocked_children,
            "reason": reason,
        }

    # -------------------------------------------------------------------------
    # VSA Search & Gap Analysis
    # -------------------------------------------------------------------------
    @app.post("/search")
    def associative_search(sq: SearchQuery) -> List[Dict[str, Any]]:
        results = store.search(sq)
        return [{"hypothesis": h, "similarity_score": score} for h, score in results]

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

    @app.get("/audit/{h_id}")
    def audit_endpoint(h_id: str) -> Dict[str, Any]:
        return store.audit_pass(h_id)

    @app.get("/algedonic/check")
    def algedonic_check() -> List[Dict[str, Any]]:
        return store.check_algedonic()

    @app.post("/traces", response_model=TraceEntry)
    def record_trace(entry: TraceEntry) -> TraceEntry:
        return tracer.record(
            action=entry.action,
            summary=entry.summary,
            h_tag=entry.h_tag,
            agent_role=entry.agent_role,
            details=entry.details,
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
            max_chars=req.max_chars,
        )

    return app
