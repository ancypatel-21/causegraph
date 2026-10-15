# ADR 0002: Telemetry stack

## Status
Accepted (Sprint 1)

## Context
The RCA engine's anomaly and evidence layers need metrics, traces, structured
logs, and change events that are correlated by node id and time, per the
spec's evidence model (section 4) and testing strategy (section 16).

## Decision
- **Metrics**: each service exposes a `/metrics` endpoint via
  `prometheus-client`. Prometheus scrapes services directly. This avoids
  round-tripping metrics through the OTel Collector for Sprint 1 and keeps
  the anomaly engine's data source to one well-known query API
  (`PROMETHEUS_URL`, PromQL `query_range`).
- **Traces**: each service uses the OpenTelemetry SDK with OTLP/HTTP export
  to a single-node `otel-collector`, auto-instrumenting FastAPI and outbound
  `httpx` calls so trace context propagates across the real
  ranking-api -> model-service and quality-monitor -> ranking-api calls. The
  collector's pipeline exports traces to its console/debug exporter for
  Sprint 1 — a tracing backend (e.g., Jaeger/Tempo) is an easy later swap
  behind the same collector config, not a code change.
- **Logs**: structured JSON logs to stdout, with `trace_id`/`span_id` pulled
  from the active OTel context on every log record, so a log line can always
  be joined to a trace and, from there, to an incident.
- **Change events**: recorded explicitly (not inferred from logs) via
  `POST /changes` against the causegraph-api, backed by a Postgres table.
  Fault injectors call this endpoint when they toggle a fault, which is the
  Sprint-1 stand-in for real deploy/config/schema change events.

## Consequences
- Anomaly detection has exactly one query surface (Prometheus), which keeps
  `causegraph/anomalies` simple and swappable later.
- Full trace visualization (Jaeger/Grafana Tempo UI) is deferred; the
  Sprint-1 bar is "trace IDs correlate logs, metrics windows, and incidents,"
  not "pretty trace UI" — that belongs with the dashboard (Phase 9+).
