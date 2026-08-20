"""Tests for FastAPI endpoints and MCP Server tools."""

import json
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from epires_core.models import HypothesisNode
from epires_core.store import EpiresStore
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
            "tags": ["fft"],
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
            "citation_or_path": "artifacts/fft.parquet",
        }
        ev_resp = client.post("/evidence", json=ev_data)
        assert ev_resp.status_code == 200

        # Mermaid DAG
        mermaid_resp = client.get("/graph/mermaid")
        assert mermaid_resp.status_code == 200
        assert "```mermaid" in mermaid_resp.json()["mermaid"]

        # Atlas projections share a versioned envelope and reflect persisted data.
        snapshot = client.get("/atlas/snapshot")
        assert snapshot.status_code == 200
        snapshot_data = snapshot.json()
        assert snapshot_data["schema_version"] == "atlas.v1"
        assert snapshot_data["generated_at"]
        assert snapshot_data["summary"]["hypotheses_total"] == 1
        assert snapshot_data["summary"]["evidence_total"] == 1
        assert snapshot_data["hypotheses"][0]["id"] == "H1"

        stratigraphy = client.get("/atlas/stratigraphy")
        assert stratigraphy.status_code == 200
        assert stratigraphy.json()["schema_version"] == "atlas.v1"
        assert {event["kind"] for event in stratigraphy.json()["events"]} >= {"hypothesis", "evidence", "trace"}

        coverage = client.get("/atlas/coverage?dimensions=Model,Feature")
        assert coverage.status_code == 200
        coverage_data = coverage.json()
        assert coverage_data["basis"] == "hypothesis_entities"
        assert coverage_data["dimensions"] == ["Model", "Feature"]
        assert coverage_data["summary"]["present_cells"] == 0
        assert coverage_data["summary"]["absent_cells"] == 0

        provenance = client.get("/atlas/provenance")
        assert provenance.status_code == 200
        provenance_data = provenance.json()
        assert provenance_data["schema_version"] == "atlas.v1"
        assert any(link["relation"] == "EVIDENCES" for link in provenance_data["links"])

        # A lower-level late claim cannot downgrade a promoted hypothesis.
        lower_ev = dict(ev_data)
        lower_ev.update({"id": "ev0", "evidence_level": "E0", "claim": "A later replay was recorded"})
        assert client.post("/evidence", json=lower_ev).status_code == 200
        assert client.get("/hypotheses/H1").json()["hypothesis"]["current_evidence_level"] == "E2"


def test_mcp_server_tools():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_mcp.db")
        trace_path = str(Path(tmpdir) / "trace.md")
        mcp = create_mcp_server(db_path=db_path, trace_md=trace_path)
        assert mcp.name == "epires"

        # Test tool manager has all 18 tools
        tool_names = [tool.name for tool in mcp._tool_manager.list_tools()]
        assert "epires_get_schema" in tool_names
        assert "epires_register_hypothesis" in tool_names
        assert "epires_register_experiment" in tool_names
        assert "epires_list_experiments" in tool_names
        assert "epires_log_evidence" in tool_names
        assert "epires_retract_evidence" in tool_names
        assert "epires_update_hypothesis" in tool_names
        assert "epires_bulk_import" in tool_names
        assert "epires_export_graph" in tool_names
        assert "epires_import_graph" in tool_names
        assert "epires_query_graph" in tool_names
        assert "epires_find_gaps" in tool_names
        assert "epires_associative_search" in tool_names
        assert "epires_export_mermaid_dag" in tool_names
        assert "epires_parallel_web_search" in tool_names
        assert "epires_parallel_extract" in tool_names
        assert "epires_record_trace" in tool_names
        assert "epires_system_status" in tool_names

        # Test schema retrieval
        get_schema = next(tool.fn for tool in mcp._tool_manager.list_tools() if tool.name == "epires_get_schema")
        schema_dict = json.loads(get_schema())
        assert schema_dict["title"] == "Epires Canonical Research Graph Schema"

        # Test tools setup
        log_ev = next(tool.fn for tool in mcp._tool_manager.list_tools() if tool.name == "epires_log_evidence")
        register = next(tool.fn for tool in mcp._tool_manager.list_tools() if tool.name == "epires_register_hypothesis")
        retract = next(tool.fn for tool in mcp._tool_manager.list_tools() if tool.name == "epires_retract_evidence")
        update_h = next(tool.fn for tool in mcp._tool_manager.list_tools() if tool.name == "epires_update_hypothesis")
        bulk_imp = next(tool.fn for tool in mcp._tool_manager.list_tools() if tool.name == "epires_bulk_import")
        export_g = next(tool.fn for tool in mcp._tool_manager.list_tools() if tool.name == "epires_export_graph")
        reg_exp = next(tool.fn for tool in mcp._tool_manager.list_tools() if tool.name == "epires_register_experiment")
        list_exp = next(tool.fn for tool in mcp._tool_manager.list_tools() if tool.name == "epires_list_experiments")

        # 1. Register hypothesis first
        register(id="H-TEST-MCP", title="MCP test", a_priori_mechanism="math", falsification_criteria="loss > 1")

        # 2. Register experiment linked to hypothesis
        exp_res = reg_exp(hypothesis_id="H-TEST-MCP", name="Smoke run", script_path="train.py", metrics={"rmsle": 1.23})
        assert "Successfully registered experiment" in exp_res
        exps_json = list_exp(hypothesis_id="H-TEST-MCP")
        assert "Smoke run" in exps_json
        log_ev(hypothesis_id="H-TEST-MCP", claim="Erroneous fail", evidence_level="E3", falsification_triggered=True)
        query = next(tool.fn for tool in mcp._tool_manager.list_tools() if tool.name == "epires_query_graph")
        res1 = json.loads(query(h_id="H-TEST-MCP"))
        assert res1["hypothesis"]["status"] == "FALSIFIED"

        ev_id = res1["evidence"][0]["id"]
        retract_msg = retract(evidence_id=ev_id, reason="Correction of benchmark error")
        assert "successfully retracted" in retract_msg

        res2 = json.loads(query(h_id="H-TEST-MCP"))
        assert res2["hypothesis"]["status"] == "PROPOSED"
        assert res2["hypothesis"]["current_evidence_level"] == "E0"

        # Test epires_update_hypothesis (e.g. mark REFINED)
        up_msg = update_h(id="H-TEST-MCP", status="REFINED", target_evidence_level="E4")
        assert "Status is REFINED" in up_msg
        res3 = json.loads(query(h_id="H-TEST-MCP"))
        assert res3["hypothesis"]["status"] == "REFINED"
        assert res3["hypothesis"]["target_evidence_level"] == "E4"

        # Test bulk import via MCP
        bulk_payload = json.dumps(
            [
                {"id": "H-BULK-1", "title": "Bulk 1", "a_priori_mechanism": "m", "falsification_criteria": "f"},
                {"id": "H-BULK-2", "title": "Bulk 2", "a_priori_mechanism": "m", "falsification_criteria": "f"},
            ]
        )
        bulk_res = json.loads(bulk_imp(hypotheses_json=bulk_payload))
        assert bulk_res["hypotheses_ingested"] == 2

        # Test export graph via MCP
        bundle_out = json.loads(export_g(project_name="mcp-test"))
        assert bundle_out["schema_version"] == "epires.v1"
        assert bundle_out["counts"]["hypotheses"] >= 3


def test_mcp_entity_pairs_are_persisted_and_validated():
    with tempfile.TemporaryDirectory() as tmpdir:
        mcp = create_mcp_server(
            db_path=str(Path(tmpdir) / "test_mcp_entities.db"),
            trace_md=str(Path(tmpdir) / "trace.md"),
        )
        register = next(tool.fn for tool in mcp._tool_manager.list_tools() if tool.name == "epires_register_hypothesis")
        register(
            id="H-ENT",
            title="Entity pair test",
            a_priori_mechanism="A mechanism",
            falsification_criteria="A criterion",
            entity_types=["Model", "Feature"],
            entity_values=["CatBoost", "FFT"],
        )
        # The closure's store is private, so query through the MCP graph tool.
        query = next(tool.fn for tool in mcp._tool_manager.list_tools() if tool.name == "epires_query_graph")
        result = json.loads(query(h_id="H-ENT"))
        assert result["hypothesis"]["entities"] == [
            {"type": "Model", "value": "CatBoost"},
            {"type": "Feature", "value": "FFT"},
        ]
        try:
            register(
                id="H-BAD",
                title="Bad entity pair",
                a_priori_mechanism="A mechanism",
                falsification_criteria="A criterion",
                entity_types=["Model"],
                entity_values=[],
            )
        except ValueError as exc:
            assert "same number" in str(exc)
        else:
            raise AssertionError("MCP accepted entity lists of different lengths")


def test_dag_cycle_prevention():
    """Verify that circular dependencies (A -> B -> A) are strictly blocked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        store = EpiresStore(db_path=db_path)

        # 1. Register H1
        store.register_hypothesis(
            HypothesisNode(id="H1", title="Hypo 1", a_priori_mechanism="m1", falsification_criteria="f1", parent_ids=[])
        )

        # 2. Register H2 depending on H1
        store.register_hypothesis(
            HypothesisNode(
                id="H2", title="Hypo 2", a_priori_mechanism="m2", falsification_criteria="f2", parent_ids=["H1"]
            )
        )

        # 3. Attempting to make H1 depend on H2 must raise ValueError (Cycle!)
        try:
            store.register_hypothesis(
                HypothesisNode(
                    id="H1",
                    title="Hypo 1 updated",
                    a_priori_mechanism="m1",
                    falsification_criteria="f1",
                    parent_ids=["H2"],
                )
            )
            raise AssertionError("Store allowed directed cycle in DAG!")
        except ValueError as exc:
            assert "cycle detected" in str(exc).lower()

        # 4. Self-dependency must also be blocked
        try:
            store.register_hypothesis(
                HypothesisNode(
                    id="H3", title="Hypo 3", a_priori_mechanism="m3", falsification_criteria="f3", parent_ids=["H3"]
                )
            )
            raise AssertionError("Store allowed self-dependency cycle in DAG!")
        except ValueError as exc:
            assert "cycle detected" in str(exc).lower()


def test_artifact_security_sandbox():
    """Verify path traversal attacks are blocked on /artifacts/{path}."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app = create_app(db_path=str(Path(tmpdir) / "test.db"))
        client = TestClient(app)

        # Directory escape attempt
        resp = client.get("/artifacts/../../etc/passwd")
        assert resp.status_code in [403, 404]
