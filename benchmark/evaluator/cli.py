"""CLI entry point (spec section 21, step 44): run a scenario end-to-end and
export a machine-readable benchmark result.

    causegraph-cli run-scenario data-schema-001
"""

from __future__ import annotations

import json

import typer

from causegraph.db import init_db

from benchmark.scenarios import list_scenario_ids

app = typer.Typer(help="CauseGraph benchmark CLI")


@app.command("list-scenarios")
def list_scenarios() -> None:
    for scenario_id in list_scenario_ids():
        typer.echo(scenario_id)


@app.command("list-methods")
def list_methods_cmd() -> None:
    from benchmark.baselines import list_methods

    for method in list_methods():
        typer.echo(method)


@app.command("bootstrap-db")
def bootstrap_db() -> None:
    init_db()
    typer.echo("database schema ready")


@app.command("run-scenario")
def run_scenario_cmd(
    scenario_id: str,
    method: str = typer.Option("graph_only", help="RCA method to evaluate"),
    events_per_second: float = typer.Option(10.0, help="synthetic workload rate"),
) -> None:
    from benchmark.evaluator.evaluator import run_scenario

    run = run_scenario(scenario_id, method=method, events_per_second=events_per_second)
    typer.echo(json.dumps(run.model_dump(mode="json"), indent=2))


@app.command("compare-methods")
def compare_methods_cmd(
    scenario_id: str,
    methods: str = typer.Option(
        "", help="comma-separated method names; defaults to every registered method"
    ),
    events_per_second: float = typer.Option(10.0, help="synthetic workload rate"),
) -> None:
    from benchmark.evaluator.evaluator import compare_methods

    method_list = [m.strip() for m in methods.split(",") if m.strip()] or None
    runs = compare_methods(scenario_id, methods=method_list, events_per_second=events_per_second)

    typer.echo(f"{'method':<12} {'top1':<6} {'top3':<6} {'mrr':<6} {'rank':<6} ranked_candidates")
    for run in runs:
        m = run.metrics
        typer.echo(
            f"{run.method:<12} {str(m['top1_accuracy']):<6} {str(m['top3_accuracy']):<6} "
            f"{m['mrr']:<6.2f} {str(m['rank_of_ground_truth']):<6} {m['ranked_candidates']}"
        )


@app.command("run-ablations")
def run_ablations_cmd(
    scenario_id: str,
    events_per_second: float = typer.Option(10.0, help="synthetic workload rate"),
) -> None:
    from benchmark.evaluator.evaluator import run_ablations

    results = run_ablations(scenario_id, events_per_second=events_per_second)

    typer.echo(f"{'ablation':<38} {'top1':<6} {'top3':<6} {'mrr':<6} {'rank':<6} ranked_candidates")
    for label, run in results.items():
        m = run.metrics
        typer.echo(
            f"{label:<38} {str(m['top1_accuracy']):<6} {str(m['top3_accuracy']):<6} "
            f"{m['mrr']:<6.2f} {str(m['rank_of_ground_truth']):<6} {m['ranked_candidates']}"
        )


@app.command("run-calibration")
def run_calibration_cmd(
    method: str = typer.Option("causegraph", help="RCA method to evaluate"),
    scenarios: str = typer.Option("", help="comma-separated scenario ids; defaults to all"),
    n_runs_per_scenario: int = typer.Option(3, help="repeated runs per scenario, varying seed"),
    events_per_second: float = typer.Option(10.0, help="synthetic workload rate"),
) -> None:
    from benchmark.evaluator.evaluator import run_calibration_study

    scenario_ids = [s.strip() for s in scenarios.split(",") if s.strip()] or None
    result = run_calibration_study(
        method=method,
        scenario_ids=scenario_ids,
        n_runs_per_scenario=n_runs_per_scenario,
        events_per_second=events_per_second,
    )

    cal = result["calibration"]
    typer.echo(f"method={result['method']} n_runs={result['n_runs']} n_scored_pairs={result['n_scored_pairs']}")
    typer.echo(f"brier_score={cal.brier_score:.4f}  expected_calibration_error={cal.expected_calibration_error:.4f}")
    typer.echo(f"{'bin':<12} {'n':<5} {'avg_confidence':<16} accuracy")
    for b in cal.bin_details:
        conf = f"{b['avg_confidence']:.2f}" if b.get("avg_confidence") is not None else "-"
        acc = f"{b['accuracy']:.2f}" if b.get("accuracy") is not None else "-"
        typer.echo(f"{str(b['range']):<12} {b['n']:<5} {conf:<16} {acc}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
