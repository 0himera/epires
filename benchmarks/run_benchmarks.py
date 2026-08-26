"""Fast Quantitative Benchmark and Evaluation Suite for Epires Research Harness."""

from __future__ import annotations
import random
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from epires_core.models import (
    Entity,
    EvidenceClaim,
    EvidenceLevel,
    HypothesisNode,
    HypothesisStatus,
    SearchQuery,
    SourceConfidence,
)
from epires_core.store import EpiresStore


def generate_synthetic_corpus(store: EpiresStore, n_items: int = 500) -> List[HypothesisNode]:
    """Generates a realistic scientific corpus with entity combinations and bulk inserts."""
    random.seed(42)
    models = ["LightGBM", "CatBoost", "XGBoost", "ResNet", "Transformer", "Linear", "RandomForest", "SVM"]
    features = ["FFT", "Wavelet", "Lag7", "Diff1", "RollingMean", "PCA", "TargetEncoding", "Quantile"]
    regimes = ["LowVolatility", "HighVolatility", "Trend", "Shock", "Holiday", "Seasonal"]

    corpus = []
    for i in range(1, n_items + 1):
        m = random.choice(models)
        f = random.choice(features)
        r = random.choice(regimes)
        status = random.choice(
            [
                HypothesisStatus.PROPOSED,
                HypothesisStatus.IN_PROGRESS,
                HypothesisStatus.CONFIRMED,
                HypothesisStatus.FALSIFIED,
            ]
        )
        level = random.choice([EvidenceLevel.E0, EvidenceLevel.E1, EvidenceLevel.E2, EvidenceLevel.E3])

        h = HypothesisNode(
            id=f"H-SYNTH-{i:04d}",
            title=f"{m} with {f} feature decomposition in {r} regime",
            a_priori_mechanism=f"Applying {f} to {m} captures spectral energy under {r} conditions with bounded variance.",
            falsification_criteria=f"Validation loss delta > {round(random.uniform(0.05, 0.25), 3)} or RMSLE degradation",
            target_evidence_level=EvidenceLevel.E3,
            current_evidence_level=level,
            status=status,
            parent_ids=[],
            entities=[
                Entity(type="Model", value=m),
                Entity(type="Feature", value=f),
                Entity(type="Regime", value=r),
            ],
            tags=[m.lower(), f.lower(), r.lower(), f"tag_{i % 10}"],
        )
        corpus.append(h)

    # Bulk insert for speed
    store.bulk_import(hypotheses=corpus, evidence=[], upsert=True, emit_summary_trace=False)
    return corpus


def evaluate_retrieval_quality(
    store: EpiresStore, corpus: List[HypothesisNode], n_queries: int = 150
) -> Dict[str, Any]:
    """Evaluates MRR, Recall@1, and Recall@5 comparing Pure VSA, Pure FTS5, and Hybrid."""
    random.seed(42)
    results = {
        "pure_vsa": {"rr": [], "r1": [], "r5": []},
        "pure_fts": {"rr": [], "r1": [], "r5": []},
        "hybrid": {"rr": [], "r1": [], "r5": []},
    }

    test_cases: List[Tuple[SearchQuery, str]] = []
    for _ in range(n_queries):
        target = random.choice(corpus)
        query_type = random.choice(["keyword", "entity", "mixed"])
        if query_type == "keyword":
            q_str = f"{target.tags[0]} {target.tags[1]}"
            sq = SearchQuery(query=q_str, limit=10)
        elif query_type == "entity":
            sq = SearchQuery(query="", entities=target.entities[:2], limit=10)
        else:
            sq = SearchQuery(query=target.tags[0], entities=[target.entities[0]], status=target.status, limit=10)
        test_cases.append((sq, target.id))

    with store._get_connection() as conn:
        rows = conn.execute("SELECT * FROM hypotheses WHERE vector_blob IS NOT NULL").fetchall()
        ids = [r["id"] for r in rows]
        vectors = [np.frombuffer(r["vector_blob"], dtype=np.int8) for r in rows]
        matrix = np.stack(vectors, axis=0)

    for sq, target_id in test_cases:
        # 1. Pure VSA
        terms = sq.query.split() if sq.query else []
        q_vec = store.encoder.encode_query(
            text_terms=terms, entities=sq.entities or [], status=sq.status.value if sq.status else None
        )
        vsa_sims = store.vsa.batch_similarity(q_vec, matrix)
        vsa_ranked = [ids[idx] for idx in np.argsort(-vsa_sims)[:10]]

        # 2. Pure FTS5
        fts_ranked = []
        if sq.query and sq.query.strip():
            with store._get_connection() as conn:
                try:
                    words = [w for w in sq.query.replace('"', " ").split() if len(w) >= 2]
                    if words:
                        match_query = " OR ".join([f'"{w}"*' for w in words])
                        fts_rows = conn.execute(
                            "SELECT id FROM hypotheses_fts WHERE hypotheses_fts MATCH ? ORDER BY rank LIMIT 10",
                            (match_query,),
                        ).fetchall()
                        fts_ranked = [r["id"] for r in fts_rows]
                except Exception:
                    pass

        # 3. Hybrid
        hybrid_res = store.search(sq)
        hybrid_ranked = [h.id for h, _ in hybrid_res]

        for method, ranked in [("pure_vsa", vsa_ranked), ("pure_fts", fts_ranked), ("hybrid", hybrid_ranked)]:
            if target_id in ranked:
                rank = ranked.index(target_id) + 1
                results[method]["rr"].append(1.0 / rank)
                results[method]["r1"].append(1.0 if rank == 1 else 0.0)
                results[method]["r5"].append(1.0 if rank <= 5 else 0.0)
            else:
                results[method]["rr"].append(0.0)
                results[method]["r1"].append(0.0)
                results[method]["r5"].append(0.0)

    return {
        m: {
            "MRR": float(np.mean(results[m]["rr"])),
            "Recall@1": float(np.mean(results[m]["r1"])),
            "Recall@5": float(np.mean(results[m]["r5"])),
        }
        for m in results
    }


def benchmark_latency_and_scaling(scales: List[int] = [100, 500, 1000, 2000]) -> List[Dict[str, Any]]:
    """Measures query execution latency and throughput across corpus scales."""
    results = []

    for n in scales:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EpiresStore(db_path=Path(tmpdir) / "scale.db")
            corpus = generate_synthetic_corpus(store, n_items=n)

            terms = ["catboost", "fft"]
            q_vec = store.encoder.encode_query(text_terms=terms, entities=[Entity(type="Model", value="CatBoost")])

            with store._get_connection() as conn:
                rows = conn.execute("SELECT vector_blob FROM hypotheses WHERE vector_blob IS NOT NULL").fetchall()
                vectors = [np.frombuffer(r["vector_blob"], dtype=np.int8) for r in rows]
                matrix = np.stack(vectors, axis=0)

            # Warmup
            _ = store.vsa.batch_similarity(q_vec, matrix)

            # Pure VSA
            n_iters = 50
            t0 = time.perf_counter()
            for _ in range(n_iters):
                _ = store.vsa.batch_similarity(q_vec, matrix)
            t_vsa = (time.perf_counter() - t0) / n_iters * 1000.0

            # Hybrid Search
            sq = SearchQuery(query="catboost fft", limit=10)
            t0 = time.perf_counter()
            for _ in range(n_iters):
                _ = store.search(sq)
            t_hybrid = (time.perf_counter() - t0) / n_iters * 1000.0

            qps = 1000.0 / t_hybrid if t_hybrid > 0 else 0

            results.append(
                {
                    "scale_n": n,
                    "vsa_matrix_latency_ms": round(t_vsa, 4),
                    "hybrid_search_latency_ms": round(t_hybrid, 4),
                    "throughput_qps": round(qps, 1),
                }
            )

    return results


def benchmark_dag_cascading() -> Dict[str, Any]:
    """Measures cascading falsification propagation latency through a deep dependency chain."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = EpiresStore(db_path=Path(tmpdir) / "dag.db")

        root = HypothesisNode(
            id="H-ROOT", title="Root mechanism", a_priori_mechanism="root", falsification_criteria="f"
        )
        store.register_hypothesis(root, emit_trace=False)

        prev_level = ["H-ROOT"]
        total_nodes = 1
        for depth in range(1, 4):
            curr_level = []
            fanout = 5 if depth < 3 else 8
            for parent_id in prev_level:
                for j in range(fanout):
                    total_nodes += 1
                    child_id = f"H-D{depth}-{total_nodes}"
                    h = HypothesisNode(
                        id=child_id,
                        title=f"Child {child_id}",
                        a_priori_mechanism="child mech",
                        falsification_criteria="f",
                        parent_ids=[parent_id],
                        status=HypothesisStatus.CONFIRMED,
                        current_evidence_level=EvidenceLevel.E2,
                    )
                    store.register_hypothesis(h, emit_trace=False)
                    curr_level.append(child_id)
            prev_level = curr_level

        ev = EvidenceClaim(
            id="ev_root_fail",
            hypothesis_id="H-ROOT",
            evidence_level=EvidenceLevel.E3,
            source_confidence=SourceConfidence.V,
            claim="Root invalidated",
            falsification_triggered=True,
        )

        t0 = time.perf_counter()
        _, blocked = store.log_evidence(ev, emit_trace=False)
        t_cascade = (time.perf_counter() - t0) * 1000.0

        return {
            "total_dag_nodes": total_nodes,
            "blocked_nodes_count": len(blocked),
            "cascade_latency_ms": round(t_cascade, 3),
        }


def profile_real_projects() -> List[Dict[str, Any]]:
    """Evaluates real production databases from ozonecup and socomputing."""
    reports = []
    projects = [
        ("socomputing (VSA/HDC Lab)", "/home/himera/projects/socomputing/.epires/hypotheses.db"),
        ("ozonecup (Tabular ML Lab)", "/home/himera/projects/ozonecup/.epires/hypotheses.db"),
    ]

    for label, path_str in projects:
        p = Path(path_str)
        if not p.exists():
            continue

        store = EpiresStore(db_path=p)
        hypotheses = store.list_hypotheses()
        evidence = store.list_evidence()
        relations = store.list_relations()
        traces = store.list_traces(limit=10000)

        t0 = time.perf_counter()
        n_searches = 100
        for _ in range(n_searches):
            _ = store.search(SearchQuery(query="model feature loss", limit=5))
        avg_search_ms = (time.perf_counter() - t0) / n_searches * 1000.0

        reports.append(
            {
                "project": label,
                "db_size_kb": round(p.stat().st_size / 1024, 1),
                "hypotheses_count": len(hypotheses),
                "evidence_count": len(evidence),
                "relations_count": len(relations),
                "traces_count": len(traces),
                "avg_search_latency_ms": round(avg_search_ms, 3),
                "qps": round(1000.0 / avg_search_ms, 1) if avg_search_ms > 0 else 0,
            }
        )

    return reports


if __name__ == "__main__":
    print("================================================================================")
    print("         EPIRES RESEARCH HARNESS — EMPIRICAL BENCHMARK & EVAL REPORT")
    print("================================================================================\n")

    # 1. Retrieval Accuracy
    print("[1/4] Evaluating Retrieval Quality & Recall@K (N=500 corpus, 150 test queries)...")
    with tempfile.TemporaryDirectory() as tmpdir:
        store = EpiresStore(db_path=Path(tmpdir) / "eval.db")
        corpus = generate_synthetic_corpus(store, n_items=500)
        eval_metrics = evaluate_retrieval_quality(store, corpus, n_queries=150)

    print("-" * 75)
    print(f"{'Method':<20} | {'MRR':<15} | {'Recall@1':<15} | {'Recall@5':<15}")
    print("-" * 75)
    for method, metrics in eval_metrics.items():
        print(
            f"{method.upper():<20} | {metrics['MRR']:<15.4f} | {metrics['Recall@1']:<15.4f} | {metrics['Recall@5']:<15.4f}"
        )
    print("-" * 75)
    metric_names = ("MRR", "Recall@1", "Recall@5")
    winners = {
        metric: max(eval_metrics, key=lambda method: eval_metrics[method][metric]).upper() for metric in metric_names
    }
    print(
        ">> OBSERVATION: Best measured method by metric: "
        + ", ".join(f"{metric}={winners[metric]}" for metric in metric_names)
        + ".\n"
    )

    # 2. Latency and Scalability
    print("[2/4] Benchmarking Latency & Scaling across corpus sizes...")
    scaling_results = benchmark_latency_and_scaling([100, 500, 1000, 2000])
    print("-" * 75)
    print(f"{'Nodes (N)':<12} | {'VSA Matrix (ms)':<18} | {'Hybrid Search (ms)':<20} | {'QPS':<15}")
    print("-" * 75)
    for row in scaling_results:
        print(
            f"{row['scale_n']:<12} | {row['vsa_matrix_latency_ms']:<18.4f} | {row['hybrid_search_latency_ms']:<20.4f} | {row['throughput_qps']:<15.1f}"
        )
    print("-" * 75)
    largest = scaling_results[-1]
    print(
        f">> OBSERVATION: At {largest['scale_n']:,} nodes, measured VSA matrix latency was "
        f"{largest['vsa_matrix_latency_ms']:.4f} ms and hybrid search latency was "
        f"{largest['hybrid_search_latency_ms']:.4f} ms ({largest['throughput_qps']:.1f} QPS).\n"
    )

    # 3. DAG Cascading Falsification
    print("[3/4] Benchmarking DAG Cascading Falsification & Tree Invalidation...")
    dag_res = benchmark_dag_cascading()
    print("-" * 75)
    print(f"Total DAG Nodes:     {dag_res['total_dag_nodes']}")
    print(f"Cascaded BLOCKED:    {dag_res['blocked_nodes_count']} hypotheses")
    print(f"Propagation Latency: {dag_res['cascade_latency_ms']} ms")
    print("-" * 75)
    print(
        f">> OBSERVATION: Cascaded BLOCKED to {dag_res['blocked_nodes_count']} dependent hypotheses in "
        f"{dag_res['cascade_latency_ms']:.3f} ms.\n"
    )

    # 4. Real Data Profiling
    print("[4/4] Profiling Real-world Research Databases (ozonecup & socomputing)...")
    real_res = profile_real_projects()
    print("-" * 85)
    print(f"{'Project':<30} | {'Hypotheses':<12} | {'Evidence':<10} | {'DAG Edges':<10} | {'Search (ms)':<12}")
    print("-" * 85)
    for r in real_res:
        print(
            f"{r['project']:<30} | {r['hypotheses_count']:<12} | {r['evidence_count']:<10} | {r['relations_count']:<10} | {r['avg_search_latency_ms']:<12.3f}"
        )
    print("-" * 85)
    print("\n[✔] Benchmark suite complete.")
