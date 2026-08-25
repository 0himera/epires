# External performance A/B benchmark

The next architecture, including the budget-matched iterative protocol and
VSA mechanism ablations, is specified in [ARCHITECTURE.md](ARCHITECTURE.md).

`perf_ab` measures whether Epires helps a real coding agent produce a better
artifact. It deliberately does **not** grade Epires vocabulary, ledger usage,
hypothesis counts, or compliance with an Epires-shaped answer schema.

## Primary experiment

Each trial starts from the same commit of a standalone project and gives the
same task to the same OpenCode version and model:

- `bare`: ordinary OpenCode, with no Epires MCP, skill, or generated
  `AGENTS.md`;
- `epires`: the normal Epires initialization, OpenCode skill, MCP server, and
  research store.

The component ablation matrix keeps the model, task prompt, limits, and hidden
grader fixed:

| Condition | Policy | MCP/store | Initial implementation |
|---|---|---|---|
| `bare` | none | no | direct |
| `epires_mcp_only` | none | yes | direct |
| `epires_minimal` | one obvious hypothesis and one measured probe | yes | direct |
| `epires_probe` | Probe-Measure-Escalate gate | yes | direct first; escalate on evidence |
| `epires_direct` | full Epires protocol | yes | direct, no delegation |
| `epires` | full Epires protocol | yes | delegated |

This separates tool availability, a minimal hypothesis ledger, adaptive
escalation, the full research protocol, and mandatory delegation. It remains a
component ablation rather than proof of causality from one run: use repeated,
counterbalanced pairs and interpret effects within timing/agent variance.

Workspaces are fresh Git repositories outside the Epires source tree. The
agent sees a fast public correctness/performance loop. Final scoring is done by
an external verifier that is never copied into the agent workspace.

The first task is `ragged_softmax_cpp`, a medium-sized C++ kernel optimization
problem. A public run takes a few seconds. The private evaluator uses additional
row-length distributions and seeds, recompiles a pristine baseline with the
same flags, and interleaves baseline/candidate measurements in one process.

Correctness is a hard gate. The primary continuous endpoint is:

```text
geometric mean of paired hidden speedups
```

The raw per-workload timings, worst-regime speedup, compile outcome, changed
paths, wall time, OpenCode transcript, token/cost metadata when available, and
Epires telemetry are retained. Epires telemetry is diagnostic only.

## Claims and repetitions

A smoke run proves only that the harness executes. It is not evidence that
either condition is better. A comparison should use at least three independent
agent runs per `(task, model, condition)`, randomized/counterbalanced condition
order, the same machine allocation, and a preregistered primary aggregation.
Baseline timing is rerun for every final evaluation rather than reused from a
historical file.

Recommended progression:

1. one task × both conditions as an engineering smoke test;
2. three local kernel tasks × three agent runs as a pilot;
3. a replay-stable external subset of SWE-fficiency for generalization;
4. only after a positive full-system A/B, run component ablations.

For a focused delegation comparison use `--condition delegation_ablation`.
For all Epires policies use `--condition ablation`; include the bare control
with `--condition all`. The analyzer compares any selected pair via
`--control-condition` and `--treatment-condition`.

The focused `web_ablation` matrix holds the direct evidence loop fixed and
varies only: no web, one minimal search after reading the task, the same search
after the baseline, and whether the task-first policy lives in `SKILL.md` or
directly in `AGENTS.md`. Web conditions require the explicit
`--enable-web-auth` flag. The runner copies only Epires web credentials into the
temporary HOME, records availability as a boolean, and never writes the key to
the result record. A required-web trial fails before agent execution when the
credential is absent.

## VSA diagnostics and ablations

VSA is evaluated on a separate diagnostic track with the same corpus, queries,
and relevance ground truth for all retrievers. It reports retrieval quality,
latency, memory, and exact-BFS agreement for relational queries. These numbers
help explain an A/B result but cannot increase the task score.

For causal attribution, later conditions can remove VSA retrieval tools while
retaining the rest of Epires. A full-Epires gain alone must not be attributed to
VSA, because skill instructions, ledger structure, MCP tools, and context all
change together.

## Why this shape

The design borrows the executable, correctness-gated artifact evaluation of
[KernelBench](https://github.com/ScalingIntelligence/KernelBench), the
repository-level workload/test separation of
[SWE-fficiency](https://github.com/swefficiency/swefficiency), the independent
performance-test idea of [GSO](https://github.com/gso-bench/gso), and the
anti-reward-hacking focus of
[SOL-ExecBench](https://github.com/NVIDIA/SOL-ExecBench).

It intentionally stays smaller than RE-Bench: the feedback loop should take
seconds and the final verifier tens of seconds, not hours. Performance results
remain machine-local unless reproduced because a 2026 cross-machine audit of
GSO, SWE-Perf, and SWE-fficiency found substantial task-level instability.

## Layout

```text
sandbox/perf_ab/
├── runner.py                 # isolated OpenCode trial orchestration
├── run.py                    # CLI
├── analyze.py                # paired treatment/control aggregation
├── vsa_diagnostics.py        # secondary component diagnostics
└── tasks/ragged_softmax/
    ├── task.json
    ├── project/              # copied into the agent workspace
    └── hidden/               # external final evaluator, never copied
```

Run a counterbalanced three-pair pilot and aggregate it:

```bash
python -m sandbox.perf_ab.run \
  --task sandbox/perf_ab/tasks/ragged_softmax \
  --model provider/model --trials 3 --order-seed 42 \
  --output /tmp/epires-perf-ab-results
python -m sandbox.perf_ab.analyze /tmp/epires-perf-ab-results \
  --output /tmp/epires-perf-ab-report.json
```

Run the full matrix, then compare the adaptive gate to bare:

```bash
python -m sandbox.perf_ab.run \
  --task sandbox/perf_ab/tasks/ragged_softmax \
  --model provider/model --variant low --condition all --trials 3 \
  --order-seed 42 --output /tmp/epires-perf-ab-matrix
python -m sandbox.perf_ab.analyze /tmp/epires-perf-ab-matrix \
  --control-condition bare --treatment-condition epires_probe \
  --output /tmp/epires-probe-vs-bare.json
```

Run the web-policy ablation:

```bash
python -m sandbox.perf_ab.run \
  --task sandbox/perf_ab/tasks/ragged_softmax \
  --model provider/model --variant low --condition web_ablation --trials 3 \
  --enable-web-auth --order-seed 42 --output /tmp/epires-web-ablation
```
