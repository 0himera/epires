# Web-policy ablation pilot

Run date: 2026-08-24 (Europe/Moscow)
Model: `openai/gpt-5.6-luna-fast`, variant `low`
Task: `ragged_softmax_cpp`
Matrix: 5 conditions × 3 counterbalanced repetitions
Raw results: `/tmp/epires-web-ablation-luna-fast-low-v1`

## Question

Should a minimal web search be mandatory before an agent solves a local medium-sized optimization
task, and should that instruction live in an Epires skill or directly in `AGENTS.md`?

This is a pilot on one task and one model. It can reject a policy bundle for this setting, but it
cannot establish a general causal effect of web search, prompt placement, or Epires.

## Controlled conditions

All Epires treatments used the same direct six-step evidence loop: inspect, measure, register one
hypothesis, implement one hypothesis, verify, and log experiment/evidence. Delegation, VSA, gap
analysis, scoring, and audit were disabled. The task prompt, model, variant, hidden evaluator, and
timeouts were fixed.

| Condition | Search policy | Policy location |
|---|---|---|
| `bare` | none; ordinary OpenCode | none |
| `epires_probe_no_web` | explicitly no web | skill |
| `epires_web_task_skill` | one search after source inspection, before baseline | skill |
| `epires_web_task_agents` | same task-first search | `AGENTS.md` |
| `epires_web_baseline_skill` | one search after baseline | skill |

Web credentials were explicitly copied into each isolated HOME. Required-web trials failed before
agent execution if credentials were unavailable. Secrets were not written to result records.

## Hidden performance results

The primary score is the correctness-gated geometric mean of paired hidden workload speedups. All
15 trials completed, passed all 6/6 hidden correctness cases, reran the baseline, and changed
`src/kernel.cpp`.

| Condition | Scores | Geomean | Median | Median agent time |
|---|---:|---:|---:|---:|
| `bare` | 3.447, 4.567, 2.088 | 3.204 | 3.447 | 58.3 s |
| `epires_probe_no_web` | 2.585, 3.586, 3.879 | 3.300 | 3.586 | 92.0 s |
| `epires_web_task_skill` | 1.058, 1.685, 1.697 | 1.446 | 1.685 | 84.2 s |
| `epires_web_task_agents` | 1.535, 3.811, 1.689 | 2.146 | 1.689 | 85.1 s |
| `epires_web_baseline_skill` | 1.548, 1.046, 1.491 | 1.341 | 1.491 | 83.2 s |

Paired comparisons use the log-ratio of hidden primary scores:

| Treatment / control | Geomean paired ratio | Wins | Conservative reading |
|---|---:|---:|---|
| no-web / bare | 1.030 | 1/3 | unstable; no demonstrated system gain |
| task-first skill / no-web | 0.438 | 0/3 | this mandatory-web bundle regressed |
| baseline-first skill / no-web | 0.406 | 0/3 | the closest one-factor web addition regressed |
| task-first AGENTS / no-web | 0.650 | 1/3 | this mandatory-web bundle regressed |
| task-first AGENTS / task-first skill | 1.484 | 2/3 | placement is a follow-up candidate, not confirmed |
| task-first skill / baseline-first skill | 1.078 | 2/3 | no stable ordering effect established |

The no-web/bare geomean is slightly above one despite losing two of three pairs because the third
pair is large. That is a warning against reporting only the aggregate that looks best.

## Protocol compliance

- All 9 required-web trials made exactly one `epires_parallel_web_search` call and all returned
  `status=success` with three results.
- All task-first searches occurred before the first public `make bench`; all baseline-first searches
  occurred after it. All occurred before the first implementation patch.
- All 3 no-web Epires trials made zero web calls.
- All 12 Epires trials completed one hypothesis, one experiment, and at least one successful
  evidence record. Two trials retried a malformed hypothesis registration before succeeding; this
  did not create a second registered hypothesis.
- Skill conditions loaded the Epires skill; the `AGENTS.md` placement condition had no skill file
  and made no skill call.

The web results were relevant but mostly reinforced obvious directions such as eliminating the
per-row allocation, storing exponentials in the output/scratch buffer, reciprocal normalization,
and SIMD. The sole high-scoring web/AGENTS run registered a hypothesis that also parallelized
independent rows. This suggests, but does not prove, that the mandatory lookup anchored several
runs on a narrower local optimization already visible in the source.

## Verdict and next policy

The data do **not** support “always perform a web search before solving” for an obvious local
optimization task. The strongest controlled comparison is baseline-first skill versus matched
no-web skill: it changed only the required search step and lost all three pairs, with a paired
geomean ratio of 0.406. This refutes the evaluated bundle
`<mandatory minimal web + this prompt + Luna Fast low + ragged_softmax task + current search
results>`, not web research in general.

The production candidate should therefore remain evidence-gated:

1. Inspect the task and source.
2. Run one obvious, reversible local baseline/probe.
3. Search only when the observation exposes an external knowledge gap, an unexplained anomaly,
   conflicting evidence, or when the task intrinsically depends on current/external facts.
4. If search is triggered, use one precise fast query first and expand only when it changes the next
   decision.

Before adopting that rule generally, rerun the preregistered matrix on at least three heterogeneous
tasks. Add a knowledge-dependent task where web search has a plausible positive mechanism; a suite
containing only self-contained kernels is biased toward local reasoning. Also repeat the
`AGENTS.md` versus skill placement comparison because its apparent 1.484 ratio comes from only
three pairs and one unusually strong run.

## Excluded smoke

`/tmp/epires-web-ablation-smoke-v1` ended before model execution with a retryable connection error
to the OpenAI Responses API and produced no code change. Its baseline-like hidden score was not
included. `/tmp/epires-web-ablation-smoke-v2` was a successful engineering smoke used only to
verify real web-tool availability and transcript ordering; it was also excluded from the
preregistered 3×5 matrix.
