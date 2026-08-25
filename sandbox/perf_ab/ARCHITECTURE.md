# Epires optimization benchmark architecture

Status: design specification for the next `perf_ab` iteration.

This document defines a benchmark for answering two different questions:

1. Does enabling Epires improve the outcome of an ordinary coding-agent run?
2. Does the Epires research methodology make better use of a fixed experimental
   budget than a neutral iterative agent?

The answers must be reported separately. The first is a product-behavior A/B.
The second is an evaluation of the methodology itself. A one-shot run cannot
answer the second question, while an externally imposed search algorithm can
hide the product behavior measured by the first.

The design adopts the useful core of
[AIDE](https://arxiv.org/html/2502.13138v1): executable candidates, an explicit
solution lineage, small measurable changes, and repeated evaluator feedback.
It adds stricter treatment isolation, paired budgets, task-level holdouts, and
component ablations required to make claims about Epires and VSA.

## 1. Claims the benchmark may make

The primary system claim is:

> Under the same model, task, starting repository, evaluator access, and
> externally enforced budget, Epires changes the distribution of correct
> hidden-task performance relative to bare OpenCode.

This is deliberately a system claim. A full `bare` versus `epires` difference
must not be attributed to VSA, hypothesis tracking, delegation, web research,
or any other individual mechanism.

A mechanism claim requires a one-factor ablation:

> Holding the rest of the Epires policy and stored observations fixed, replacing
> retrieval implementation X with retrieval implementation Y changes hidden
> task performance or a preregistered diagnostic endpoint.

The benchmark does not attempt to show that Epires is universally better, that
one successful optimization validates a research hypothesis, or that the best
of many post-hoc configurations is a valid estimate of expected performance.

## 2. Two protocols

### 2.1 Protocol N: natural product behavior

Protocol N preserves the benchmark that already exists.

```text
fresh task copy ──> one OpenCode invocation ──> final hidden grader
                         │
                  bare or Epires setup
```

Both conditions receive the same neutral request, model, model variant, task,
and external limits. Epires may naturally spend more tokens or time because
that overhead is part of the product. This protocol answers whether a user
benefits from enabling Epires under its normal defaults.

Primary endpoint:

```text
paired hidden score of the final working tree
```

Protocol N must remain available after Protocol S is implemented. It catches
failures such as excessive planning, unnecessary research, delegation overhead,
or the agent stopping before it implements an obvious improvement.

### 2.2 Protocol S: budget-matched search behavior

Protocol S evaluates optimization ability. The harness runs a sequence of
agent decisions and public evaluations under a common budget envelope.

```text
                         ┌──────────────────────────────┐
                         │ externally enforced budget │
                         └──────────────┬───────────────┘
                                        │
fresh task ──> bootstrap ──> propose ──> execute ──> public evaluate
                                  ▲                       │
                                  │                       ▼
                              select/branch <── record candidate
                                  │
                                  └── stop ──> public selection ──> hidden grade
```

The external shell performs only neutral mechanics:

- create isolated workspaces;
- enforce budgets;
- snapshot every candidate;
- run the public evaluator;
- return factual output to the same condition;
- ask the condition for its next action;
- select the final candidate using a preregistered public rule;
- run the hidden verifier exactly once on the selected candidate.

The shell must not propose hypotheses, recommend optimizations, choose research
topics, summarize lessons, or rank branches for the agent. Those decisions are
part of the condition being evaluated.

The initial Protocol S comparison is:

| Condition | Iterative feedback | Research policy | Epires store |
|---|---:|---|---:|
| `bare_search` | yes | model's ordinary behavior | no |
| `epires_search` | yes | normal Epires behavior | yes |

`bare_search` is not one-shot. On every round it receives the same current
workspace and the latest public evaluator output, then gets a neutral request
to continue optimizing. This prevents the main comparison from becoming
"iterative Epires versus one-shot bare".

## 3. Evaluation boundaries

Every task has three information layers.

```text
Layer 1: public development signal
  visible source, tests, benchmark output and errors
  used repeatedly during an episode

Layer 2: within-task hidden verification
  additional inputs, distributions and end-to-end workloads
  never copied to the workspace
  run once for the public-selected final candidate

Layer 3: task-family holdout
  entire tasks not used while designing or choosing an Epires variant
  used only for a preregistered generalization evaluation
```

Layer 2 measures whether an episode overfit or gamed its visible evaluator.
Because repeated harness development can indirectly overfit Layer 2, Layer 2
is validation for benchmark development, not a permanent test set. Layer 3 is
required for a strong generalization claim.

The following isolation rules are invariants:

- A fresh Git repository is created for every episode.
- A fresh, empty Epires database is created for every Epires episode.
- No benchmark-specific hypothesis, document, embedding, VSA vector, transcript,
  or previous solution is preloaded.
- Provider authentication may be copied into the sandbox; global skills,
  configuration, sessions, caches, and memories may not.
- Hidden grader code and hidden inputs never enter the agent workspace.
- Only declared submission paths are copied into the final grading workspace.
- The pristine baseline is rebuilt and measured during every hidden grade.
- Public and hidden performance processes are not run concurrently with another
  performance process on the same allocated CPU set.

## 4. Episode state machine

An optimization episode consists of immutable candidate records. A candidate is
not merely a Git state: it includes the decision that produced the state and the
evidence obtained afterward.

```text
NEW
  │
  ├─ baseline fails ───────────────> REPAIR
  │                                  │
  │                                  └─ public evaluation
  │
  └─ baseline valid ───────────────> FIRST_PROBE
                                      │
                                      └─ public evaluation
                                             │
                           ┌─────────────────┴──────────────┐
                           ▼                                ▼
                       IMPROVE                           BRANCH
                           │                                │
                           └──────── public evaluation ─────┘
                                             │
                                      SELECT_OR_STOP
```

### 4.1 Bootstrap rule

For a neutral or nearly empty project, the first action should not be an
unbounded research phase. Each condition must first produce one obvious,
testable change and measure it. In Epires this becomes a hypothesis with:

- expected mechanism;
- predicted direction of the primary public metric;
- falsification criterion;
- intended changed paths;
- parent candidate.

The rule is procedural, not semantic: the benchmark does not award points for
using the word "hypothesis". Only the resulting artifact and measurements affect
the task score.

### 4.2 Complexity and escalation gate

The suggested default Epires policy has four observable levels:

| Level | Evidence available | Allowed response |
|---|---|---|
| G0 | no measured candidate | implement and measure one obvious probe |
| G1 | one or more clean measurements | make an atomic evidence-driven improvement |
| G2 | plateau, anomaly, or conflicting results | branch, retrieve prior evidence, or run targeted research |
| G3 | repeated unresolved failures or interacting causes | broader decomposition or delegation |

Web research and delegation are therefore available but not mandatory startup
steps. Their use is logged. The model is not told a wall-clock deadline or a
numeric speedup target. The harness stops externally when the budget is spent.

### 4.3 Candidate transitions

Each transition declares one of four operators:

- `draft`: create an independent initial approach;
- `repair`: make a failing candidate valid without intentionally changing its
  core approach;
- `improve`: make one primary mechanism change to a valid candidate;
- `branch`: start a new lineage or fork a strong candidate with a materially
  different strategy.

"Atomic" is a research discipline, not an artificial patch-size limit. An idea
may require several related code edits, but a candidate must not combine
unrelated optimization hypotheses if the effects can be measured separately.

The agent may choose any earlier candidate as a parent. The harness never
forces greedy selection of the current best, but always preserves the best
valid public candidate so a later regression cannot erase it.

## 5. Budget contract

Budget enforcement belongs to the harness, not the prompt. Each episode records
a budget vector:

```json
{
  "max_agent_invocations": 12,
  "max_public_evaluations": 12,
  "max_input_tokens": null,
  "max_output_tokens": null,
  "max_provider_cost_usd": null,
  "max_episode_wall_seconds": 900
}
```

The first implementation uses invocations and public evaluations as the hard
compute-matching dimensions because free providers may not expose stable price
or token metadata. Wall time is a safety timeout, not the optimization target.
When reliable token and provider-cost usage exists, those become additional
hard constraints rather than replacements for the evaluation count.

Rules:

- A condition may stop early; unused budget is recorded and not imputed.
- Parallel model calls count individually against the invocation budget.
- Parallel execution cannot pack extra public evaluations into the same nominal
  budget.
- Failed, timed-out, malformed, and duplicate proposals consume budget.
- Evaluator retries caused by harness infrastructure do not consume agent
  budget and are marked separately.
- The headline comparison uses the same budget vector for both paired arms.

Results are also checkpointed at `1, 2, 4, 8, 12` public evaluations. This
produces an anytime curve and reveals whether a condition helps early search,
late search, or only spends more resources.

## 6. Candidate selection and hidden grading

The final candidate is selected without hidden information:

1. discard candidates failing public correctness;
2. choose the highest preregistered public primary score;
3. break ties by lower public worst-workload runtime;
4. break any remaining tie by earlier evaluation index;
5. restore the exact recorded patch for that candidate;
6. run the hidden verifier once.

The hidden verifier may rerun internally for timing stability, but its result is
never returned to the agent and never used to select another candidate in the
same episode.

Best hidden score over all candidates is not computed during an episode. It may
be computed later over frozen traces in a separately labelled oracle audit, but
must never be reported as the task score: it uses information unavailable to
the agent and introduces best-of-N selection bias.

## 7. Metrics

### 7.1 Primary system endpoint

The system verdict is hierarchical because a zero score for an incorrect
candidate cannot be represented by a log-ratio without an arbitrary epsilon:

1. hidden valid-submission/correctness rate;
2. hidden performance among pairs in which both selected candidates are valid.

Incorrect outcomes are always counted in the first endpoint and are never
silently discarded as "failed runs". A treatment is called better only if it
passes a preregistered correctness non-inferiority gate and improves the second
endpoint. If correctness regresses, faster surviving candidates do not override
that regression.

For each jointly valid `(task, model, seed, pair)`:

```text
score = hidden score of the public-selected candidate
paired effect = log(score_treatment / score_control)
```

Across jointly valid pairs, the performance ratio is:

```text
exp(mean(paired effects))
```

This is the geometric mean treatment/control ratio conditional on both arms
being valid. Reports must also include all invalid-arm outcomes, the paired
median, wins/ties/losses, task-level results, and paired confidence intervals
once the preregistered sample size is reached. The analyzer must distinguish an
agent-produced invalid submission from an infrastructure failure; neither may
be folded into the same exclusion bucket.

### 7.2 Secondary system endpoints

- valid final-candidate rate;
- best-public-score versus evaluation count;
- area under the best-public-score/budget curve;
- time and evaluations to first correct candidate;
- time and evaluations to first improvement over the pristine baseline;
- worst hidden workload ratio;
- public-to-hidden generalization gap;
- retained speedup in an end-to-end workload;
- model invocations, tokens, provider cost, CPU time, and wall time;
- changed-path and submission-policy violations.

Secondary improvements cannot override a regression in the preregistered
primary endpoint.

### 7.3 Hypothesis-process diagnostics

These metrics describe how Epires worked. They do not contribute to task score:

- hypotheses proposed, tested, supported, contradicted, or left unresolved;
- fraction of hypotheses registered before their associated code change;
- prediction accuracy for metric direction (`improve`, `neutral`, `regress`);
- calibration/Brier score when a confidence is supplied;
- fraction of changes that isolate one declared mechanism;
- evaluator calls per accepted improvement;
- branch diversity and lineage depth;
- fraction of anomalies assigned to explicit auxiliary assumptions;
- rate at which later conflicting evidence revises an earlier verdict;
- research/delegation invocation rate by gate level;
- useful-evidence rate: retrieved or researched evidence cited by a subsequent
  candidate whose mechanism matches the evidence.

These diagnostics can explain a system result but cannot rescue a losing
hidden score.

## 8. VSA evaluation

VSA has two evaluation tracks.

### 8.1 Offline retrieval diagnostics

The existing `vsa_diagnostics.py` compares lexical FTS, pure VSA, and hybrid
retrieval over an identical corpus and relevance ground truth. It measures
retrieval quality, relational correctness, latency, and memory. This is a unit
and component benchmark; it says nothing by itself about coding outcomes.

### 8.2 Retrieval replay and end-to-end ablation

First, a replay ablation sends an identical frozen query stream over an
identical episode-local document set to every backend. This isolates retrieval
ranking, latency, and memory. It cannot establish downstream task utility.

Second, the end-to-end matrix holds the starting task, Epires policy,
pre-existing episode-local documents, result count, and budget fixed while
changing only the retrieval backend:

| Condition | Retrieval backend | Other Epires behavior |
|---|---|---|
| `epires_no_retrieval` | none | fixed |
| `epires_fts` | lexical FTS | fixed |
| `epires_vsa` | pure VSA | fixed |
| `epires_hybrid` | current hybrid | fixed |

This matrix is run only after the full-system comparison establishes a reason
to inspect retrieval. All four arms start with the same episode-local documents;
none receives benchmark-specific seed memories. Later queries and actions may
diverge as a downstream consequence of different retrieved results; that
divergence is part of the end-to-end treatment effect. Retrieval latency and
tokens count against the same budget.

Additional diagnostic questions are:

- Did the requested relevant item appear in top-k?
- Did the agent use the retrieved evidence in its next decision?
- Did retrieval resurrect a previously productive branch?
- Did it surface contradictory evidence rather than only supporting evidence?
- Was the retrieved evidence stale, task-inapplicable, or associated with a
  different auxiliary assumption?

A full-Epires improvement alone cannot be attributed to VSA.

## 9. Reward-hacking defenses

The public evaluator is an optimization signal and is therefore assumed to be
gameable. Every task must include independent hidden variation in at least two
of these dimensions:

- input sizes and distributions;
- random seeds;
- alignment and boundary cases;
- thread counts or CPU affinity;
- call patterns and repetition counts;
- clean-build environment;
- end-to-end consumer workload.

For performance tasks, define retained speedup as:

```text
hidden end-to-end speedup / claimed public speedup
```

The report flags reward-hacking suspicion when retained speedup is below a
preregistered threshold, when public improvement becomes hidden slowdown, or
when correctness fails. The flag is an anomaly, not proof of intent.

The harness also verifies protected-file hashes, declared submitted paths,
clean recompilation, deterministic output tolerances, and the absence of
benchmark-process manipulation.

## 10. Task suite

Tasks should be medium-sized, executable, and fast enough to support repeated
feedback. A task is eligible when:

- an unoptimized implementation is understandable in one repository session;
- public correctness plus timing completes in at most a few seconds;
- hidden verification completes in tens of seconds, not hours;
- multiple real optimization strategies exist;
- correctness can be checked independently;
- the baseline has no single textual hint revealing the intended solution;
- public and hidden distributions can differ meaningfully;
- measured performance is stable on the benchmark host.

The initial development suite should contain at least three mechanically
different tasks:

1. `ragged_softmax_cpp` — irregular reduction, vectorization and scheduling;
2. `bitset_intersection_cpp` — data representation, memory access and SIMD;
3. `json_structural_scan_cpp` — branch behavior, validation and vector scanning.

Candidate task-level holdouts should come from a different code shape, for
example a small GEMM/microkernel or image-stencil task. Task choice is locked
before comparing Epires variants. A task that is unstable across clean replays
is quarantined rather than silently removed after seeing treatment results.

## 11. Counterbalancing and claims

Bare and Epires episodes may run concurrently on separate allocated resources.
Their public and hidden performance measurements may not share contended CPU
cores. When isolation is unavailable, the paired arms run sequentially with
alternating order.

Minimum stages:

1. Engineering smoke: one task, one seed, both arms. Only verifies execution.
2. Pilot: three tasks, at least three paired seeds. Estimates variance and
   identifies evaluator failures.
3. Preregistered system comparison: locked tasks, conditions, model, budgets,
   seeds, primary endpoint, exclusion rules, and analysis.
4. Component ablation: performed only after the system comparison, changing one
   dimension per contrast.
5. Task-level holdout: selected system variants are evaluated without further
   tuning.

The report must distinguish:

- `smoke_only`;
- `pilot_estimate`;
- `preregistered_internal_result`;
- `task_holdout_result`.

Single-seed observations and deltas within measured run-to-run noise are not
accepted as architecture evidence. If two results conflict, both remain in the
record and the conclusion is revised rather than selecting the favorable run.

## 12. Durable artifacts

Every run is self-contained and replayable:

```text
results/<batch_id>/
├── manifest.json
├── preregistration.json
└── <task_id>/<pair_id>/<condition>/
    ├── episode.json
    ├── environment.json
    ├── transcript.jsonl
    ├── candidates/
    │   └── <candidate_id>/
    │       ├── decision.json
    │       ├── change.patch
    │       ├── public_eval.json
    │       ├── stdout.txt
    │       └── stderr.txt
    ├── selected_candidate.json
    ├── hidden_grade.json
    └── result.json
```

`decision.json` has a condition-neutral envelope. Epires-specific fields are
optional diagnostics:

```json
{
  "candidate_id": "c07",
  "parent_id": "c03",
  "operator": "improve",
  "summary": "reduce redundant offset loads",
  "predicted_direction": "improve",
  "changed_paths": ["src/kernel.cpp"],
  "hypothesis_id": "H-4",
  "assumption_ids": ["AUX_COMPILER_VECTORIZES_INNER_LOOP"]
}
```

`episode.json` records the complete candidate DAG, budget ledger, selection
rule, stop reason, tool invocations, Epires configuration hashes, OpenCode and
model identifiers, Git commits, and artifact hashes. Raw transcripts are kept
for audit but are not required by the scoring path.

## 13. Component architecture

```text
BatchScheduler
  ├── PairScheduler
  │     ├── EpisodeRunner(bare_search)
  │     └── EpisodeRunner(epires_search)
  │
  ├── ResourceAllocator
  └── ResultWriter

EpisodeRunner
  ├── WorkspaceFactory       existing runner isolation
  ├── ConditionAdapter       OpenCode / Epires setup and continuation
  ├── BudgetLedger           invocations, evals, tokens, cost, safety timeout
  ├── CandidateStore         Git snapshots, patches, lineage and artifacts
  ├── PublicEvaluator        visible correctness and performance feedback
  ├── PublicSelector         preregistered final-candidate rule
  └── HiddenVerifier         existing external grader boundary

Analysis
  ├── PairAggregator         paired log-ratios and exclusions
  ├── AnytimeAnalyzer        score-versus-budget curves
  ├── GeneralizationAudit    public/hidden and task-holdout gaps
  └── ProcessDiagnostics     hypotheses, retrieval, VSA and delegation
```

The condition adapter should prefer OpenCode session continuation when it is
reliable. If continuation cannot provide reproducible context isolation, every
round may start a fresh model call with a mechanically constructed state packet.
Both arms must use the same continuation mode.

## 14. Mapping to the current implementation

The existing implementation remains useful:

| Current file | Role in the new architecture |
|---|---|
| `runner.py` | workspace isolation, treatment setup, subprocess control, hidden grading |
| `run.py` | seed/order scheduling, extended to protocol and budget selection |
| `analyze.py` | paired primary analysis, extended with checkpoints and confidence intervals |
| `vsa_diagnostics.py` | offline retrieval component track |
| `tasks/*/task.json` | extended with public-evaluator and hidden-selection metadata |

New modules should be introduced without making `runner.py` own search policy:

```text
episode.py          protocol-S state machine
budget.py           external budget accounting
candidates.py       immutable snapshots and public selection
adapters.py         bare/Epires round interface
schemas.py          versioned records and validation
```

Suggested CLI additions:

```text
--protocol natural|search
--max-agent-invocations N
--max-public-evals N
--checkpoints 1,2,4,8,12
--continuation session|state-packet
--resource-set <allocator-specific value>
```

## 15. Implementation order

1. Extract reusable workspace setup and hidden grading from the current
   single-invocation runner without changing Protocol N behavior.
2. Add versioned candidate and episode schemas plus immutable patch snapshots.
3. Implement a public evaluator adapter for `ragged_softmax_cpp`.
4. Implement `bare_search` with fixed rounds and neutral factual feedback.
5. Implement `epires_search` using the same round and budget interface.
6. Add public-only candidate selection and one-shot hidden grading.
7. Add checkpoint/anytime analysis and paired bootstrap intervals.
8. Add two mechanically different development tasks.
9. Run a variance pilot before locking the preregistration.
10. Add one-factor VSA/retrieval ablations only after the system pipeline is
    stable.

## 16. Acceptance criteria for the harness

Protocol S is ready for a research pilot only when tests demonstrate that:

- both arms receive byte-identical task sources and public feedback schemas;
- budget exhaustion stops both arms at the same accounting boundary;
- hidden output cannot reach the agent or candidate selector;
- restoring any candidate reproduces its submitted-path hashes;
- the public selector returns the same candidate deterministically;
- failed and timed-out proposals consume agent budget;
- infrastructure retries are distinguishable from agent attempts;
- fresh Epires stores contain no prior-task data;
- protected-file modifications are detected;
- performance graders never overlap on the same CPU allocation;
- Protocol N results remain backward-compatible with the current analyzer.

Only after these conditions hold should benchmark outcomes be interpreted as
evidence about the agent systems rather than about the harness.
