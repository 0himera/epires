"""Stigmergy pheromone + Hebbian + Bateson filter (Heylighen/Bateson)."""

from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING
import numpy as np

from .models import EvidenceClaim, TraceEntry

if TYPE_CHECKING:
    from .store import EpiresStore


def srmu_novelty_gate(v1: np.ndarray | None, v2: np.ndarray | None, dim: int = 10000) -> float:
    """Calculates SRMU novelty weight in [0.0, 1.0] between two vectors.

    Novelty = 1.0 - max(0.0, cosine_similarity).
    Redundant assertions (similarity ~ 1.0) yield novelty ~ 0.0 (suppressed update).
    Orthogonal / new assertions (similarity ~ 0.0) yield novelty ~ 1.0.
    """
    if v1 is None or v2 is None:
        return 1.0
    try:
        dot = float(np.dot(v1.astype(np.float32), v2.astype(np.float32)))
        sim = dot / max(1, dim)
        return float(max(0.0, min(1.0, 1.0 - sim)))
    except Exception:
        return 1.0


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def pheromone_weight(
    h_id: str,
    store: "EpiresStore",
    half_life_days: float = 7.0,
    mode: str = "auto",
    half_life_events: float = 20.0,
) -> float:
    """Computes stigmergic pheromone weight with SRMU / event-drift support.

    mode:
      - 'auto': uses SRMU event stream decay if traces exist, falling back to time decay.
      - 'srmu': uses trace-event distance decay (immune to wall-clock inactivity).
      - 'time': uses calendar time half-life decay.
    """
    h = store.get_hypothesis(h_id)  # type: ignore
    if not h:
        return 0.0
    evs = store.get_evidence_for_hypothesis(h_id)  # type: ignore
    confirmed = sum(1 for e in evs if not e.falsification_triggered)

    # Check event stream distance if traces are available
    event_age: float | None = None
    if mode in ("auto", "srmu") and hasattr(store, "list_traces"):
        try:
            traces = store.list_traces(limit=2000)
            if traces:
                last_idx = None
                for idx, t in enumerate(traces):
                    if t.h_tag == h_id:
                        last_idx = idx
                        break
                if last_idx is not None:
                    event_age = float(last_idx)
        except Exception:
            event_age = None

    if event_age is not None and (mode == "srmu" or (mode == "auto" and event_age >= 0)):
        decay = math.exp(-event_age / max(1.0, half_life_events))
        freshness = 1.0 / (1.0 + event_age)
        return float(confirmed * decay + freshness)

    # Fallback to calendar age
    last = None
    if evs:
        ts_list = [_parse_ts(e.timestamp) for e in evs]
        ts_list = [t for t in ts_list if t]
        last = max(ts_list) if ts_list else None
    if not last:
        last = _parse_ts(getattr(h, "updated_at", "")) or _parse_ts(getattr(h, "created_at", ""))
    now = datetime.now(timezone.utc)
    age = (now - last).total_seconds() / 86400 if last else 0.0
    age = max(0.0, age)
    decay = math.exp(-age / half_life_days) if half_life_days > 0 else 0.0
    freshness = 1.0 / (1.0 + age)
    return float(confirmed * decay + freshness)


def hebbian_strength(edge, store: "EpiresStore") -> float:
    """Frequency of joint use of edge's endpoints (via traces)."""
    try:
        traces = store.list_traces(limit=5000)  # type: ignore
    except Exception:
        return 0.0
    if not traces:
        return 0.0
    src = getattr(edge, "source_id", "") or ""
    tgt = getattr(edge, "target_id", "") or ""
    total = len(traces)
    hits = 0
    for t in traces:
        blob = f"{t.h_tag} {t.summary} {t.details}"
        if src and tgt and src in blob and tgt in blob:
            hits += 1
    # ponytail: O(n) scan, FAISS/index if throughput matters
    if hits:
        return hits / total
    # fallback: co-activation proxy when no joint trace exists
    c_s = sum(1 for t in traces if t.h_tag == src)
    c_t = sum(1 for t in traces if t.h_tag == tgt)
    if c_s and c_t:
        return min(c_s, c_t) / total
    return 0.0


def bateson_filter(entry: TraceEntry | EvidenceClaim) -> bool:
    """True if 'difference that makes a difference' -> keep, else cold log."""
    if getattr(entry, "falsification_triggered", False):
        return True
    d = getattr(entry, "delta_vs_baseline", None)
    if d is not None and d != 0 and d != 0.0:
        return True
    details = getattr(entry, "details", None)
    if isinstance(details, dict) and "status" in details:
        return True
    summ = (getattr(entry, "summary", "") or "").lower()
    if any(k in summ for k in ("falsif", "block", "confirm", "merge", "split", "condition", "resolved", "status")):
        return True
    # EvidenceClaim that changes hypothesis status is also meaningful (E-level promotion)
    # detected via falsification_triggered/delta above; otherwise cold
    return False


def rank_by_stigmergy(hypotheses, store: "EpiresStore") -> list:
    return sorted(hypotheses, key=lambda h: pheromone_weight(h.id, store), reverse=True)
