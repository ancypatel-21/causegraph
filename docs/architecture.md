# Architecture (through Phase 10)

## Reference application

```
User Events (seeded workload)
    |
    v
event-api --PRODUCES--> event-stream (Kafka topic "interaction-events")
                              |
                         CONSUMES
                              v
                        feature-worker --WRITES_TO--> feature-store (Redis)
                              |
                         GENERATES
                              v
                     engagement-feature
                              ^
                        USES_FEATURE
                              |
                        model-service --SERVES_MODEL--> ranking-model-v1
                              ^
                           CALLS
                              |
                        ranking-api
                              ^
                           CALLS
                              |
                       quality-monitor  (probes ranking-api every few seconds,
                                          computes the quality-proxy signal)
```

Fault ownership: `feature-worker` owns `incompatible_schema` (via
`POST /admin/fault/schema`) and `consumer_lag` (via `POST /admin/fault/lag`,
which pauses its own Kafka consumption); `model-service` owns `latency`
(via `POST /admin/fault/latency`). See `docs/adr/0001-service-boundaries.md`.

## Telemetry

Every service exposes `/metrics` (Prometheus format) and is instrumented
with OpenTelemetry (traces exported via OTLP to a collector). See
`docs/adr/0002-telemetry-stack.md`. Domain health signals (error rate, null
feature rate, consumer lag, latency, quality proxy) are published as the
single `causegraph_domain_signal{service=...,signal=...}` gauge so the
anomaly engine has one uniform query surface — see
`causegraph/rca/node_signals.py` for the mapping from graph node to its
Prometheus query.

## Dependency graph and RCA

The dependency graph is an in-memory repository (`causegraph/graph/`)
behind the `GraphRepository` interface (`docs/adr/0003-graph-repository-interface.md`),
populated once from the static Sprint-1 topology in
`causegraph/graph/topology.py`.

Edge direction follows the spec's examples literally (e.g. `CALLS:
service -> service` is caller -> callee), but *which side is upstream*
differs by edge semantics: for "dependent -> dependency" edges (CALLS,
READS_FROM, USES_FEATURE, SERVES_MODEL, CONSUMES, DEPENDS_ON) the edge's
target is upstream of its source. For "creator -> created" edges
(PRODUCES, WRITES_TO, GENERATES) it's the reverse: the source (the
creator) is upstream of the target. `causegraph/graph/repository.py`
encodes this once (`CREATOR_EDGE_TYPES`), so traversal code never has to
reason about it per edge.

`causegraph/rca/graph_only.py` implements the B3 baseline (spec section
9.1): traverse upstream from the incident's symptom node(s), score every
reachable candidate by `anomaly_severity / (1 + graph_distance)`, and emit
an auditable `Evidence` row per candidate with signal data, plus a ranked
`Hypothesis` list. This is deliberately naive — it has no temporal
ordering, change-event correlation, or causal/intervention evidence.

## Baselines (Phase 5)

All of B0-B4 now run through the same evaluator (spec section 9.1),
registered in `benchmark/baselines/registry.py`:

| Method | File | Approach |
|---|---|---|
| `random` (B0) | `random_baseline.py` | Shuffles every graph node; sanity floor. |
| `rules` (B1) | `rules_baseline.py` | Fixed signature table over raw signal thresholds, checked in priority order. Deliberately brittle. |
| `graph_only` (B3) | `causegraph/rca/graph_only.py` | Upstream traversal + anomaly severity / distance. |
| `llm_only` (B2) | `llm_only.py` | All telemetry-emitting nodes, no topology hint, ranked by an LLM provider. |
| `graph_llm` (B4) | `graph_llm.py` | Same candidate set as `graph_only`, but ranked by an LLM provider instead of the fixed formula. |
| `causegraph` (CG) | `causegraph/rca/causegraph_method.py` | The full scoring model below. |

B2/B4 go through a provider-neutral LLM adapter (`causegraph/llm/provider.py`).
The default provider is a deterministic, network-free heuristic — every
baseline runs with zero API keys configured, per spec section 14 step 18.
A real provider (currently Anthropic) is opt-in via
`CAUSEGRAPH_LLM_PROVIDER=anthropic` (needs the `llm` extra and an API key).

## CauseGraph scoring (Phase 6)

`causegraph/rca/causegraph_method.py` implements the full scoring model
from spec section 5.2:

```
score(c) = w1*A(c) + w2*D(c,s) + w3*T(c) + w4*C(c) + w5*P(c,s) + w6*I(c) - w7*X(c)
```

| Term | What it measures | How |
|---|---|---|
| A(c) | Anomaly severity at c | Robust z-score over the incident window, normalized |
| D(c,s) | Graph proximity to symptom | `1/(1+distance)` |
| T(c) | Temporal precedence | Candidate's anomaly severity in the *first half* of the incident window, compared to the symptom's own early severity — a real lead, not just "also anomalous" |
| C(c) | Recent-change correlation | Any `ChangeEvent` recorded for c shortly before the incident |
| P(c,s) | Propagation consistency | Mean normalized severity across every signaled node on c's path to the symptom, not just the endpoints |
| I(c) | Intervention/counterfactual evidence | Pluggable `intervention_scorer`; defaults to 0.0 (no evidence) unless a real one is wired in (Phase 7, below) |
| X(c) | Contradicting evidence | 1.0 only when c *has real telemetry* showing it's quiet — absence of data is never treated as evidence of health |

Weights are fixed, documented defaults (spec section 5.2: "Start
interpretable... weights are tuned on a development subset only"), not
tuned — see `docs/research-protocol.md` for why a real tuning pass isn't
possible yet with only 3 scenarios.

**Ablations are free**: `enabled_terms=ALL_TERMS - {"C"}` reproduces
"CauseGraph without change-event evidence" (spec section 9.2) exactly,
with no separate code path.

### A real (if small) comparison result

Run live against the Compose stack, scenario `data-schema-001` (root
cause: `feature-worker`), one replay per method:

| method | top-1 | top-3 | MRR | rank | top-5 ranking |
|---|---|---|---|---|---|
| `causegraph` | ✅ | ✅ | 1.00 | 1 | feature-worker, quality-monitor, engagement-feature, ... |
| `graph_only` | ✅ | ✅ | 1.00 | 1 | feature-worker, quality-monitor, ranking-api, ... |
| `rules` | ✅ | ✅ | 1.00 | 1 | feature-worker, event-api, model-service, ... |
| `llm_only` | ❌ | ✅ | 0.50 | 2 | ranking-api, feature-worker, quality-monitor, ... |
| `graph_llm` | ❌ | ✅ | 0.33 | 3 | ranking-api, model-service, feature-worker, ... |
| `random` | ❌ | ❌ | 0.00 | — | ranking-api, engagement-feature, ranking-model, ... |

This is **one run on one scenario** — illustrative, not a claim. `random`
correctly lands at the bottom; `rules` happens to match this exact
scenario's hand-tuned threshold (it's expected to fail on anything novel);
the LLM baselines underperform here specifically because the default mock
provider is a simple heuristic, not a real language model. None of this
is a substitute for the held-out evaluation in Phase 9 — see
`docs/research-protocol.md`.

**Proof this isn't cherry-picked**: a second live run of `causegraph` on
the identical scenario got `top1_accuracy=false` (`quality-monitor`
ranked first, `feature-worker` second — still `top3_accuracy=true`,
`mrr=0.5`) and the intervention probe that run measured 0.0 recovery
instead of 0.54. Same code, same scenario, different outcome — exactly
why spec section 9.4 requires confidence intervals over repeated runs,
not single point estimates, and why no accuracy number in this repo
should be read as a stable measurement yet.

## Causal/intervention validation (Phase 7)

`causegraph/causal/intervention.py` scores a before/after measurement
(domain-agnostic, no knowledge of injectors). The orchestration that
actually disables a fault, waits, re-measures, and restores it lives in
`benchmark/evaluator/intervention_runner.py` — a benchmark/dev-mode-only
privilege, per spec section 6.1, never exposed over the causegraph-api
HTTP surface or any agent tool.

It's opt-in (`ALLOW_INTERVENTION_TESTS=1`) and only applies to the
`causegraph` method, since it mutates live fault state mid-run. When
enabled, the evaluator runs it once, for the one node that has a known
lever for the incident's active fault (`FAULT_OWNER_NODE`, keyed by fault
*type*, the same thing the evaluator already needed to call the injector
at all — not the scenario's ground-truth answer), and feeds the result
into `CauseGraphMethod.intervention_scorer`.

Verified live (`data-schema-001`, `causegraph` method,
`ALLOW_INTERVENTION_TESTS=1`): the evaluator disabled the schema fault,
measured `model-service`'s latency drop from 2.33ms to 1.08ms, scored the
recovery at 0.54 (above the 0.5 "recovered" threshold), restored the
fault, and still correctly ranked `feature-worker` #1 — with the
intervention evidence (`reliability=0.95`, the highest of any evidence
type) queryable via `GET /incidents/{id}/evidence`.

## Investigator agent (Phase 8)

`causegraph/agent/` implements spec section 6: "an evidence orchestrator,
not an omnipotent operator." It never re-ranks from scratch — it takes
whichever RCA method's already-ranked `Hypothesis`/`Evidence` list won
(the source of truth), may call a couple of bounded tools
(`causegraph/agent/tools.py`) to fill gaps, and writes the required
structured conclusion (spec section 6.2) as an `AgentReport`.

- All seven tools from spec section 6.1 exist, each hard-capped (depth,
  time window, row limit) regardless of what's requested.
  `get_trace_summary` and `get_logs` are **honest stubs** — Sprint 1 has
  no queryable trace or log backend (see Telemetry, above), so they
  report `available: false` rather than fabricating data.
  `request_intervention_test` is benchmark/dev-mode only; absent an
  injected callable from the benchmark harness, it also reports itself
  unavailable rather than silently no-op'ing.
- Uses the same provider-neutral LLM adapter as B2/B4 — mock by default,
  no API key required.
- `needs_human_approval` is always `true`. There is no remediation
  executor yet (Phase 10), so the agent never implies an action can run
  without one.
- Opt-in via `ENABLE_AGENT_SYNTHESIS=1`; purely additive — it never
  changes the ranked `Hypothesis` list or the accuracy metrics, only adds
  an `AgentReport` alongside them in `BenchmarkRun.metrics`.

**A real finding, not a bug**: because the agent's secondary ranking goes
through the (crude, heuristic) mock LLM provider — which just takes
`max(raw_signals.values())` per candidate, not a properly normalized
comparison across different metric types — it can disagree with
`CauseGraphMethod`'s own numeric ranking. In the `top1_accuracy=false` run
above, `CauseGraphMethod` ranked `quality-monitor` first and the agent
agreed; in other runs the agent's choice diverges from the primary
ranking even when the primary ranking is correct. This is exactly the
behavior spec section 4.3 warns about — "LLM prose is not the source of
truth" — demonstrated, not just stated: the benchmark's accuracy metrics
are computed from `CauseGraphMethod`'s score alone, never from the
agent's pick.

## Held-out evaluation and ablations (Phase 9)

Grew from 3 to 5 scenarios with two genuinely new fault mechanisms (not
superficial variants): `cache-ttl-001` (a deliberately **quiet root
cause** — feature-worker keeps writing valid data, only the TTL
regresses, so its own anomaly signal never fires) and
`redis-unavailable-001` (gives `feature-store` its first-ever
ground-truth role). `Scenario.split` (`dev`/`held_out`) tags all five;
the two new ones were labeled `held_out` and never looked at before
being run. `benchmark/evaluator/evaluator.py:run_ablations` runs the four
term-ablations spec section 9.2 names, plus the full model, through the
same evaluator as everything else.

Real results, including a case where CauseGraph wins and a case where
nothing gets top-1, are in `docs/research-protocol.md` — including an
honest limitation the ablations surfaced (the X contradicting-evidence
term actively fights the change-event term on quiet-root-cause
scenarios), not just the wins.

## Policy-gated remediation (Phase 10)

`causegraph/remediation/` implements spec sections 10-11: "The LLM
proposes a typed action; a deterministic policy engine decides whether
it is allowed and whether human approval is required." The full
lifecycle (`POST /remediation/proposals` → `.../approve` →
`.../execute`, plus `.../rollback`) is wired into `causegraph-api` and
verified live against the real stack, not just unit-tested.

- **`policy.py`**'s `ALLOWED_ACTIONS` is a fixed allow-list of
  `(action_type, target)` pairs, each with a risk tier (spec section
  11's three tiers) and hard-coded fix/undo payloads — never built from
  free-form text. Every `action_type` is one of the scenario `cleanup`
  values already defined in `benchmark/scenarios/*.yaml`: remediation is
  literally "undo the fault," the same mechanism the benchmark harness
  uses for cleanup, now gated by policy instead of running
  unconditionally.
- **HIGH-risk actions are denied in code, not just in docs.** A
  `drop_database` entry exists in the allow-list specifically so there's
  something concrete for the policy engine to reject — verified live:
  proposing it returns `status: rejected`, `reason: "high-risk actions
  are disallowed in this project"`.
- **MEDIUM-risk actions require approval**, enforced at execution time
  (`RemediationExecutor.execute` raises `RemediationError` if a
  medium-risk proposal isn't `APPROVED` yet) — verified live: executing
  before approval returns HTTP 409.
- **LOW-risk actions may execute without approval** (`resume_consumer`
  on `event-stream`), per spec section 11's tier table.
- **Idempotency key** = a hash of `(incident_id, action_type, target)`.
  Calling `propose` twice returns the same proposal; calling `execute`
  twice only calls the real endpoint once — verified live via
  `feature-worker`'s logs showing exactly one `schema fault set to
  False` after two `execute` calls.
- **Every executable action has a working rollback.** Verified live:
  after executing `restore_schema` (which calls
  `POST /admin/fault/schema {enabled: false}`), rolling back calls
  `{enabled: true}` and `feature-worker`'s logs confirm the fault came
  back.
- **`causegraph/remediation/executor.py` is the only module in the
  project that calls a service's admin endpoint from production code**
  (`causegraph-api`), as distinct from the benchmark harness's fault
  injectors (`benchmark/injectors/`) — mechanically similar calls, but
  one creates ground-truth incidents for the benchmark and the other
  executes a policy-approved fix against a real diagnosed incident.
- The investigator agent's `recommended_action` now names a real,
  allow-listed `action_type` (via `incident.trigger_signal` →
  `FAULT_TO_ACTION_TYPE`) instead of a generic placeholder — but
  recommending is all it does; `needs_human_approval` is still always
  `true`, and whether the action is actually allowed is decided by
  `PolicyEngine.evaluate` at execution time, never by the agent.

## What's not built yet (by design)

| Deferred to | What |
|---|---|
| Phase 9 (further) | Weight tuning (needs more scenarios first — see research-protocol.md), confidence intervals over repeated runs, path-accuracy scoring |
| Phase 9+ | Dashboard / UI |

See spec section 13 for the full roadmap and section 13.1 for the MVP cut
line (Phase 9).
