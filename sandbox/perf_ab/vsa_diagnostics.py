"""Deterministic, diagnostic-only retrieval benchmark for Epires VSA.

This module deliberately does not contribute to the perf-ab task score.  It
compares three retrieval implementations over exactly the same documents and
queries:

* a complete SQLite FTS5/BM25 lexical baseline over every text field;
* the current pure ``HypergraphEncoder`` + binary VSA index;
* the current public ``EpiresStore.search`` hybrid (FTS5 + VSA).

It also compares the current dual-codebook two-hop algorithm with exact BFS on
a fixed branching graph.  The corpus, relevance judgements, graph and queries
are all declared below rather than inferred from either implementation's
rankings.  The benchmark is therefore useful for diagnosis and ablations, but
must not be folded into the externally verified kernel-optimization score.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import statistics
import tempfile
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol, Sequence

from epires_core import (
    BipolarVSA,
    DualCodebookVSA,
    EpiresStore,
    HypergraphEncoder,
    HypothesisNode,
    SearchQuery,
)
from epires_core.models import Entity
from epires_core.search_index import BinaryIndex


@dataclass(frozen=True)
class DiagnosticDocument:
    id: str
    title: str
    mechanism: str
    criteria: str
    tags: tuple[str, ...]
    entities: tuple[tuple[str, str], ...]

    def as_hypothesis(self) -> HypothesisNode:
        return HypothesisNode(
            id=self.id,
            title=self.title,
            a_priori_mechanism=self.mechanism,
            falsification_criteria=self.criteria,
            tags=list(self.tags),
            entities=[Entity(type=kind, value=value) for kind, value in self.entities],
        )


@dataclass(frozen=True)
class DiagnosticQuery:
    id: str
    text: str
    # Integer grades: 3 = directly relevant, 1 = useful secondary result.
    relevance: Mapping[str, int]


def build_retrieval_corpus() -> tuple[DiagnosticDocument, ...]:
    """Return a fixed medium-kernel corpus with realistic lexical confounders."""

    rows = (
        (
            "K01",
            "Vectorized ragged softmax with AVX2",
            "SIMD exponential approximation walks row offsets without padding",
            "Reject if short irregular rows regress",
            ("ragged-softmax", "avx2", "row-offsets", "vectorization"),
            (("Kernel", "Softmax"), ("ISA", "AVX2")),
        ),
        (
            "K02",
            "Stable online maximum for irregular softmax rows",
            "Running maximum and rescaling prevent exponential overflow on variable lengths",
            "Reject on numerical error above 1e-6",
            ("ragged-softmax", "numerical-stability", "online-max", "irregular-rows"),
            (("Kernel", "Softmax"), ("Technique", "OnlineMax")),
        ),
        (
            "K03",
            "Fuse causal masking into ragged softmax",
            "Apply triangular mask while loading logits and skip masked exponentials",
            "Reject if causal outputs differ from reference",
            ("ragged-softmax", "causal-mask", "fusion", "logits"),
            (("Kernel", "Softmax"), ("Technique", "Fusion")),
        ),
        (
            "K04",
            "Dynamic scheduling for long-tail softmax rows",
            "Work stealing balances highly variable row lengths across worker threads",
            "Reject if scheduler overhead dominates median rows",
            ("ragged-softmax", "load-balancing", "work-stealing", "long-tail"),
            (("Kernel", "Softmax"), ("Technique", "Scheduling")),
        ),
        (
            "K05",
            "Cache blocked CSR sparse matrix vector multiply",
            "Reorder CSR row blocks to retain the dense input vector in cache",
            "Reject if matrix reordering cost is not amortized",
            ("spmv", "csr", "cache-blocking", "row-blocks"),
            (("Kernel", "SpMV"), ("Format", "CSR")),
        ),
        (
            "K06",
            "Gather prefetch for scattered sparse columns",
            "Software prefetch hides indirect x-vector gathers from column indices",
            "Reject when prefetch increases last-level cache misses",
            ("spmv", "gather", "prefetch", "column-indices"),
            (("Kernel", "SpMV"), ("Technique", "Prefetch")),
        ),
        (
            "K07",
            "Nonzero-balanced sparse row partition",
            "Partition by nonzero count instead of row count to reduce thread imbalance",
            "Reject on uniform matrices with excessive partition cost",
            ("spmv", "load-balancing", "nonzeros", "partition"),
            (("Kernel", "SpMV"), ("Technique", "Scheduling")),
        ),
        (
            "K08",
            "Sell-C-sigma sparse vector kernel",
            "Slice rows by length before SIMD execution to reduce padding",
            "Reject if conversion cost exceeds repeated execution savings",
            ("spmv", "sell-c-sigma", "simd", "row-length"),
            (("Kernel", "SpMV"), ("Format", "SELL")),
        ),
        (
            "K09",
            "One-pass Welford layer normalization",
            "Online mean and variance reduce memory traffic while retaining stability",
            "Reject if variance error exceeds tolerance",
            ("layernorm", "welford", "one-pass", "variance"),
            (("Kernel", "LayerNorm"), ("Technique", "Welford")),
        ),
        (
            "K10",
            "Vectorized affine layer normalization",
            "Fuse scale and bias with normalized output using wide SIMD stores",
            "Reject if unaligned tails regress",
            ("layernorm", "affine", "simd", "fusion"),
            (("Kernel", "LayerNorm"), ("Technique", "Vectorization")),
        ),
        (
            "K11",
            "Blocked reduction for wide layer normalization",
            "Each thread reduces a cache-sized feature tile before merging partials",
            "Reject when merge synchronization dominates",
            ("layernorm", "blocked-reduction", "cache", "parallel"),
            (("Kernel", "LayerNorm"), ("Technique", "Reduction")),
        ),
        (
            "K12",
            "Packed microkernel for small matrix multiply",
            "Register blocking and packed panels improve tiny GEMM reuse",
            "Reject if packing dominates one-shot matrices",
            ("gemm", "microkernel", "register-blocking", "packing"),
            (("Kernel", "GEMM"), ("Technique", "Packing")),
        ),
        (
            "K13",
            "Batched matrix multiply pointer hoisting",
            "Hoist batch strides and reuse address arithmetic across inner loops",
            "Reject if compiler already eliminates the arithmetic",
            ("gemm", "batched", "pointer-arithmetic", "hoisting"),
            (("Kernel", "GEMM"), ("Technique", "Hoisting")),
        ),
        (
            "K14",
            "Quantized int8 matrix multiply accumulation",
            "Widen dot products into int32 accumulators and fuse zero-point correction",
            "Reject on accumulator overflow",
            ("gemm", "int8", "quantization", "accumulation"),
            (("Kernel", "GEMM"), ("DType", "INT8")),
        ),
        (
            "K15",
            "Thread-private bins for parallel histogram",
            "Privatized counters avoid false sharing before a final reduction",
            "Reject when the bin array exceeds private cache",
            ("histogram", "false-sharing", "private-bins", "reduction"),
            (("Kernel", "Histogram"), ("Technique", "Privatization")),
        ),
        (
            "K16",
            "Conflict-free local histogram updates",
            "Replicate hot counters to reduce atomic contention on skewed keys",
            "Reject on uniform keys if replication overhead wins",
            ("histogram", "atomics", "contention", "skew"),
            (("Kernel", "Histogram"), ("Technique", "Replication")),
        ),
        (
            "K17",
            "Cache tiled separable image convolution",
            "Horizontal and vertical passes reuse halo pixels from a cache tile",
            "Reject if small images pay excess tiling overhead",
            ("convolution", "separable", "cache-tiling", "halo"),
            (("Kernel", "Convolution"), ("Technique", "Tiling")),
        ),
        (
            "K18",
            "Direct convolution with boundary specialization",
            "Separate interior loops eliminate boundary branches and checks",
            "Reject if code size harms instruction cache",
            ("convolution", "boundaries", "branch-elimination", "specialization"),
            (("Kernel", "Convolution"), ("Technique", "Specialization")),
        ),
        (
            "K19",
            "Winograd transform for three by three convolution",
            "Transform tiles reduce multiplication count for fixed filters",
            "Reject when transform error exceeds tolerance",
            ("convolution", "winograd", "transform", "3x3"),
            (("Kernel", "Convolution"), ("Technique", "Winograd")),
        ),
        (
            "K20",
            "Parallel Blelloch prefix scan",
            "Upsweep and downsweep tree compute exclusive prefix sums",
            "Reject below the parallel crossover size",
            ("prefix-scan", "blelloch", "parallel", "exclusive"),
            (("Kernel", "Scan"), ("Technique", "TreeReduction")),
        ),
        (
            "K21",
            "SIMD delimiter scan for JSON parsing",
            "Vector comparisons locate structural characters before scalar decoding",
            "Reject on strings dominated by escape sequences",
            ("json", "delimiter-scan", "simd", "parsing"),
            (("Kernel", "Parser"), ("Technique", "Vectorization")),
        ),
        (
            "K22",
            "Branchless UTF-8 validation",
            "Classify byte ranges with vector masks and validate continuation bytes",
            "Reject if malformed input bypasses validation",
            ("utf8", "branchless", "simd", "validation"),
            (("Kernel", "Parser"), ("Technique", "Validation")),
        ),
        (
            "K23",
            "Software pipelined radix partition",
            "Overlap histogram, prefix offsets and key scattering across blocks",
            "Reject if extra buffers exceed memory budget",
            ("radix-sort", "software-pipeline", "partition", "histogram"),
            (("Kernel", "Sort"), ("Technique", "Pipelining")),
        ),
        (
            "K24",
            "Blocked transpose with padded scratch tile",
            "Padding removes cache-set conflicts during matrix transpose",
            "Reject if scratch allocation dominates small matrices",
            ("transpose", "cache-blocking", "padding", "scratch"),
            (("Kernel", "Transpose"), ("Technique", "Tiling")),
        ),
    )
    return tuple(DiagnosticDocument(*row) for row in rows)


def build_retrieval_queries() -> tuple[DiagnosticQuery, ...]:
    """Queries are fixed independently of observed method rankings."""

    return (
        DiagnosticQuery("Q01", "ragged softmax AVX2 row offsets vectorization", {"K01": 3, "K04": 1}),
        DiagnosticQuery("Q02", "stable exponential overflow irregular softmax maximum", {"K02": 3}),
        DiagnosticQuery("Q03", "fused causal mask ragged logits", {"K03": 3, "K01": 1}),
        DiagnosticQuery("Q04", "load balancing variable length softmax work stealing", {"K04": 3, "K07": 1}),
        DiagnosticQuery("Q05", "CSR sparse matrix vector cache locality row blocks", {"K05": 3}),
        DiagnosticQuery("Q06", "prefetch scattered column gathers sparse matvec", {"K06": 3}),
        DiagnosticQuery("Q07", "balance sparse rows by nonzero count partition", {"K07": 3, "K04": 1}),
        DiagnosticQuery("Q08", "one pass Welford layer normalization variance", {"K09": 3}),
        DiagnosticQuery("Q09", "avoid false sharing with thread private histogram bins", {"K15": 3}),
        DiagnosticQuery("Q10", "ragged sofmax vectrized AVX2 row ofsets", {"K01": 3}),
        DiagnosticQuery("Q11", "jagged probability normalization SIMD", {"K01": 3, "K02": 1}),
        DiagnosticQuery("Q12", "separable convolution cache tile halo pixels", {"K17": 3}),
    )


class SearchBackend(Protocol):
    name: str

    def search(self, query: str, k: int) -> list[tuple[str, float]]: ...

    def resident_bytes(self) -> int: ...

    def close(self) -> None: ...


def _fts_terms(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[^\W_]+", text, flags=re.UNICODE) if len(token) >= 2]


class LexicalFTSBackend:
    """Strong exact-token BM25 baseline over all user-visible document text."""

    name = "lexical_fts5_bm25"

    def __init__(self, documents: Sequence[DiagnosticDocument], root: Path):
        self.db_path = root / "lexical.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute(
            "CREATE VIRTUAL TABLE docs USING fts5("
            "id UNINDEXED, title, mechanism, criteria, tags, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        self.conn.executemany(
            "INSERT INTO docs(id, title, mechanism, criteria, tags) VALUES (?, ?, ?, ?, ?)",
            [(d.id, d.title, d.mechanism, d.criteria, " ".join(d.tags)) for d in documents],
        )
        self.conn.commit()

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        terms = _fts_terms(query)
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in terms)
        rows = self.conn.execute(
            "SELECT id, bm25(docs, 1.0, 1.0, 1.0, 1.0) AS rank "
            "FROM docs WHERE docs MATCH ? ORDER BY rank ASC, id ASC LIMIT ?",
            (expression, k),
        ).fetchall()
        # SQLite BM25 is negative with better matches being more negative.
        return [(str(doc_id), -float(rank)) for doc_id, rank in rows]

    def resident_bytes(self) -> int:
        page_count = int(self.conn.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(self.conn.execute("PRAGMA page_size").fetchone()[0])
        return page_count * page_size

    def close(self) -> None:
        self.conn.close()


def _codebook_bytes(vsa: BipolarVSA) -> int:
    return sum(int(vector.nbytes) for vector in vsa._codebook.values())


class PureVSABackend:
    """Current hypothesis/query encoder with the current packed binary index."""

    name = "pure_vsa"

    def __init__(self, documents: Sequence[DiagnosticDocument], dim: int):
        self.vsa = BipolarVSA(dim=dim, seed=42)
        self.encoder = HypergraphEncoder(self.vsa)
        self.index = BinaryIndex(dim=dim)
        for document in documents:
            self.index.add(document.id, self.encoder.encode_hypothesis(document.as_hypothesis()))

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        vector = self.encoder.encode_query(text_terms=query.split())
        results = self.index.search(vector, k=k)
        return sorted(results, key=lambda item: (-item[1], item[0]))

    def resident_bytes(self) -> int:
        packed = sum(len(blob) for blob in self.index._blobs)
        return packed + _codebook_bytes(self.vsa)

    def close(self) -> None:
        return None


class EpiresHybridBackend:
    """Public current Epires hybrid search, without benchmark-specific reranking."""

    name = "epires_hybrid_current"

    def __init__(self, documents: Sequence[DiagnosticDocument], dim: int, root: Path):
        self.store = EpiresStore(db_path=root / "hybrid.db", vsa_dim=dim, trace_md_path=None)
        for document in documents:
            self.store.register_hypothesis(document.as_hypothesis(), emit_trace=False)

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        results = self.store.search(SearchQuery(query=query, limit=k))
        return [(document.id, float(score)) for document, score in results]

    def resident_bytes(self) -> int:
        with self.store._get_connection() as conn:
            sqlite_bytes = int(conn.execute("PRAGMA page_count").fetchone()[0]) * int(
                conn.execute("PRAGMA page_size").fetchone()[0]
            )
        index_bytes = sum(len(blob) for blob in getattr(self.store._index, "_blobs", ()))
        return sqlite_bytes + index_bytes + _codebook_bytes(self.store.vsa)

    def close(self) -> None:
        return None


def _recall_at_k(ranking: Sequence[str], relevance: Mapping[str, int], k: int) -> float:
    relevant = {doc_id for doc_id, grade in relevance.items() if grade > 0}
    if not relevant:
        return 0.0
    return len(relevant.intersection(ranking[:k])) / len(relevant)


def _reciprocal_rank(ranking: Sequence[str], relevance: Mapping[str, int], k: int) -> float:
    for rank, doc_id in enumerate(ranking[:k], start=1):
        if relevance.get(doc_id, 0) > 0:
            return 1.0 / rank
    return 0.0


def _dcg(grades: Iterable[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))


def _ndcg_at_k(ranking: Sequence[str], relevance: Mapping[str, int], k: int) -> float:
    actual = _dcg(relevance.get(doc_id, 0) for doc_id in ranking[:k])
    ideal = _dcg(sorted((grade for grade in relevance.values() if grade > 0), reverse=True)[:k])
    return actual / ideal if ideal else 0.0


def evaluate_rankings(
    rankings: Mapping[str, Sequence[str]], queries: Sequence[DiagnosticQuery], k: int
) -> dict[str, object]:
    per_query: list[dict[str, object]] = []
    for query in queries:
        ranking = list(rankings.get(query.id, ()))
        per_query.append(
            {
                "query_id": query.id,
                "recall_at_k": round(_recall_at_k(ranking, query.relevance, k), 6),
                "reciprocal_rank": round(_reciprocal_rank(ranking, query.relevance, k), 6),
                "ndcg_at_k": round(_ndcg_at_k(ranking, query.relevance, k), 6),
                "top_ids": ranking[:k],
                "relevant_ids": sorted(query.relevance),
            }
        )

    def mean(field: str) -> float:
        return round(statistics.fmean(float(row[field]) for row in per_query), 6)

    return {
        "recall_at_k": mean("recall_at_k"),
        "mrr_at_k": mean("reciprocal_rank"),
        "ndcg_at_k": mean("ndcg_at_k"),
        "per_query": per_query,
    }


def _percentile(values: Sequence[float], proportion: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, math.ceil(proportion * len(ordered)) - 1))
    return ordered[index]


def _latency_summary(samples_ms: Sequence[float]) -> dict[str, float | int]:
    return {
        "samples": len(samples_ms),
        "median_ms": round(statistics.median(samples_ms), 6),
        "p95_ms": round(_percentile(samples_ms, 0.95), 6),
        "mean_ms": round(statistics.fmean(samples_ms), 6),
    }


def _build_backend(factory: Callable[[], SearchBackend]) -> tuple[SearchBackend, dict[str, float | int]]:
    tracemalloc.start()
    started = time.perf_counter_ns()
    backend = factory()
    build_ms = (time.perf_counter_ns() - started) / 1_000_000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return backend, {"build_ms": round(build_ms, 6), "build_peak_traced_bytes": int(peak)}


def _benchmark_search_backend(
    backend: SearchBackend,
    queries: Sequence[DiagnosticQuery],
    k: int,
    repeats: int,
    build_stats: Mapping[str, float | int],
) -> dict[str, object]:
    # Untimed pass provides rankings and warms lazy indexes/caches.
    raw_rankings = {query.id: backend.search(query.text, k) for query in queries}
    rankings = {query_id: [doc_id for doc_id, _ in rows] for query_id, rows in raw_rankings.items()}
    samples: list[float] = []
    for _ in range(repeats):
        for query in queries:
            started = time.perf_counter_ns()
            backend.search(query.text, k)
            samples.append((time.perf_counter_ns() - started) / 1_000_000)

    quality = evaluate_rankings(rankings, queries, k)
    failure_cases = [
        row
        for row in quality["per_query"]
        if float(row["recall_at_k"]) < 1.0  # type: ignore[index]
    ]
    return {
        "quality": {key: value for key, value in quality.items() if key != "per_query"},
        "performance": {
            **build_stats,
            "hot_query_latency": _latency_summary(samples),
            "estimated_resident_bytes": backend.resident_bytes(),
        },
        "per_query": quality["per_query"],
        "failure_cases": failure_cases,
    }


# ---------------------------------------------------------------------------
# Two-hop diagnostic

GraphEdge = tuple[str, str, str]


@dataclass(frozen=True)
class GraphQuery:
    id: str
    head: str
    relation_1: str
    relation_2: str


def build_two_hop_graph() -> tuple[tuple[GraphEdge, ...], tuple[GraphQuery, ...]]:
    """Branching paths prevent a top-1 intermediate cleanup from getting a free pass."""

    edges: tuple[GraphEdge, ...] = (
        ("A", "BLOCKS", "B1"),
        ("A", "BLOCKS", "B2"),
        ("B1", "GATED_BY", "T1"),
        ("B2", "GATED_BY", "T2"),
        ("C", "REFINES", "M1"),
        ("C", "REFINES", "M2"),
        ("C", "REFINES", "M3"),
        ("M1", "SUPERSEDES", "U1"),
        ("M2", "SUPERSEDES", "U2"),
        ("M3", "SUPERSEDES", "U3"),
        ("D", "PRODUCES", "N1"),
        ("N1", "GATED_BY", "V1"),
        ("E", "BLOCKS", "X1"),
        ("X1", "REFINES", "Y1"),
        ("Z1", "CONFLICTS_WITH", "Z2"),
        ("Z2", "BLOCKS", "Z3"),
        ("P1", "PRODUCES", "P2"),
        ("P2", "SUPERSEDES", "P3"),
        ("J1", "REFINES", "J2"),
        ("J2", "GATED_BY", "J3"),
    )
    queries = (
        GraphQuery("G01", "A", "BLOCKS", "GATED_BY"),
        GraphQuery("G02", "C", "REFINES", "SUPERSEDES"),
        GraphQuery("G03", "D", "PRODUCES", "GATED_BY"),
        GraphQuery("G04", "E", "BLOCKS", "REFINES"),
        GraphQuery("G05", "P1", "PRODUCES", "SUPERSEDES"),
        GraphQuery("G06", "J1", "REFINES", "GATED_BY"),
    )
    return edges, queries


class ExactTwoHopBFS:
    name = "exact_bfs_reference"

    def __init__(self, edges: Sequence[GraphEdge]):
        self.adjacency: dict[tuple[str, str], set[str]] = {}
        for source, relation, target in edges:
            self.adjacency.setdefault((source, relation), set()).add(target)

    def query(self, query: GraphQuery, k: int) -> list[tuple[str, float]]:
        frontier = {query.head}
        for relation in (query.relation_1, query.relation_2):
            frontier = {target for source in frontier for target in self.adjacency.get((source, relation), set())}
        return [(target, 1.0) for target in sorted(frontier)[:k]]

    def resident_bytes(self) -> int:
        return sum(
            len(source.encode()) + len(relation.encode()) + sum(len(target.encode()) for target in targets)
            for (source, relation), targets in self.adjacency.items()
        )


class CurrentDualVSATwoHop:
    name = "current_dual_codebook_vsa"

    def __init__(self, edges: Sequence[GraphEdge], dim: int):
        self.vsa = DualCodebookVSA(dim=dim, seed=42)
        self.edges = tuple(edges)
        self.entities = sorted({node for edge in edges for node in (edge[0], edge[2])})
        self.memory = self.vsa.bundle_triples(self.edges)

    def query(self, query: GraphQuery, k: int) -> list[tuple[str, float]]:
        return self.vsa.query_2hop(
            memory=self.memory,
            head=query.head,
            relation_1=query.relation_1,
            relation_2=query.relation_2,
            all_entities=self.entities,
            top_k=k,
        )

    def resident_bytes(self) -> int:
        codebooks = (self.vsa._head_vsa, self.vsa._tail_vsa, self.vsa._rel_vsa)
        return int(self.memory.nbytes) + sum(_codebook_bytes(codebook) for codebook in codebooks)


def _benchmark_two_hop(dim: int, k: int, repeats: int) -> dict[str, object]:
    edges, queries = build_two_hop_graph()
    exact = ExactTwoHopBFS(edges)
    ground_truth = {query.id: {target: 1 for target, _ in exact.query(query, k=len(edges))} for query in queries}
    metric_queries = tuple(
        DiagnosticQuery(query.id, f"{query.head} {query.relation_1} {query.relation_2}", ground_truth[query.id])
        for query in queries
    )

    methods: dict[str, object] = {}
    for backend in (exact, CurrentDualVSATwoHop(edges, dim=dim)):
        rankings = {query.id: [target for target, _ in backend.query(query, k)] for query in queries}
        samples: list[float] = []
        for _ in range(repeats):
            for query in queries:
                started = time.perf_counter_ns()
                backend.query(query, k)
                samples.append((time.perf_counter_ns() - started) / 1_000_000)
        quality = evaluate_rankings(rankings, metric_queries, k)
        methods[backend.name] = {
            "quality": {key: value for key, value in quality.items() if key != "per_query"},
            "performance": {
                "hot_query_latency": _latency_summary(samples),
                "estimated_resident_bytes": backend.resident_bytes(),
            },
            "per_query": quality["per_query"],
            "failure_cases": [
                row
                for row in quality["per_query"]
                if float(row["recall_at_k"]) < 1.0  # type: ignore[index]
            ],
        }

    return {
        "graph": {"nodes": len({node for edge in edges for node in (edge[0], edge[2])}), "edges": len(edges)},
        "query_count": len(queries),
        "ground_truth": {query_id: sorted(relevance) for query_id, relevance in ground_truth.items()},
        "methods": methods,
        "design_note": "Exact BFS expands every intermediate; current VSA cleans up to one top intermediate before hop two.",
    }


def run_diagnostics(dim: int = 10_000, k: int = 5, repeats: int = 20) -> dict[str, object]:
    if dim <= 0 or dim % 8 != 0:
        raise ValueError("dim must be a positive multiple of 8 for the binary index")
    if k <= 0:
        raise ValueError("k must be positive")
    if repeats <= 0:
        raise ValueError("repeats must be positive")

    documents = build_retrieval_corpus()
    queries = build_retrieval_queries()
    with tempfile.TemporaryDirectory(prefix="epires-vsa-diagnostic-") as temp_dir:
        root = Path(temp_dir)
        factories: tuple[Callable[[], SearchBackend], ...] = (
            lambda: LexicalFTSBackend(documents, root),
            lambda: PureVSABackend(documents, dim),
            lambda: EpiresHybridBackend(documents, dim, root),
        )
        retrieval_methods: dict[str, object] = {}
        for factory in factories:
            backend, build_stats = _build_backend(factory)
            try:
                retrieval_methods[backend.name] = _benchmark_search_backend(backend, queries, k, repeats, build_stats)
            finally:
                backend.close()

        return {
            "schema_version": 1,
            "benchmark": "epires_vsa_offline_diagnostics",
            "diagnostic_only": True,
            "included_in_primary_perf_score": False,
            "config": {"dim": dim, "k": k, "repeats": repeats, "seed": 42},
            "retrieval": {
                "corpus_size": len(documents),
                "query_count": len(queries),
                "fields_seen_by_lexical": ["title", "mechanism", "criteria", "tags"],
                "fields_seen_by_current_vsa": ["id", "status", "evidence_level", "entities", "tags"],
                "methods": retrieval_methods,
            },
            "two_hop": _benchmark_two_hop(dim=dim, k=k, repeats=repeats),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dim", type=int, default=10_000, help="VSA dimensions (positive multiple of 8)")
    parser.add_argument("--k", type=int, default=5, help="Retrieval cutoff")
    parser.add_argument("--repeats", type=int, default=20, help="Timed repetitions per query")
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation; use 0 for compact output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_diagnostics(dim=args.dim, k=args.k, repeats=args.repeats)
    print(json.dumps(result, indent=args.indent or None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
