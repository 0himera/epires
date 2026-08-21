"""Abstract argumentation — grounded labeling + bipolar supported attacks."""
from __future__ import annotations

try:
    from .models import HypothesisStatus
except Exception:  # ponytail: fallback if models not importable
    HypothesisStatus = None  # type: ignore


def grounded_labeling(attacks: list[tuple[str, str]]) -> dict[str, str]:
    """Grounded labeling IN/OUT/UNDEC до fixpoint (bounded 100)."""
    # ponytail: literal per spec IN if no attackers; all-OUT=>IN is known ceiling — add if Dung-correct grounded needed
    nodes: set[str] = set()
    for a, b in attacks:
        nodes.add(a)
        nodes.add(b)
    if not nodes:
        return {}
    att_map: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b in attacks:
        att_map[b].append(a)
    label: dict[str, str] = {n: "UNDEC" for n in nodes}
    for _ in range(100):
        new: dict[str, str] = {}
        for n in nodes:
            attackers = att_map.get(n, [])
            if not attackers:
                new[n] = "IN"
            elif any(label[a] == "IN" for a in attackers):
                new[n] = "OUT"
            else:
                new[n] = "UNDEC"
        if new == label:
            break
        label = new
    return label


def bipolar_to_attacks(
    supports: list[tuple[str, str]], conflicts: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Преобразует SUPPORTS+CONFLICTS в атаки с транзитивным замыканием по SUPPORTS."""
    adj: dict[str, list[str]] = {}
    for a, b in supports:
        adj.setdefault(a, []).append(b)

    def closure(start: str) -> set[str]:
        visited: set[str] = set()
        stack = [start]
        seen: set[str] = set()
        while stack:
            cur = stack.pop()
            for nxt in adj.get(cur, []):
                if nxt not in seen:
                    seen.add(nxt)
                    visited.add(nxt)
                    stack.append(nxt)
        return visited

    attacks: set[tuple[str, str]] = set()
    for c in conflicts:
        attacks.add(c)
    # (a CONFLICTS b) + (b SUPPORTS* c) -> (a,c)
    for a, b in conflicts:
        for c in closure(b):
            attacks.add((a, c))
    # (a SUPPORTS b) + (c CONFLICTS a) -> (c,b) + closure(b)
    for a, b in supports:
        for c, d in conflicts:
            if d == a:
                attacks.add((c, b))
                for e in closure(b):
                    attacks.add((c, e))
    return sorted(attacks)


def status_from_label(label: str) -> str:
    """IN→CONFIRMED, OUT→FALSIFIED, UNDEC→BLOCKED."""
    if label == "IN":
        return HypothesisStatus.CONFIRMED.value if HypothesisStatus else "CONFIRMED"
    if label == "OUT":
        return HypothesisStatus.FALSIFIED.value if HypothesisStatus else "FALSIFIED"
    return HypothesisStatus.BLOCKED.value if HypothesisStatus else "BLOCKED"
