"""Bipolar Vector Symbolic Architecture (VSA / Hyperdimensional Computing) Engine.

Inspired by HSME core and Kanerva SDM paradigms.
Operates on bipolar vectors {-1, +1}^D (default D = 10,000).
Operations:
- Bind (XOR/Multiply): Associative role-filler binding. Reversible: bind(bind(a, b), b) == a.
- Permute (Cyclic shift): Directional relation encoding.
- Bundle (Superposition / Majority Vote): Packing multiple entities/relations into a single hypervector.
- Similarity (Cosine / Normalized Dot Product): Microsecond associative lookup.
"""

from __future__ import annotations
import hashlib
from typing import Sequence
import numpy as np


class BipolarVSA:
    def __init__(self, dim: int = 10000, seed: int | None = 42):
        self.dim = dim
        self._seed = seed
        self._codebook: dict[str, np.ndarray] = {}

    def generate_vector(self, key: str | None = None) -> np.ndarray:
        """Generates a random bipolar vector (+1 or -1) of dimension self.dim.
        
        If `key` is provided, generates a deterministic vector by hashing the key.
        """
        if key is not None:
            if key in self._codebook:
                return self._codebook[key]
            # Deterministic hash-based seed for reproducibility
            hash_bytes = hashlib.sha256(key.encode("utf-8")).digest()
            seed_val = int.from_bytes(hash_bytes[:4], "big")
            rng = np.random.RandomState(seed_val)
            vec = rng.choice([-1, 1], size=self.dim).astype(np.int8)
            self._codebook[key] = vec
            return vec

        rng = np.random.RandomState(self._seed) if self._seed is not None else np.random
        return rng.choice([-1, 1], size=self.dim).astype(np.int8)

    def get_or_create_vector(self, key: str) -> np.ndarray:
        """Fetch or create a deterministic vector for a given entity key (e.g., 'Model:CatBoost')."""
        return self.generate_vector(key)

    def bind(self, v1: np.ndarray, v2: np.ndarray) -> np.ndarray:
        """Binds two bipolar vectors using element-wise multiplication.
        
        Binding preserves orthogonality to both operands and is reversible:
        bind(bind(a, b), b) == a.
        """
        return (v1 * v2).astype(np.int8)

    def permute(self, v: np.ndarray, shifts: int = 1) -> np.ndarray:
        """Permutes a bipolar vector using cyclic shift (np.roll).
        
        Used to encode directional relationships (e.g. source -> relation -> target).
        """
        return np.roll(v, shifts)

    def bundle(self, vectors: Sequence[np.ndarray]) -> np.ndarray:
        """Bundles multiple bipolar vectors using majority voting.
        
        The resulting vector is similar to all constituent vectors in the bundle.
        """
        if not vectors:
            raise ValueError("Cannot bundle an empty list of vectors.")
        if len(vectors) == 1:
            return vectors[0].copy()

        stacked = np.stack(vectors, axis=0)
        summed = np.sum(stacked, axis=0)

        # Majority vote
        bundled = np.sign(summed).astype(np.int8)

        # Break ties (where sign is 0) deterministically using pseudo-random selection
        ties = (bundled == 0)
        if np.any(ties):
            num_ties = np.sum(ties)
            tie_choices = np.where(np.arange(num_ties) % 2 == 0, 1, -1).astype(np.int8)
            bundled[ties] = tie_choices

        return bundled

    def similarity(self, v1: np.ndarray, v2: np.ndarray) -> float:
        """Calculates cosine similarity between two bipolar vectors.
        
        For bipolar vectors in {-1, 1}^D, this is dot(v1, v2) / D, bounded in [-1.0, 1.0].
        """
        dot_product = np.dot(v1.astype(np.float32), v2.astype(np.float32))
        return float(dot_product / self.dim)

    def batch_similarity(self, query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        """Calculates similarities between a query vector (D,) and a matrix of vectors (N, D).
        
        Returns an array of shape (N,) with similarity values.
        """
        if matrix.ndim == 1:
            return np.array([self.similarity(query, matrix)])
        dot_products = np.matmul(matrix.astype(np.float32), query.astype(np.float32))
        return (dot_products / self.dim).astype(np.float32)
