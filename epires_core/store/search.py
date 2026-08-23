"""Hybrid FTS5 + VSA associative search, gap discovery, and scoring wrappers."""

from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from ..models import (
    EvidenceClaim,
    GapQuery,
    HypothesisNode,
    HypothesisStatus,
    SearchQuery,
)


class SearchMixin:
    """Provides hybrid search, combinatorial gap analysis, and stigmergy/scoring wrappers."""

    def bateson_should_log(self, ev: EvidenceClaim) -> bool:
        from ..stigmergy import bateson_filter

        return bateson_filter(ev)

    def pheromone_rank(self) -> List[HypothesisNode]:
        from ..stigmergy import rank_by_stigmergy

        return rank_by_stigmergy(self.list_hypotheses(), self)

    def score_experiments(self, candidates: List[Dict[str, Any]], q: Dict[str, float]) -> List[Tuple[str, float]]:
        from ..scoring import score_candidates

        return score_candidates(candidates, q)

    def calibrated_p(self, agent_id: str, stated_p: float) -> float:
        from ..calibration import calibrated_weight

        return calibrated_weight(agent_id, stated_p, self)

    def search(self, sq: SearchQuery) -> List[Tuple[HypothesisNode, float]]:
        """Performs hybrid full-text (SQLite FTS5) and VSA cosine similarity search."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM hypotheses WHERE vector_blob IS NOT NULL").fetchall()
            if not rows:
                return []

            ids = [r["id"] for r in rows]
            vectors = [np.frombuffer(r["vector_blob"], dtype=np.int8) for r in rows]
            matrix = np.stack(vectors, axis=0)

            if self._index is None or len(getattr(self._index, "_ids", ())) != len(rows):
                try:
                    from ..search_index import BinaryIndex

                    idx = BinaryIndex(dim=self.vsa.dim)
                    for hid, vec in zip(ids, vectors):
                        idx.add(hid, vec)  # BinaryIndex packs bipolar int8 itself
                    self._index = idx
                except Exception:
                    self._index = None

        # 1. Full-text search via SQLite FTS5
        fts_matches: Dict[str, float] = {}
        if sq.query and sq.query.strip():
            with self._get_connection() as conn:
                try:
                    words = [w for w in sq.query.replace('"', " ").replace("'", " ").split() if len(w) >= 2]
                    if words:
                        match_query = " OR ".join([f'"{w}"*' for w in words])
                        fts_rows = conn.execute(
                            "SELECT id, rank FROM hypotheses_fts WHERE hypotheses_fts MATCH ? ORDER BY rank LIMIT 50",
                            (match_query,),
                        ).fetchall()
                        for r in fts_rows:
                            fts_matches[r["id"]] = max(0.5, 1.0 / (1.0 + abs(float(r["rank"]))))
                except Exception:
                    pass

        # 2. VSA query hypervector
        terms = sq.query.split() if sq.query else []
        q_vec = self.encoder.encode_query(
            text_terms=terms, entities=sq.entities or [], status=sq.status.value if sq.status else None
        )

        if self._index is not None:
            hits = dict(self._index.search(q_vec, k=len(ids)))
            sims = [hits.get(h_id, 0.0) for h_id in ids]
        else:
            sims = self.vsa.batch_similarity(q_vec, matrix)

        # 3. Hybrid fusion
        combined_scores: List[Tuple[str, float]] = []
        for h_id, vsa_sim in zip(ids, sims):
            score = float(vsa_sim) + fts_matches.get(h_id, 0.0)
            combined_scores.append((h_id, score))

        combined_scores.sort(key=lambda x: x[1], reverse=True)

        results: List[Tuple[HypothesisNode, float]] = []
        for h_id, score in combined_scores[: sq.limit]:
            h = self.get_hypothesis(h_id)
            if h:
                results.append((h, float(score)))
        return results

    def find_gaps(self, gq: GapQuery) -> List[Dict[str, Any]]:
        """Finds under-explored or untested entity combinations (White Spots / Gaps in research).

        Distinguishes mere conceptual hypotheses from empirically tested combinations.
        """
        all_h = self.list_hypotheses()
        tested_combinations: Dict[Tuple[str, ...], int] = {}
        hypothesized_combinations: Dict[Tuple[str, ...], int] = {}
        dimension_values: Dict[str, set[str]] = {dim: set() for dim in gq.dimensions}

        # Cache evidence and experiment counts per hypothesis
        with self._get_connection() as conn:
            ev_counts = {
                r["hypothesis_id"]: r["c"]
                for r in conn.execute(
                    "SELECT hypothesis_id, COUNT(*) as c FROM evidence WHERE (is_retracted = 0 OR is_retracted IS NULL) GROUP BY hypothesis_id"
                ).fetchall()
            }
            exp_counts = {
                r["hypothesis_id"]: r["c"]
                for r in conn.execute(
                    "SELECT hypothesis_id, COUNT(*) as c FROM experiments GROUP BY hypothesis_id"
                ).fetchall()
            }

        for h in all_h:
            ent_map: Dict[str, str] = {
                e.type if hasattr(e, "type") else e["type"]: e.value if hasattr(e, "value") else e["value"]
                for e in h.entities
            }
            for dim in gq.dimensions:
                if dim in ent_map:
                    dimension_values[dim].add(ent_map[dim])

            # Check if hypothesis covers all requested dimensions
            if all(dim in ent_map for dim in gq.dimensions):
                combo = tuple(ent_map[dim] for dim in gq.dimensions)
                hypothesized_combinations[combo] = hypothesized_combinations.get(combo, 0) + 1

                # An entity combination is considered empirically tested if it has evidence/experiments
                empirical_weight = ev_counts.get(h.id, 0) + exp_counts.get(h.id, 0)
                if empirical_weight > 0 or h.status in {HypothesisStatus.CONFIRMED, HypothesisStatus.FALSIFIED}:
                    tested_combinations[combo] = tested_combinations.get(combo, 0) + max(1, empirical_weight)

        # Compute Cartesian product of seen dimension values
        all_combos = list(itertools.product(*[list(dimension_values[d]) for d in gq.dimensions]))

        gaps: List[Dict[str, Any]] = []
        for combo in all_combos:
            tested_count = tested_combinations.get(combo, 0)
            hypo_count = hypothesized_combinations.get(combo, 0)
            if tested_count < gq.min_tested:
                gaps.append(
                    {
                        "combination": {dim: val for dim, val in zip(gq.dimensions, combo)},
                        "tested_count": tested_count,
                        "hypothesized_count": hypo_count,
                        "status": "UNTESTED" if tested_count == 0 else "UNDER_TESTED",
                    }
                )
        return gaps

    def query_2hop_relations(
        self,
        head_id: str,
        relation_1: str,
        relation_2: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Executes a 2-hop causal query on the relation graph using Dual-Codebook VSA (VSAR-034)."""
        if self._dual_vsa is None:
            from ..vsa_dual import DualCodebookVSA

            self._dual_vsa = DualCodebookVSA(dim=self.vsa.dim)

        relations = self.list_relations()
        if not relations:
            return []

        triples = [(r.source_id, r.relation_type.value, r.target_id) for r in relations]
        memory_bundle = self._dual_vsa.bundle_triples(triples)

        # Collect all unique entity/hypothesis IDs in the graph
        entities = list({r.source_id for r in relations} | {r.target_id for r in relations})

        scores = self._dual_vsa.query_2hop(
            memory=memory_bundle,
            head=head_id,
            relation_1=relation_1,
            relation_2=relation_2,
            all_entities=entities,
            top_k=top_k,
        )

        return [{"target_id": tid, "similarity": round(sim, 4)} for tid, sim in scores]

    def sharded_search(
        self,
        query_text: str,
        agent_role: str = "Lead-PI",
        top_k: int = 5,
        allowed_roles: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Executes a multi-agent sharded search with zero cross-agent contamination (VSAR-032/033)."""
        if self._shard_router is None:
            from ..sharding import HierarchicalShardRouter

            self._shard_router = HierarchicalShardRouter(dim=self.vsa.dim, total_shards=16)
            # Seed shards from current hypotheses
            hypotheses = self.list_hypotheses()
            workloads: Dict[str, int] = {}
            for h in hypotheses:
                role = "Lead-PI"
                workloads[role] = workloads.get(role, 0) + 1
                vec = self.vsa.ngram_bundle(f"{h.title} {h.a_priori_mechanism}")
                self._shard_router.insert(
                    h.id, vec, agent_role=role, metadata={"title": h.title, "status": h.status.value}
                )

        query_vec = self.vsa.ngram_bundle(query_text)
        results = self._shard_router.query(query_vec, agent_role=agent_role, top_k=top_k, allowed_roles=allowed_roles)
        return [{"id": item_id, "similarity": round(sim, 4), **meta} for item_id, sim, meta in results]

    def compress_trace_context(self, limit: int = 50) -> Dict[str, Any]:
        """Compresses latest execution traces into a dense VSA semantic digest (VSAR-007)."""
        if self._compressor is None:
            from ..compressor import EpisodicVSACompressor

            self._compressor = EpisodicVSACompressor(dim=self.vsa.dim)

        raw_traces = self.list_traces(limit=limit)
        trace_dicts = [t.model_dump() for t in raw_traces]
        res = self._compressor.compress_traces(trace_dicts)
        # Drop raw numpy vector from user response for JSON serializability
        res.pop("state_vector", None)
        return res
