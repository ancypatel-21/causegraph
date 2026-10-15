# Research protocol

This file tracks the experimental discipline requirements from spec
section 9.4 and the reproducibility requirements from section 17, and what
is (and is not yet) satisfied as of Phase 9.

## Satisfied

- Every `BenchmarkRun` records `git_sha`, `scenario_id`, `scenario_version`
  (content hash of the scenario manifest), `seed`, `workload_config`,
  `method`, and timestamps — nothing is persisted without these.
- Scenario manifests are public, versioned YAML files
  (`benchmark/scenarios/*.yaml`).
- Results are written twice (Postgres + standalone JSON under
  `experiments/results/`), and the evaluator refuses to overwrite an
  existing result file for the same run id.
- One command starts the system (`make up`) and one command runs a smoke
  benchmark (`make smoke`).
- All required baselines (B0/B1/B2/B3/B4) and CauseGraph (CG) run through
  the same evaluator (`benchmark/baselines/registry.py`), satisfying
  "Required baselines run through the same evaluator" from the full-project
  acceptance checklist (spec section 23).
- Intervention evidence (spec section 5.3) is real, not simulated: when
  `ALLOW_INTERVENTION_TESTS=1`, the evaluator actually disables the live
  fault, measures the symptom, and restores it — recorded in both
  `BenchmarkRun.metrics["intervention_scores"]` and as an `Evidence` row
  with `reliability=0.95`. It is strictly benchmark/dev-mode only (never
  exposed over HTTP or any agent tool), and the I(c) term defaults to
  0.0 whenever it wasn't run, never counting absence as evidence either
  way.
- An LLM is used (B2, B4) behind a provider-neutral adapter
  (`causegraph/llm/provider.py`) whose default provider needs no API key,
  so the project remains useful without a paid model API (spec section 14,
  step 18). Model/provider is recorded on every `RankingResult` and, when
  a real provider is used, is pinned via `CAUSEGRAPH_LLM_MODEL`.
- The investigator agent (`causegraph/agent/`) satisfies "LLM agent is
  bounded by typed evidence tools" (spec section 23 acceptance checklist):
  every tool is hard-capped, two are honest "not available" stubs rather
  than fabricated data, and `needs_human_approval` is always `true` since
  no remediation executor exists yet. The agent never changes the ranked
  `Hypothesis` list that the benchmark metrics are computed from — see
  `docs/architecture.md`'s Phase 8 section for a concrete case where the
  agent's own pick disagreed with it, demonstrated live, not hypothetical.
- **A dev/held-out split exists and was honored**: `Scenario.split`
  (`dev` or `held_out`). `cache-ttl-001` and `redis-unavailable-001` were
  built and labeled `held_out` *before* being run even once, and their
  results below are reported exactly as they came out, including the
  failures.
- **Ablation studies were actually run**, not just scaffolded — results
  below, including a negative one.
- **Calibration is measured, not cosmetic** (spec section 9.3 and the
  full-project acceptance checklist, spec section 23): real Brier score
  and ECE computed from 10 live runs (`benchmark/evaluator/evaluator.py:
  run_calibration_study`, pure math in `causegraph/calibration.py`) —
  see below.
- **Repeated runs with multiple seeds exist**, per spec section 9.4 —
  `run_scenario`'s `seed` parameter overrides the scenario manifest's
  canonical seed so repeats vary the workload instead of replaying it
  identically. Still only 2 seeds per scenario so far (see the caveat
  below) — a step in this direction, not the full discipline yet.

## Real findings (Phase 9, one run each — see caveat below)

### `redis-unavailable-001` (held-out): a case where CauseGraph helps

| method | top-1 | top-3 | MRR | rank |
|---|---|---|---|---|
| `causegraph` | ✅ | ✅ | 1.00 | 1 |
| `rules` | ✅ | ✅ | 1.00 | 1 |
| `graph_only` | ❌ | ✅ | 0.50 | 2 |

`graph_only` ranked `model-service` (a downstream reflection) ahead of
the true cause, `feature-store`. `causegraph` got it right — specifically
because of the change-event term; `rules` got it right by having a
threshold for `feature-store`'s new signal (added this phase).

### `cache-ttl-001` (held-out, "quiet root cause"): a case where everything struggles, and why

The TTL fault means `feature-worker` keeps writing valid data — its own
anomaly signal never fires. No method got top-1:

| method | top-1 | top-3 | MRR | rank |
|---|---|---|---|---|
| `causegraph` | ❌ | ✅ | 0.50 | 2 |
| `graph_only` | ❌ | ❌ | 0.00 | — (not in top 5) |
| `rules` | ❌ | ❌ | 0.20 | 5 |

Ablating `causegraph` on this scenario:

| variant | top-1 | top-3 | MRR | rank |
|---|---|---|---|---|
| `causegraph_full` | ❌ | ✅ | 0.50 | 2 |
| `causegraph_no_change_events` | ❌ | ❌ | 0.00 | — (not in top 5) |
| `causegraph_no_temporal_ordering` | ✅ | ✅ | 1.00 | 1 |
| `causegraph_no_propagation_consistency` | ✅ | ✅ | 1.00 | 1 |
| `causegraph_no_intervention_evidence` | ❌ | ✅ | 0.50 | 2 |

Two real findings here, not noise:

1. **The change-event term is load-bearing for quiet root causes.**
   Removing it drops `feature-worker` out of the top 5 entirely — without
   C(c), there is *nothing* distinguishing it from any other quiet node.
   This is exactly the case CauseGraph's design argues change-event
   evidence exists for.
2. **The X (contradicting-evidence) term has a real, documented weakness
   here.** `feature-worker` has real telemetry showing it's quiet
   (because the fault doesn't touch its own signal), so X(c)=1.0 and its
   score is penalized for looking "healthy" — even though it's the actual
   root cause. This is why `causegraph_full` doesn't get top-1 even with
   C(c) helping: the X penalty partially cancels it out. Removing T or P
   happens to tip the balance back in `feature-worker`'s favor on this
   specific scenario. This is a genuine limitation of the current fixed
   weights, surfaced by honest held-out evaluation exactly as intended —
   not something to quietly patch by re-tuning against this one scenario
   (see the weight-tuning discipline below).

### Contrast: the same ablations on `data-schema-001` (dev, "loud" root cause)

| variant | top-1 | top-3 | MRR | rank |
|---|---|---|---|---|
| `causegraph_full` | ✅ | ✅ | 1.00 | 1 |
| `causegraph_no_change_events` | ❌ | ✅ | 0.50 | 2 |
| `causegraph_no_temporal_ordering` | ❌ | ✅ | 0.50 | 2 |
| `causegraph_no_propagation_consistency` | ✅ | ✅ | 1.00 | 1 |

Here T *helps* (opposite of `cache-ttl-001`) and P is neutral. **Neither
term is uniformly good or bad — their value is scenario-dependent**, which
is itself evidence that 3-5 scenarios aren't enough to responsibly tune
anything yet (see below).

### Calibration (spec section 9.3): is `causegraph`'s confidence trustworthy?

`run-calibration --method causegraph` (default settings: all 5 scenarios,
2 seeds each = 10 live runs). Confidence is a softmax over the returned
hypotheses' scores (`_softmax_top1_confidence` in
`benchmark/evaluator/evaluator.py`) — available for every method, not
only when agent synthesis runs.

```
method=causegraph  n_runs=10  n_scored_pairs=10
brier_score=0.1506  expected_calibration_error=0.0742

bin          n   avg_confidence  accuracy
[0.0, 0.2]   0   -               -
[0.2, 0.4]   0   -               -
[0.4, 0.6]   3   0.45            0.33
[0.6, 0.8]   3   0.66            0.67
[0.8, 1.0]   4   0.91            1.00
```

Reading this honestly: a Brier score of 0.15 and ECE of 0.07 are
reasonable — genuinely better than "cosmetic," which is the bar spec
section 23 sets. The `[0.6, 0.8]` bin is close to perfectly calibrated
(66% confidence, 67% actual accuracy). The `[0.8, 1.0]` bin is
*underconfident* (91% confidence, 100% accuracy) — the safer direction
to be wrong in. The `[0.4, 0.6]` bin is mildly overconfident (45% vs
33%). None of this should be over-read: **3-4 samples per bin is not
enough to trust the per-bin numbers**, only the aggregate Brier
score/ECE, and even those come from just 10 runs total. This is a
genuine first measurement, not a mature calibration claim — the
honest version of "measured, not cosmetic" is reporting the number
*and* saying plainly how little data it rests on.

### Caveat that applies to every table above

These are **one live run each**, not repeated trials — the system has
real timing jitter (a repeat run of `causegraph` on `data-schema-001` in
`docs/architecture.md`'s Phase 7 section got a different rank on a
different day). Treat every number above as a data point, not a verdict;
the *qualitative* findings (C(c) is load-bearing; X(c) has a documented
weakness; T/P are scenario-dependent) are the actual result. The numbers
would need averaging over several seeds per scenario to become a
quantitative claim, which is the next item below.

## Not yet applicable / not yet done

- **Weight tuning**: still not done, and still shouldn't be done yet.
  5 scenarios (3 dev, 2 held-out) is enough to *see* that the weights have
  a real weakness (above), but nowhere near enough to responsibly retune
  them — doing so now would mean tuning 7 weights against evidence from
  essentially 3 dev data points, which is overfitting dressed up as
  measurement. This needs materially more scenarios first.
- **Confidence intervals**: still not done. The comparison/ablation
  tables above are each a single run; only the calibration study used
  repeated runs (2 seeds), and even that is too few to report a
  confidence interval on the Brier score/ECE themselves, just the point
  estimate.
- **Path-accuracy scoring**: scenario manifests declare `expected_path`,
  but only root-cause rank (top-1/top-3/MRR) is scored today; whether a
  method's `causal_path` matches the expected propagation chain is not
  part of the metrics yet.

## Standing rule

Per spec section 18.3, this project does not claim accuracy numbers,
production-scale performance, causality (vs. correlation), or remediation
safety beyond what has actually been measured in a held-out evaluation.
Nothing in `experiments/results/` should be cited in the README, a blog
post, or a paper draft until the run that produced it is reproducible from
a fresh clone. The I(c) term in CauseGraph's scoring defaults to 0.0 (no
evidence) unless a real intervention tester ran — a missing intervention
result is never treated as evidence against a candidate. The documented
X(c) weakness above is reported, not hidden or quietly patched.
