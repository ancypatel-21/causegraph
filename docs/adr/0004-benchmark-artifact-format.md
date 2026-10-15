# ADR 0004: Benchmark artifact format

## Status
Accepted (Sprint 1)

## Context
Per the spec's reproducibility requirements (section 17) and definition of
done (14.1), "a benchmark result without its config, seed, code version, and
scenario version is invalid." Results must be regenerable and comparable
across baselines added later.

## Decision
- **Scenario manifests** are YAML files under `benchmark/scenarios/*.yaml`,
  matching the schema in spec section 8.1 (`id`, `seed`, `root_cause`,
  `fault`, `inject_at_seconds`, `symptom_nodes`, `expected_path`, `cleanup`,
  `severity`, `labels`). Scenario files are versioned in git; changing the
  semantics of an existing scenario requires bumping its `id` or adding a
  `scenario_version` field, never silently editing ground truth in place.
- **Benchmark runs** are persisted twice, in the same shape:
  1. As a row in Postgres (`benchmark_runs` table, matching the
     `BenchmarkRun` schema in spec section 15), queryable via
     `GET /benchmark/runs/{id}`.
  2. As a standalone JSON file at
     `experiments/results/<scenario_id>__<run_id>.json`, containing the full
     `BenchmarkRun` payload plus the resolved scenario manifest — so results
     survive even without the database and `git diff` shows exactly what
     changed between runs.
- Every run record carries `git_sha`, `scenario_version` (the scenario file's
  `id` plus its git blob hash), `seed`, `workload_config`, `method`,
  `method_config`, timestamps, and `metrics{}`. Nothing is written without
  these fields populated.
- Result files are append-only: evaluator refuses to overwrite an existing
  result file for the same run id (definition of done: "no generated
  experiment results are silently overwritten").

## Consequences
- Any table or figure in `experiments/notebooks` can be regenerated solely
  from `experiments/results/*.json` plus the `benchmark/scenarios/*.yaml`
  used to produce it.
- Comparing baselines later (B0-B4 vs CG) is a matter of filtering
  `benchmark_runs` by `method`, not re-deriving anything.
