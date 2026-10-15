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

## Scenarios

| id | fault | root cause | owner service |
|---|---|---|---|
| `data-schema-001` | `incompatible_schema` | `feature-worker` | feature-worker |
| `ml-latency-001` | `latency` | `model-service` | model-service |
| `stream-lag-001` | `consumer_lag` | `event-stream` | feature-worker (pauses its own consumer) |

Each manifest (`benchmark/scenarios/*.yaml`) declares `expected_path` — the
causal chain from root cause to symptom — used for qualitative comparison,
not currently scored directly (path-accuracy scoring is a Phase 9
evaluation addition).

## Adding a scenario

Add a new YAML file matching the `Scenario` schema
(`causegraph/schemas/models.py`), register a `FaultInjector` for its
`fault` name in `benchmark/injectors/registry.py` if one doesn't already
exist, and make sure the owning service exposes the matching
`/admin/fault/...` endpoint. Never edit an existing scenario's semantics
in place — bump its `id` instead, per
`docs/adr/0004-benchmark-artifact-format.md`.

## Growing past Sprint 1

Sprint 1 ships exactly three scenarios (spec section 21, step 43). The
full benchmark (spec section 8) calls for starting at 20 high-quality
scenarios and growing toward 50-100 once the harness is stable — that's
Phase 4 work, not Sprint 1.
