"""Provenance: observer context & criteria registry."""

from __future__ import annotations

from dataclasses import dataclass

CRITERIA_VERSIONS: dict[str, str] = {
    "v1": "initial falsification criteria v1 — baseline",
    "v2": "refined criteria v2 — stricter thresholds",
    "v3": "production criteria v3 — hidden-test grade",
}


@dataclass
class ObserverBlock:
    agent_id: str = ""
    model: str = ""
    prompt_version: str = ""
    criteria_version: str = "v1"
    stated_p: float = 0.5
    distinction: str = ""
    framing: str = ""


def build_observer_id(model: str, prompt_version: str) -> str:
    return f"{model}:{prompt_version}"
