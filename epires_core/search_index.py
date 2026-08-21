"""FAISS binary index wrapper with numpy fallback (ponytail: 1 class + 2 funcs)."""

from __future__ import annotations

import numpy as np

try:
    import faiss  # type: ignore

    _HAS_FAISS = True
except Exception:  # noqa: BLE001
    faiss = None  # type: ignore
    _HAS_FAISS = False


def _to_bytes(vec: np.ndarray) -> bytes:
    """Bipolar {-1,1} int8 -> packed bytes (1 bit per dim)."""
    bits = (np.asarray(vec, dtype=np.int8) == 1).astype(np.uint8)
    # ponytail: packbits is MSB-first, consistent for query/store
    return np.packbits(bits).tobytes()


def _hamming(a: bytes, b: bytes) -> int:
    """Hamming distance between two packed blobs via popcount."""
    av = np.frombuffer(a, dtype=np.uint8)
    bv = np.frombuffer(b, dtype=np.uint8)
    xor = np.bitwise_xor(av, bv)
    return int(np.unpackbits(xor).sum())


class BinaryIndex:
    """Binary VSA index: FAISS IndexBinaryFlat if available else brute popcount."""

    def __init__(self, dim: int = 10000):
        self.dim = dim
        self.nbytes = (dim + 7) // 8
        self._ids: list[str] = []
        self._blobs: list[bytes] = []
        self._faiss = None
        if _HAS_FAISS:
            try:
                base = faiss.IndexBinaryFlat(dim)  # type: ignore
                try:
                    self._faiss = faiss.IndexBinaryIDMap(base)  # type: ignore
                except Exception:
                    self._faiss = base
            except Exception:
                self._faiss = None

    def add(self, hid: str, vec: np.ndarray) -> None:
        blob = _to_bytes(vec)
        # pad/truncate to nbytes (ponytail: protects dim mismatch)
        if len(blob) != self.nbytes:
            blob = (blob + b"\x00" * self.nbytes)[: self.nbytes]
        self._ids.append(hid)
        self._blobs.append(blob)
        if self._faiss is not None:
            arr = np.frombuffer(blob, dtype=np.uint8).reshape(1, -1)
            if hasattr(self._faiss, "add_with_ids"):
                try:
                    self._faiss.add_with_ids(arr, np.array([len(self._ids) - 1], dtype=np.int64))  # type: ignore
                    return
                except Exception:
                    pass
            self._faiss.add(arr)  # type: ignore

    def search(self, query_vec: np.ndarray, k: int = 10) -> list[tuple[str, float]]:
        if not self._ids:
            return []
        k = min(k, len(self._ids))
        q_blob = _to_bytes(query_vec)
        if len(q_blob) != self.nbytes:
            q_blob = (q_blob + b"\x00" * self.nbytes)[: self.nbytes]

        # FAISS path
        if self._faiss is not None and getattr(self._faiss, "ntotal", 0) > 0:
            try:
                q_arr = np.frombuffer(q_blob, dtype=np.uint8).reshape(1, -1)
                dists, idxs = self._faiss.search(q_arr, k)  # type: ignore
                out: list[tuple[str, float]] = []
                for dist, idx in zip(dists[0], idxs[0]):
                    if int(idx) < 0 or int(idx) >= len(self._ids):
                        continue
                    # ponytail: score = 1 - hamming/dim (higher = closer)
                    score = (self.dim - int(dist)) / self.dim
                    out.append((self._ids[int(idx)], float(score)))
                # fallback if FAISS returned <k due to IDMap quirks
                if out:
                    return out
            except Exception:
                pass

        # numpy brute-force fallback
        scores: list[tuple[str, float]] = []
        for hid, blob in zip(self._ids, self._blobs):
            h = _hamming(q_blob, blob)
            score = (self.dim - h) / self.dim
            scores.append((hid, float(score)))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:k]
