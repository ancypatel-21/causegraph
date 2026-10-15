# Benchmark

## Running a scenario

```bash
make up
make bootstrap-db
make scenario SCENARIO=data-schema-001
```

Or directly via the CLI (spec section 21, step 44):

```bash
docker compose -f infra/compose/docker-compose.yml run --rm benchmark-cli \
  run-scenario data-schema-001
```

## What happens during a run

`benchmark/evaluator/evaluator.py` orchestrates, against the real running
services:

1. Start the seeded workload generator (`benchmark/workloads/generator.py`)
   posting synthetic events to `event-api`.
2. Wait `scenario.inject_at_seconds`, then enable the scenario's fault
   injector (`benchmark/injectors/`) against the service that owns it.
3. Wait a short settle window for the symptom to show up in Prometheus.
4. Create an `Incident` with the scenario's declared `symptom_nodes`.
5. Run the requested RCA method (any of `random`, `rules`, `graph_only`,
   `llm_only`, `graph_llm`, `causegraph` — see `docs/architecture.md`) and
   persist its `Hypothesis`/`Evidence` output.
6. Disable the fault (cleanup) and stop the workload.
7. Score the ranked hypotheses against `scenario.root_cause`: top-1/top-3
   accuracy, MRR, rank of ground truth, time-to-diagnosis.
8. Persist a `BenchmarkRun` to Postgres **and** as a standalone JSON file
   under `experiments/results/`, per
   `docs/adr/0004-benchmark-artifact-format.md`.

## Agent synthesis

```bash
docker compose -f infra/compose/docker-compose.yml run --rm -e ENABLE_AGENT_SYNTHESIS=1 \
  benchmark-cli run-scenario data-schema-001 --method causegraph
```

Opt-in, purely additive (spec section 6/8 — see `docs/architecture.md`).
Adds an `AgentReport` to `BenchmarkRun.metrics["agent_report"]`; never
changes the ranked `Hypothesis` list or the accuracy metrics.

## Causal validation (CauseGraph only)

```bash
docker compose -f infra/compose/docker-compose.yml run --rm -e ALLOW_INTERVENTION_TESTS=1 \
  benchmark-cli run-scenario data-schema-001 --method causegraph
```

Opt-in and `causegraph`-only (spec section 5.3 / section 6.1 — see
`docs/architecture.md`). Off by default because it mutates live fault
state mid-run and adds wall-clock time; a plain `run-scenario` call never
does this unless the flag is set.

## Comparing every method on one scenario

```bash
docker compose -f infra/compose/docker-compose.yml run --rm benchmark-cli \
  compare-methods data-schema-001
```

Runs every registered method against the same scenario (one independent
fault-injection replay per method, so each gets its own real telemetry)
and prints a comparison table. Use `--methods graph_only,causegraph` to
run a subset. See `docs/architecture.md` for a sample result.

## Ablation studies (spec section 9.2)

```bash
docker compose -f infra/compose/docker-compose.yml run --rm benchmark-cli \
  run-ablations cache-ttl-001
```

Runs `causegraph_full` plus the four term-ablations spec section 9.2 asks
for by name (`causegraph_no_change_events`, `_no_temporal_ordering`,
`_no_propagation_consistency`, `_no_intervention_evidence`) against the
same scenario — each is just `CauseGraphMethod` constructed with a
different `enabled_terms` set (`causegraph/rca/causegraph_method.py`), no
separate code path. "Without LLM synthesis" is just
`ENABLE_AGENT_SYNTHESIS=0` vs `=1` on a plain run; "vary traversal depth
and candidate budget" is the existing `depth`/`top_k` parameters — neither
needed a new mechanism. See `docs/research-protocol.md` for real results
and what they show.

## Calibration study (spec section 9.3)

```bash
docker compose -f infra/compose/docker-compose.yml run --rm benchmark-cli \
  run-calibration --method causegraph --n-runs-per-scenario 3
```

Runs every scenario `n-runs-per-scenario` times, each with a different
seed (`scenario.seed + 0, +1, +2, ...` — `run_scenario`'s `seed`
parameter overrides the manifest's canonical seed for exactly this),
pools every run's (confidence, correctness) pair across all scenarios
and seeds, and reports Brier score + Expected Calibration Error
(`causegraph/calibration.py`). Confidence is a softmax over the returned
hypotheses' scores, so it's available for every method, not just when
agent synthesis runs. See `docs/research-protocol.md` for a real result
and how much (or little) data it rests on.

## Scenarios

| id | fault | root cause | owner service | split |
|---|---|---|---|---|
| `data-schema-001` | `incompatible_schema` | `feature-worker` | feature-worker | dev |
| `ml-latency-001` | `latency` | `model-service` | model-service | dev |
| `stream-lag-001` | `consumer_lag` | `event-stream` | feature-worker (pauses its own consumer) | dev |
| `cache-ttl-001` | `cache_ttl_regression` | `feature-worker` | feature-worker | held_out |
| `redis-unavailable-001` | `redis_unavailable` | `feature-store` | model-service (the reader that fails) | held_out |

`cache-ttl-001` is deliberately a **quiet root cause**: the TTL change
means feature-worker keeps writing valid data, so its own anomaly signal
never fires — the only evidence pointing at it is the recorded change
event. `redis-unavailable-001` gives `feature-store` its first-ever
ground-truth role, exercising a node that previously only ever appeared
as an intermediate hop. Both were genuinely held out: not looked at until
the Phase 9 evaluation run documented in `docs/research-protocol.md`.

Each manifest (`benchmark/scenarios/*.yaml`) declares `expected_path` — the
causal chain from root cause to symptom — used for qualitative comparison,
not currently scored directly (path-accuracy scoring is a possible future
evaluation addition).

## Adding a scenario

Add a new YAML file matching the `Scenario` schema
(`causegraph/schemas/models.py`), register a `FaultInjector` for its
`fault` name in `benchmark/injectors/registry.py` if one doesn't already
exist, and make sure the owning service exposes the matching
`/admin/fault/...` endpoint. Never edit an existing scenario's semantics
in place — bump its `id` instead, per
`docs/adr/0004-benchmark-artifact-format.md`.

## Growing past 5 scenarios

Sprint 1 shipped exactly three scenarios (spec section 21, step 43); Phase
9 added two more with genuinely new fault mechanisms (not superficial
variants of the first three) and a `split` field. The full benchmark
(spec section 8) calls for starting at 20 high-quality scenarios and
growing toward 50-100 once the harness is stable — 5 is an honest, modest
step in that direction, not a claim of having reached it. Growing further
means adding real new fault mechanisms (infra/network/cascading
categories from spec section 8 are still unrepresented), not duplicating
existing ones with different numbers.
