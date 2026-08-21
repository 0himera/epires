"""Eval agents: deterministic MockAgent (prompt-keyword driven) + minimal LLMAgent stub."""

from __future__ import annotations

import json
import os

VERIFY_MARKER = "verify assumptions first"
AUDIT_MARKER = "use audit before confirming"


class MockAgent:
    """Reads the variant prompt and decides by marker phrases. Deterministic, no LLM."""

    def __init__(self, variant_text: str):
        self.variant = variant_text.lower()
        self.verify_first = VERIFY_MARKER in self.variant
        self.audit_first = AUDIT_MARKER in self.variant

    def respond(self, obs: dict) -> dict:
        kind = obs.get("kind")
        if kind == "anomaly":
            if self.verify_first:
                return {"action": "attribute", "assumption_ids": obs.get("suspects", [])}
            return {"action": "falsify"}
        if kind == "results":
            if self.audit_first:
                return {"action": "verify_level"}
            return {"action": "claim", "level": obs.get("claimed_level", "E4")}
        if kind == "conflict":
            if self.audit_first:
                return {"action": "discuss"}
            return {"action": "confirm", "h_id": obs.get("champion", "HA")}
        return {"action": "noop"}


class LLMAgent:
    """OpenAI-compatible chat-completions call. TODO: retries, multi-turn tool loop."""

    def __init__(self, variant_text: str, scenario_description: str = "", model: str | None = None):
        self.model = model or os.environ["EPIRES_EVAL_MODEL"]
        self.base_url = os.environ.get("EPIRES_EVAL_BASE_URL", "https://api.openai.com/v1")
        self.system = f"{variant_text}\n\nScenario:\n{scenario_description}"

    def respond(self, obs: dict) -> dict:
        import httpx

        r = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {os.environ.get('EPIRES_EVAL_API_KEY', '')}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system},
                    {"role": "user", "content": json.dumps(obs)},
                ],
            },
            timeout=60,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        # ponytail: naive JSON slice, structured outputs if this survives contact with real models
        return json.loads(content[content.index("{") : content.rindex("}") + 1])
