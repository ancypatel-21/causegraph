# CauseGraph

Graph-guided causal root-cause analysis for distributed ML systems. See
`CauseGraph_Project_Specification.pdf` for the full research spec; this
README covers what's implemented so far.

## Status: through Phase 8

Backend-only so far, per the spec's own Codex kickoff prompt (Phase 9+ adds
a dashboard). Built: a real distributed reference application,
OpenTelemetry/Prometheus telemetry, an in-memory dependency graph, three
reproducible fault scenarios, all five required baselines (B0/B1/B2/B3/B4),
the full CauseGraph scoring model (CG), live intervention/counterfactual
validation, and a bounded investigator agent with a provider-neutral LLM
adapter (mock by default, no API key needed) — all wired through one
automated benchmark evaluator. Not yet built: held-out evaluation +
ablations actually run (Phase 9), remediation (Phase 10), and the
dashboard. See `docs/architecture.md` for the full breakdown.

## Quick start

```bash
cp .env.example .env            # defaults already match the compose network
make up                         # builds and starts the full stack
make bootstrap-db                # creates Postgres tables
make scenario SCENARIO=data-schema-001
```

`make scenario` runs the full loop: starts a seeded synthetic workload,
injects the named fault partway through, lets the symptom manifest, runs
the `graph_only` baseline by default, scores it against the scenario's
ground truth, and writes a reproducible result to `experiments/results/`.

Available scenarios: `data-schema-001`, `ml-latency-001`, `stream-lag-001`
(see `benchmark/scenarios/`). Available RCA methods: `random`, `rules`,
`graph_only`, `llm_only`, `graph_llm`, `causegraph` (see
`docs/architecture.md`). Compare all of them on one scenario:

```bash
docker compose -f infra/compose/docker-compose.yml run --rm benchmark-cli \
  compare-methods data-schema-001
```

```bash
make logs     # tail every service
make down     # tear the stack down
make test     # unit tests (no live stack required)
```

With the stack up, the full integration/e2e suite (which hits real
services) can also run:

```bash
RUN_LIVE_STACK_TESTS=1 pytest tests/integration tests/e2e
```

## What's here

- **services/** — event-api, feature-worker, model-service, ranking-api,
  quality-monitor: a real, small recommendation/ranking pipeline with two
  owned fault toggles (`incompatible_schema` on feature-worker, `latency`
  and `consumer_lag` on feature-worker/model-service).
- **causegraph/** — the reusable core: schemas, the dependency-graph
  repository, OpenTelemetry/Prometheus telemetry helpers, the robust
  z-score anomaly detector, the graph-only baseline and the full
  CauseGraph scoring model, intervention-evidence math (`causal/`), the
  bounded investigator agent (`agent/`), the provider-neutral LLM adapter
  (`llm/`), and the central `causegraph-api` service.
- **benchmark/** — scenario manifests, fault injectors, the seeded workload
  generator, all six RCA methods (`baselines/`), the live intervention-test
  orchestrator (`evaluator/intervention_runner.py`), and the evaluator
  that ties it all together into a scored, saved `BenchmarkRun`.
- **docs/adr/** — the four ADRs written before this sprint's code, per the
  spec's own process requirement.

## Repository map

See `docs/architecture.md` for the full breakdown, a sample live
baseline-comparison result, and the roadmap for everything not yet built.
