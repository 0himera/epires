"""Tests for AutoTracer."""

import tempfile
from pathlib import Path
from epires_core.store import EpiresStore
from epires_core.tracer import AutoTracer


def test_autotracer_records_sqlite_and_markdown():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        trace_path = Path(tmpdir) / "agent-trace.md"
        
        store = EpiresStore(db_path=db_path, vsa_dim=1000)
        tracer = AutoTracer(store=store, trace_md_path=trace_path)

        assert trace_path.exists()
        initial_content = trace_path.read_text(encoding="utf-8")
        assert "Agent Trace & Epistemic Log" in initial_content

        # Record action
        entry = tracer.record(
            action="FALSIFY",
            summary="SDM memory rejected vs kNN [E3, V]",
            h_tag="H3",
            agent_role="Lead-PI",
            details={"ci_delta": 0.0}
        )

        # Check SQLite
        traces = store.list_traces()
        assert len(traces) == 1
        assert traces[0].action == "FALSIFY"
        assert traces[0].h_tag == "H3"

        # Check Markdown file
        md_content = trace_path.read_text(encoding="utf-8")
        assert "`FALSIFY`" in md_content
        assert "`H3`" in md_content
        assert "SDM memory rejected" in md_content
