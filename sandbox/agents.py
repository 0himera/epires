"""Eval agents: deterministic MockAgent (prompt-keyword driven) + minimal LLMAgent stub."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

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


class OpencodeAgent:
    """Runs tasks through real opencode CLI in an isolated workspace."""

    def __init__(self, variant_prompt: str, model: str | None = None):
        self.variant_prompt = variant_prompt
        self.model = model or os.getenv("EPIRES_EVAL_MODEL", "")
        self.workspace: Path | None = None

    def seed(self, workspace: Path, task: str = "") -> None:
        cfg_dir = workspace / ".opencode"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        # ponytail: isolate workspace as its own git project — otherwise opencode
        # resolves project root to the parent repo and leaks its root AGENTS.md
        if not (workspace / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=False)
            subprocess.run(["git", "add", "-A"], cwd=workspace, check=False)
            subprocess.run(["git", "commit", "-qm", "ws"], cwd=workspace, check=False)
        epires_bin = str((PROJECT_ROOT / ".venv" / "bin" / "epires").resolve())
        (cfg_dir / "opencode.json").write_text(
            json.dumps({"mcp": {"epires": {"type": "local", "command": [epires_bin, "mcp"]}}}),
            encoding="utf-8",
        )
        (workspace / "AGENTS.md").write_text(f"{self.variant_prompt}\n\n{task}", encoding="utf-8")
        self.workspace = workspace

    def run(self, task: str, workspace: Path) -> str:
        self.seed(workspace, task)
        # ponytail: opencode trusts $PWD over getcwd — point it at the workspace
        env = dict(os.environ)
        abs_ws = str(Path(workspace).resolve())
        env["PWD"] = abs_ws
        r = subprocess.run(
            ["opencode", "run", "Execute the task described in AGENTS.md.", "--format", "json"],
            cwd=abs_ws,
            env=env,
            timeout=600,
            capture_output=True,
            text=True,
        )
        out = (r.stdout or "") + (r.stderr or "")
        # ponytail: persist transcript for debugging failed runs
        try:
            (workspace / "agent_transcript.jsonl").write_text(out, encoding="utf-8")
        except Exception:
            pass
        return out

    def respond(self, obs: dict) -> dict:
        # ponytail: NEVER run in repo cwd — it would overwrite the root AGENTS.md.
        # One-shot verdicts get a throwaway isolated workspace.
        if self.workspace is None:
            self._td = tempfile.TemporaryDirectory(prefix="epires_respond_")
            self.workspace = Path(self._td.name)
        out = self.run(json.dumps(obs), self.workspace)
        # ponytail: --format json is an NDJSON event stream; model text lives in type=="text" parts
        texts: list[str] = []
        for line in out.splitlines():
            line = line.strip()
            if not (line.startswith("{") and line.endswith("}")):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            part = ev.get("part") or {}
            if ev.get("type") == "text" or part.get("type") == "text":
                texts.append(part.get("text", ""))
        candidate = "\n".join(texts) or out
        try:
            return json.loads(candidate[candidate.index("{") : candidate.rindex("}") + 1])
        except (ValueError, json.JSONDecodeError):
            # ponytail: noop on unparseable output; tighten parsing if real runs show noise
            return {"action": "noop"}
