# CauseGraph

**Graph-guided causal root-cause analysis for distributed ML systems.**

CauseGraph diagnoses *why* a distributed ML pipeline broke, not just *that*
it broke — by combining a typed dependency graph, anomaly detection,
change-event correlation, and **live causal intervention tests**, and
scoring the result against four baselines on a benchmark it is honest
about the limits of.

[![CI](https://github.com/ancypatel-21/causegraph/actions/workflows/ci.yml/badge.svg)](https://github.com/ancypatel-21/causegraph/actions/workflows/ci.yml)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![Status](https://img.shields.io/badge/status-MVP%20complete%20%E2%80%94%20Phase%200%E2%80%9310-brightgreen)

---

## The problem

Modern ML products are dependency chains: events feed feature pipelines,
features feed models, models feed ranking services. A visible symptom
can surface far downstream from where it actually started:

> Recommendation quality falls, but the ranking service reports healthy.
> The actual cause is an upstream schema change that quietly increased
> nulls in a feature three hops away.

Pointing an LLM at a raw telemetry dump and asking it to guess is
expensive, hallucination-prone, and topology-blind. CauseGraph instead
narrows the search using the system's real dependency structure, scores
competing hypotheses against auditable evidence, and only brings in an
LLM — bounded, and last — to explain a conclusion the numbers already
support.

## What makes this different from a typical RCA demo

- **A real distributed system, not a mocked JSON fixture.** Five live
  services (Kafka → feature pipeline → model → ranking API → quality
  monitor), each independently instrumented with OpenTelemetry and
  Prometheus, running in Docker Compose.
- **Five genuinely different, reproducible fault mechanisms** — not one
  fault re-labeled five times — including a deliberately *quiet* root
  cause (valid data, wrong TTL) designed to break naive anomaly-only
  detection.
- **Causal evidence is causal, not correlational.** The benchmark
  harness can actually disable a suspected fault mid-incident, measure
  whether the symptom recovers, and restore it — a real controlled
  experiment, not a simulated one.
- **Evidence is the source of truth, not LLM prose.** Every ranked
  hypothesis traces back to stored, typed `Evidence` rows. The
  investigator agent explains a diagnosis; it never gets to invent one.
- **Held-out evaluation and ablations that were actually run**,
  including a negative result reported in full (see [Results](#results-measured-not-claimed)) —
  not just scaffolding for evaluation that never happened.
- **Nothing executes without a policy check.** Remediation actions go
  through a fixed allow-list and risk-tiered approval gate; high-risk
  actions are rejected in code, not just in documentation.

## Architecture

```
User Events (seeded workload)
    │
    ▼
event-api ──produces──▶ event-stream (Kafka)
                              │
                          consumes
                              ▼
                        feature-worker ──writes──▶ feature-store (Redis)
                              │
                          generates
                              ▼
                     engagement-feature
                              ▲
                        uses-feature
                              │
                        model-service ──serves──▶ ranking-model-v1
                              ▲
                            calls
                              │
                        ranking-api
                              ▲
                            calls
                              │
                       quality-monitor   (probes ranking-api continuously,
                                           this is where symptoms surface)
```

Five independently-owned, independently-injectable faults sit on this
graph: a schema break and a cache-TTL regression on `feature-worker`, a
consumer-lag pause on the Kafka consumer, and a latency spike / simulated
connection exhaustion on `model-service`. Full breakdown, edge semantics,
and every scoring term in [`docs/architecture.md`](docs/architecture.md).

## Results (measured, not claimed)

Every number below came from a live run against the real Docker Compose
stack — reproduce any of it with the commands in [Quick start](#quick-start).
Per this project's own standing rule, nothing here is cited as a stable
measurement; see [`docs/research-protocol.md`](docs/research-protocol.md)
for the full, unedited findings, including where things didn't work.

**Baseline comparison** — `data-schema-001`, one independent replay per
method:

| method | top-1 | top-3 | MRR | rank |
|---|---|---|---|---|
| `causegraph` (full scoring model) | ✅ | ✅ | 1.00 | 1 |
| `graph_only` (topology + anomaly) | ✅ | ✅ | 1.00 | 1 |
| `rules` (hand-authored thresholds) | ✅ | ✅ | 1.00 | 1 |
| `llm_only` (raw telemetry → LLM) | ❌ | ✅ | 0.50 | 2 |
| `graph_llm` (graph-narrowed → LLM) | ❌ | ✅ | 0.33 | 3 |
| `random` (sanity floor) | ❌ | ❌ | 0.00 | — |

**An ablation that actually shows the mechanism works**, on
`cache-ttl-001` — a held-out scenario engineered so the real root cause
emits *no anomaly of its own*:

| `causegraph` variant | top-1 | rank |
|---|---|---|
| full model | ❌ | 2 |
| **without change-event evidence** | ❌ | **not in top 5** |
| without temporal ordering | ✅ | 1 |
| without propagation consistency | ✅ | 1 |

Removing change-event correlation doesn't just hurt the score — it drops
the true root cause out of the results entirely. That's the one piece of
evidence this scenario actually has, and the ablation proves it's
load-bearing, not decorative. (It also surfaced a real weakness in the
contradicting-evidence term, reported honestly rather than patched away
— see the docs.)

**Calibration** (Brier score / Expected Calibration Error, spec-required
metric, 10 live runs across 5 scenarios × 2 seeds):

```
brier_score = 0.1506        expected_calibration_error = 0.0742
```

A legitimate first measurement — and explicitly reported alongside how
little data (n=10) it rests on.

## Quick start

```bash
git clone https://github.com/ancypatel-21/causegraph.git
cd causegraph
cp .env.example .env
make up              # builds and starts the full stack
make bootstrap-db     # creates Postgres tables
make scenario SCENARIO=data-schema-001
```

Compare every RCA method, run the ablation study, or measure calibration:

```bash
docker compose -f infra/compose/docker-compose.yml run --rm benchmark-cli \
  compare-methods data-schema-001

docker compose -f infra/compose/docker-compose.yml run --rm benchmark-cli \
  run-ablations cache-ttl-001

docker compose -f infra/compose/docker-compose.yml run --rm benchmark-cli \
  run-calibration --method causegraph
```

Propose, approve, and execute a policy-gated remediation against a real
diagnosed incident:

```bash
curl -X POST localhost:18000/remediation/proposals -H 'Content-Type: application/json' \
  -d '{"incident_id":"<id>","action_type":"restore_schema","target":"feature-worker"}'
curl -X POST localhost:18000/remediation/proposals/<id>/approve -d '{"approved_by":"you"}'
curl -X POST localhost:18000/remediation/proposals/<id>/execute
```

```bash
make test     # 75 unit tests, no live stack required
make logs     # tail every service
make down     # tear the stack down
```

With the stack up, the integration/e2e suite can also run against real
services: `RUN_LIVE_STACK_TESTS=1 pytest tests/integration tests/e2e`.

## What's built

| | |
|---|---|
| **Reference application** | 5 services, Kafka, Postgres, Redis, OpenTelemetry + Prometheus throughout |
| **Dependency graph** | Typed nodes/edges behind a storage-agnostic repository interface |
| **Fault benchmark** | 5 reproducible scenarios (3 dev, 2 held-out), each a genuinely distinct mechanism |
| **Baselines** | All 5 required (random, rules, graph-only, LLM-only, graph+LLM), one shared evaluator |
| **CauseGraph scoring** | 7-term interpretable model — anomaly, proximity, temporal lead, change correlation, propagation consistency, intervention evidence, contradicting evidence |
| **Causal validation** | Real live intervention tests (disable → measure → restore), not simulated |
| **Investigator agent** | 7 bounded, hard-capped evidence tools; provider-neutral LLM adapter (works with zero API keys) |
| **Held-out evaluation** | Dev/held-out split honored before results were ever looked at; 4 ablations actually run |
| **Calibration** | Real Brier score / ECE from repeated multi-seed runs |
| **Remediation** | Policy-gated propose → approve → execute → rollback, allow-listed actions only |

This clears the spec's own MVP line (Phases 0–9) plus remediation
(Phase 10). What's intentionally not here yet: scaling past 5 scenarios
toward the spec's target of 20+, responsible weight tuning (needs more
scenarios first — tuning 7 weights against 3 dev data points is
overfitting, not measurement), and publication artifacts (demo video,
write-up). No dashboard/UI — this is a backend-first build, per the
project's own kickoff plan.

## Repository layout

```
causegraph/        core library — graph, telemetry, anomaly detection, RCA
                    scoring, causal validation, LLM adapter, agent,
                    remediation engine, and the central causegraph-api
services/           event-api · feature-worker · model-service ·
                    ranking-api · quality-monitor
benchmark/          scenario manifests, fault injectors, workload
                    generator, baselines, and the evaluator
infra/              Docker Compose, Prometheus, OpenTelemetry Collector
tests/              unit (no infra needed) · integration · e2e
docs/               architecture, benchmark guide, research protocol,
                    and the ADRs written before any of this was built
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — full system design,
  every scoring term explained, phase-by-phase build notes
- [`docs/benchmark.md`](docs/benchmark.md) — how to run scenarios,
  comparisons, ablations, and calibration studies
- [`docs/research-protocol.md`](docs/research-protocol.md) — every
  measured result, unedited, including what didn't work
- [`docs/adr/`](docs/adr) — the 4 architecture decision records written
  before writing any code

## Design principles

- **Never fabricate evidence.** Tools without a real backend (trace
  search, log aggregation) report themselves unavailable instead of
  returning invented data.
- **The ranking is numeric, not narrative.** The LLM-based agent explains
  an already-decided diagnosis; it cannot out-vote the scoring model.
- **No action without an allow-list.** Every executable remediation is a
  fixed `(action_type, target)` pair with hard-coded payloads — never
  built from free-form text, and high-risk actions are rejected in code.
- **Report negative results.** Ablations and held-out runs are published
  as they came out, including the cases where the system got it wrong.
