# sandbox eval

Mock agents (CI): `python -m sandbox.run_eval --all`

Real agent via opencode CLI:

```sh
EPIRES_EVAL_MODEL=anthropic/claude-sonnet-4-5 python -m sandbox.run_eval --all --agent opencode
python -m sandbox.run_eval --report
```

Each scenario x variant gets a persistent workspace at `sandbox/results/ws_<scenario>__<variant>/`
with `.opencode/opencode.json` (MCP: epires) and `AGENTS.md`; the store lives there too.
