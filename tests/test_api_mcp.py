"""Tests for FastAPI endpoints and MCP Server tools."""

import json
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from server.app import create_app
from server.mcp_server import create_mcp_server


def test_fastapi_endpoints():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_api.db")
        trace_path = str(Path(tmpdir) / "trace.md")
        app = create_app(db_path=db_path, trace_md=trace_path)
        client = TestClient(app)

        # Dashboard SPA
        resp = client.get("/")
        assert resp.status_code == 200
        assert "EPIRES" in resp.text

        # Health
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Register Hypothesis
        h_data = {
            "id": "H1",
            "title": "Fourier frequency decomposition baseline",
            "a_priori_mechanism": "FFT extracts seasonal periodicity",
            "falsification_criteria": "RMSLE > 1.85",
            "target_evidence_level": "E3",
            "current_evidence_level": "E0",
            "status": "PROPOSED",
            "parent_ids": [],
            "entities": [{"type": "Feature", "value": "FFT"}],
            "tags": ["fft"]
        }
        post_resp = client.post("/hypotheses", json=h_data)
        assert post_resp.status_code == 200
        assert post_resp.json()["id"] == "H1"

        # List
        list_resp = client.get("/hypotheses")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

        # Evidence
        ev_data = {
            "id": "ev1",
            "hypothesis_id": "H1",
            "evidence_level": "E2",
            "source_confidence": "V",
            "claim": "FFT pass on fold 1 with RMSLE 1.72",
            "metric_name": "RMSLE",
            "metric_value": 1.72,
            "falsification_triggered": False,
            "citation_or_path": "artifacts/fft.parquet"
        }
        ev_resp = client.post("/evidence", json=ev_data)
        assert ev_resp.status_code == 200

        # Mermaid DAG
        mermaid_resp = client.get("/graph/mermaid")
        assert mermaid_resp.status_code == 200
        assert "```mermaid" in mermaid_resp.json()["mermaid"]


def test_mcp_server_tools():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_mcp.db")
        trace_path = str(Path(tmpdir) / "trace.md")
        mcp = create_mcp_server(db_path=db_path, trace_md=trace_path)
        assert mcp.name == "epires"

        # Test tool manager has all 10 tools
        tool_names = [tool.name for tool in mcp._tool_manager.list_tools()]
        assert "epires_register_hypothesis" in tool_names
        assert "epires_log_evidence" in tool_names
        assert "epires_query_graph" in tool_names
        assert "epires_find_gaps" in tool_names
        assert "epires_associative_search" in tool_names
        assert "epires_export_mermaid_dag" in tool_names
        assert "epires_parallel_web_search" in tool_names
        assert "epires_parallel_extract" in tool_names
        assert "epires_record_trace" in tool_names
        assert "epires_system_status" in tool_names
