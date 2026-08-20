import random
import tempfile
import numpy as np
from pathlib import Path
from epires_core.models import HypothesisNode, Entity, SearchQuery, HypothesisStatus, EvidenceLevel
from epires_core.store import EpiresStore

with tempfile.TemporaryDirectory() as tmpdir:
    store = EpiresStore(db_path=Path(tmpdir) / "eval.db")
    models = ["LightGBM", "CatBoost", "XGBoost", "ResNet", "Transformer", "Linear", "RandomForest", "SVM"]
    features = ["FFT", "Wavelet", "Lag7", "Diff1", "RollingMean", "PCA", "TargetEncoding", "Quantile"]
    regimes = ["LowVolatility", "HighVolatility", "Trend", "Shock", "Holiday", "Seasonal"]

    corpus = []
    random.seed(42)
    for i in range(1, 501):
        m = random.choice(models)
        f = random.choice(features)
        r = random.choice(regimes)
        h = HypothesisNode(
            id=f"H-{i:04d}",
            title=f"{m} with {f} feature decomposition in {r} regime",
            a_priori_mechanism=f"Applying {f} to {m} captures spectral energy under {r} conditions with bounded variance.",
            falsification_criteria=f"Validation loss delta > {round(random.uniform(0.05, 0.25), 3)} or RMSLE degradation",
            target_evidence_level=EvidenceLevel.E3,
            current_evidence_level=EvidenceLevel.E1,
            status=HypothesisStatus.PROPOSED,
            parent_ids=[],
            entities=[Entity(type="Model", value=m), Entity(type="Feature", value=f), Entity(type="Regime", value=r)],
            tags=[m.lower(), f.lower(), r.lower(), f"tag_{i%10}"],
        )
        corpus.append(h)
    store.bulk_import(hypotheses=corpus, evidence=[], upsert=True, emit_summary_trace=False)

    with store._get_connection() as conn:
        rows = conn.execute("SELECT * FROM hypotheses WHERE vector_blob IS NOT NULL").fetchall()
        ids = [r["id"] for r in rows]
        vectors = [np.frombuffer(r["vector_blob"], dtype=np.int8) for r in rows]
        matrix = np.stack(vectors, axis=0)

    test_cases = []
    for _ in range(50):
        target = random.choice(corpus)
        sq = SearchQuery(query=f"{target.tags[0]} {target.tags[1]}", limit=10)
        test_cases.append(("keyword", sq, target.id))
    for _ in range(50):
        target = random.choice(corpus)
        sq = SearchQuery(query="", entities=target.entities[:2], limit=10)
        test_cases.append(("entity", sq, target.id))
    for _ in range(50):
        target = random.choice(corpus)
        sq = SearchQuery(query=target.tags[0], entities=[target.entities[1]], limit=10)
        test_cases.append(("mixed", sq, target.id))

    res = {"pure_vsa": [], "pure_fts": [], "naive_hybrid": [], "rrf_hybrid": []}

    for qtype, sq, target_id in test_cases:
        # VSA
        terms = sq.query.split() if sq.query else []
        q_vec = store.encoder.encode_query(text_terms=terms, entities=sq.entities or [], status=sq.status.value if sq.status else None)
        vsa_sims = store.vsa.batch_similarity(q_vec, matrix)
        vsa_order = np.argsort(-vsa_sims)
        vsa_rank_map = {ids[idx]: rank + 1 for rank, idx in enumerate(vsa_order)}
        vsa_top10 = [ids[idx] for idx in vsa_order[:10]]

        # FTS5
        fts_top10 = []
        fts_rank_map = {}
        if sq.query and sq.query.strip():
            with store._get_connection() as conn:
                try:
                    words = [w for w in sq.query.replace('"', " ").split() if len(w) >= 2]
                    if words:
                        match_query = " OR ".join([f'"{w}"*' for w in words])
                        fts_rows = conn.execute("SELECT id FROM hypotheses_fts WHERE hypotheses_fts MATCH ? ORDER BY rank LIMIT 50", (match_query,)).fetchall()
                        fts_top10 = [r["id"] for r in fts_rows[:10]]
                        for rank, r in enumerate(fts_rows):
                            fts_rank_map[r["id"]] = rank + 1
                except Exception:
                    pass

        # Naive Hybrid
        naive_scores = {}
        for idx, h_id in enumerate(ids):
            fts_boost = 0.5 if h_id in fts_rank_map else 0.0
            naive_scores[h_id] = float(vsa_sims[idx]) + fts_boost
        naive_top10 = sorted(naive_scores.keys(), key=lambda k: naive_scores[k], reverse=True)[:10]

        # RRF Hybrid (Reciprocal Rank Fusion)
        rrf_scores = {}
        for h_id in ids:
            vr = vsa_rank_map.get(h_id, 1000)
            fr = fts_rank_map.get(h_id, 1000)
            score = (1.0 / (60 + vr)) + ((2.0 / (60 + fr)) if fr < 1000 else 0.0)
            rrf_scores[h_id] = score
        rrf_top10 = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)[:10]

        for method, ranked in [("pure_vsa", vsa_top10), ("pure_fts", fts_top10), ("naive_hybrid", naive_top10), ("rrf_hybrid", rrf_top10)]:
            rank = ranked.index(target_id) + 1 if target_id in ranked else 0
            rr = 1.0 / rank if rank > 0 else 0.0
            res[method].append((qtype, rr, 1.0 if rank == 1 else 0.0, 1.0 if 0 < rank <= 5 else 0.0))

    print(f"{'Method':<15} | {'Overall MRR':<12} | {'Recall@1':<10} | {'Recall@5':<10}")
    print("-" * 55)
    for m in res:
        mrr = np.mean([x[1] for x in res[m]])
        r1 = np.mean([x[2] for x in res[m]])
        r5 = np.mean([x[3] for x in res[m]])
        print(f"{m:<15} | {mrr:<12.4f} | {r1:<10.4f} | {r5:<10.4f}")

    print("\nBreakdown by Query Type (MRR):")
    print(f"{'Method':<15} | {'Keyword':<12} | {'Entity':<12} | {'Mixed':<12}")
    print("-" * 55)
    for m in res:
        kw_mrr = np.mean([x[1] for x in res[m] if x[0] == 'keyword'])
        ent_mrr = np.mean([x[1] for x in res[m] if x[0] == 'entity'])
        mix_mrr = np.mean([x[1] for x in res[m] if x[0] == 'mixed'])
        print(f"{m:<15} | {kw_mrr:<12.4f} | {ent_mrr:<12.4f} | {mix_mrr:<12.4f}")
