"""Episodic Context Token Compressor (VSAR-007).

Encodes multi-turn agent execution traces, hypothesis mechanisms, and observations into
compact VSA superposition digests, reducing context window tokens by >=50% while preserving
retrieval accuracy and semantic intent.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence
import numpy as np

from .vsa import BipolarVSA


class EpisodicVSACompressor:
    """Compresses long agent trace streams and multi-turn notes into dense semantic digests."""

    def __init__(self, dim: int = 4096, seed: int = 42):
        self.dim = dim
        self.vsa = BipolarVSA(dim=dim, seed=seed)

    def _extract_keywords(self, text: str) -> List[str]:
        """Extracts normalized salient tokens/keywords from text."""
        words = re.findall(r"[A-Za-z0-9_\-\.:=]+", text)
        stopwords = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "in",
            "on",
            "at",
            "to",
            "for",
            "with",
            "by",
            "of",
            "is",
            "are",
            "was",
            "were",
            "it",
            "this",
            "that",
            "from",
            "as",
            "be",
            "have",
            "has",
        }
        return [w for w in words if len(w) > 2 and w.lower() not in stopwords]

    def encode_event(self, action: str, summary: str, details: Optional[Dict[str, Any]] = None) -> np.ndarray:
        """Encodes an episodic event into a bound VSA hypervector."""
        v_action = self.vsa.get_or_create_vector(f"action::{action.upper()}")
        keywords = self._extract_keywords(summary)
        if details:
            for k, v in details.items():
                keywords.extend(self._extract_keywords(f"{k}:{v}"))

        if not keywords:
            return v_action

        kw_vectors = [self.vsa.get_or_create_vector(f"kw::{kw.lower()}") for kw in keywords]
        v_content = self.vsa.bundle(kw_vectors)
        return self.vsa.bind(v_action, v_content)

    def compress_traces(
        self,
        traces: Sequence[Dict[str, Any]],
        max_summary_tokens: int = 150,
    ) -> Dict[str, Any]:
        """Compresses a sequence of trace records into a structured summary + state hypervector (VSAR-007).

        Returns:
            {
                "compressed_digest": str,
                "original_tokens": int,
                "compressed_tokens": int,
                "token_reduction_pct": float,
                "state_vector": np.ndarray
            }
        """
        if not traces:
            return {
                "compressed_digest": "No active traces recorded.",
                "original_tokens": 0,
                "compressed_tokens": 5,
                "token_reduction_pct": 0.0,
                "state_vector": np.zeros(self.dim, dtype=np.int8),
            }

        full_raw_text = " ".join(
            f"[{t.get('action', '')}] {t.get('summary', '')} {str(t.get('details', ''))}" for t in traces
        )
        original_tokens = max(1, len(full_raw_text.split()))

        # Encode and bundle all events
        event_vectors = []
        action_counts: Dict[str, int] = {}
        key_milestones: List[str] = []

        for t in traces:
            act = t.get("action", "EVENT")
            summ = t.get("summary", "")
            action_counts[act] = action_counts.get(act, 0) + 1
            event_vectors.append(self.encode_event(act, summ, t.get("details")))

            # Retain critical decisions / falsifications / gates
            if any(k in act.upper() for k in ("CONFIRM", "FALSIFY", "ANOMALY", "GATE", "RETRACT", "REGISTER")):
                key_milestones.append(f"• {act}: {summ}")

        state_vector = self.vsa.bundle(event_vectors)

        # Build dense executive digest (VSAR-007)
        actions_summary = ", ".join(f"{act}:{cnt}" for act, cnt in sorted(action_counts.items()))
        milestones = [f"• {m[:80]}" for m in (key_milestones[-3:] if key_milestones else ["• Initialized"])]
        recent = [f"• {t.get('action', '')}: {t.get('summary', '')[:60]}" for t in traces[-2:]]

        digest_parts = [
            f"[VSA State: {len(traces)} events | {actions_summary}]",
            "Milestones:",
            *milestones,
            "Recent:",
            *recent,
        ]

        compressed_text = "\n".join(digest_parts)
        compressed_tokens = len(compressed_text.split())
        token_reduction = max(0.0, round((1.0 - (compressed_tokens / original_tokens)) * 100.0, 1))

        return {
            "compressed_digest": compressed_text,
            "original_tokens": original_tokens,
            "compressed_tokens": compressed_tokens,
            "token_reduction_pct": token_reduction,
            "state_vector": state_vector,
        }
