"""Scenario manifest loader. See docs/adr/0004-benchmark-artifact-format.md."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from causegraph.schemas import Scenario

SCENARIOS_DIR = Path(__file__).parent


def load_scenario(scenario_id: str) -> Scenario:
    path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no scenario manifest found for '{scenario_id}' at {path}")

    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    scenario = Scenario.model_validate(data)
    if scenario.id != scenario_id:
        raise ValueError(f"scenario file {path} declares id '{scenario.id}', expected '{scenario_id}'")
    return scenario


def scenario_version(scenario_id: str) -> str:
    path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return f"{scenario_id}@{content_hash}"


def list_scenario_ids() -> list[str]:
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.yaml"))
