# ADR 0001: Reference application service boundaries

## Status
Accepted (Sprint 1)

## Context
CauseGraph needs a real distributed ML application to create authentic dependency
chains and failure propagation, not a mocked telemetry dump. The spec (section 7)
lists nine conceptual services; Sprint 1 only needs enough of them to create one
real upstream-to-symptom causal chain with three fault scenarios: a data/schema
fault, an ML/latency fault, and a streaming/queue fault.

## Decision
Implement exactly five HTTP services in Sprint 1, matching the spec's First
Implementation Sprint (section 21, step 38):

- **event-api** — accepts synthetic interaction events, produces to Kafka.
- **feature-worker** — consumes events, computes features, writes to Redis
  (the feature-store). Owns the `incompatible_schema` fault.
- **model-service** — reads features, scores items, reports a model version.
  Owns the `latency` fault.
- **ranking-api** — calls model-service for a candidate set, returns ranked
  results. The client-facing entry point.
- **quality-monitor** — periodically calls ranking-api and emits a quality-proxy
  metric; this is where symptoms are first observed, mirroring "recommendation
  quality falls but the ranking service is healthy" in the spec's problem
  definition.

`feature-store` (Redis) and `event-stream` (a Kafka topic) are modeled as
dependency-graph nodes, not as separate deployable services — they are
infrastructure the five services depend on. `model-trainer` and
`model-registry` are deferred: Sprint 1 hardcodes a single model version
rather than running real training, since model training is not required to
produce a believable failure chain.

## Consequences
- The dependency graph (ADR 0003) has a fixed, small topology for Sprint 1:
  5 services + 1 topic + 1 cache + 1 feature + 1 model version.
- Every service is independently deployable and independently fails, which is
  required for believable fault injection and for the graph-only baseline to
  have something real to rank.
- Adding model-trainer/model-registry later only requires new graph nodes and
  edges, not a redesign of the graph or RCA interfaces.
