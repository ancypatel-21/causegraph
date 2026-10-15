# Research protocol

This file tracks the experimental discipline requirements from spec
section 9.4 and the reproducibility requirements from section 17, and what
is (and is not yet) satisfied as of Phase 6.

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

## Not yet applicable

- **Dev/held-out split**: there are 3 scenarios. A meaningful split needs
  enough scenarios that a held-out subset isn't trivially easy or
  trivially hard — realistically this needs the scenario count to grow
  substantially first (Phase 9, and growing past 3 scenarios generally).
- **Weight tuning discipline** ("Weights are tuned on a training/
  development subset... final evaluation must use held-out scenarios" —
  spec section 5.2): the full CauseGraph scoring model (Phase 6) now has
  7 tunable weights (`causegraph/rca/causegraph_method.py:DEFAULT_WEIGHTS`),
  but they are fixed, documented *starting* values, explicitly not tuned.
  Tuning them against only 3 scenarios would be overfitting to the
  benchmark, not a measurement — this is deferred until there are enough
  scenarios for a real dev/held-out split (Phase 9).
- **Confidence intervals / repeated runs with multiple seeds**: deferred
  until there's more than a single run per scenario to aggregate (Phase 9).
  The "comparison result" in `docs/architecture.md` is explicitly labeled
  as one run on one scenario, not a statistically supported claim.
- **Path-accuracy scoring**: scenario manifests declare `expected_path`,
  but only root-cause rank (top-1/top-3/MRR) is scored today; whether a
  method's `causal_path` matches the expected propagation chain is not yet
  part of the metrics (Phase 9 addition).

## Standing rule

Per spec section 18.3, this project does not claim accuracy numbers,
production-scale performance, causality (vs. correlation), or remediation
safety beyond what has actually been measured in a held-out evaluation.
Nothing in `experiments/results/` should be cited in the README, a blog
post, or a paper draft until the run that produced it is reproducible from
a fresh clone. The I(c) term in CauseGraph's scoring defaults to 0.0 (no
evidence) until Phase 7 wires in a real intervention tester — a missing
intervention result is never treated as evidence against a candidate.
