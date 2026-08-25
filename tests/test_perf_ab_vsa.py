"""Regression tests for the diagnostic-only VSA benchmark."""

from __future__ import annotations

import json

import pytest

from sandbox.perf_ab.vsa_diagnostics import (
    DiagnosticQuery,
    build_retrieval_corpus,
    build_retrieval_queries,
    build_two_hop_graph,
    evaluate_rankings,
    main,
    run_diagnostics,
)


def test_diagnostic_dataset_is_fixed_and_ground_truth_is_valid():
    documents = build_retrieval_corpus()
    queries = build_retrieval_queries()
    document_ids = {document.id for document in documents}

    assert len(documents) == 24
    assert len(document_ids) == len(documents)
    assert len(queries) == 12
    assert all(set(query.relevance).issubset(document_ids) for query in queries)
    assert documents == build_retrieval_corpus()
    assert queries == build_retrieval_queries()


def test_ranking_metrics_use_all_relevant_documents_and_graded_ndcg():
    query = DiagnosticQuery("Q", "unused", {"best": 3, "secondary": 1})
    result = evaluate_rankings({"Q": ["secondary", "best", "noise"]}, (query,), k=3)

    assert result["recall_at_k"] == 1.0
    assert result["mrr_at_k"] == 1.0
    assert 0.0 < result["ndcg_at_k"] < 1.0


def test_two_hop_graph_contains_branching_ground_truth():
    edges, queries = build_two_hop_graph()
    first_hop = {target for source, relation, target in edges if source == "C" and relation == "REFINES"}

    assert first_hop == {"M1", "M2", "M3"}
    assert any(query.id == "G02" for query in queries)


def test_run_diagnostics_reports_separate_methods_and_never_primary_score():
    result = run_diagnostics(dim=512, k=5, repeats=1)

    assert result["diagnostic_only"] is True
    assert result["included_in_primary_perf_score"] is False
    assert set(result["retrieval"]["methods"]) == {
        "lexical_fts5_bm25",
        "pure_vsa",
        "epires_hybrid_current",
    }
    assert set(result["two_hop"]["methods"]) == {
        "exact_bfs_reference",
        "current_dual_codebook_vsa",
    }
    for method in result["retrieval"]["methods"].values():
        assert set(method["quality"]) == {"recall_at_k", "mrr_at_k", "ndcg_at_k"}
        assert method["performance"]["estimated_resident_bytes"] > 0
        assert method["performance"]["hot_query_latency"]["samples"] == 12


def test_cli_prints_one_json_document(capsys: pytest.CaptureFixture[str]):
    assert main(["--dim", "512", "--k", "3", "--repeats", "1", "--indent", "0"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["benchmark"] == "epires_vsa_offline_diagnostics"
    assert output["config"]["dim"] == 512


@pytest.mark.parametrize("dim", [0, 7, 513])
def test_invalid_binary_dimensions_are_rejected(dim: int):
    with pytest.raises(ValueError, match="positive multiple of 8"):
        run_diagnostics(dim=dim, repeats=1)
