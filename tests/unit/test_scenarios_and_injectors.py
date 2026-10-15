import pytest

from benchmark.injectors import get_injector
from benchmark.injectors.cache_ttl import CacheTtlInjector
from benchmark.injectors.redis_unavailable import RedisUnavailableInjector
from benchmark.scenarios import list_scenario_ids, load_scenario


def test_all_five_scenarios_load_and_validate():
    ids = list_scenario_ids()
    assert len(ids) == 5
    for scenario_id in ids:
        scenario = load_scenario(scenario_id)
        assert scenario.id == scenario_id
        assert scenario.split in {"dev", "held_out"}
        assert scenario.root_cause in scenario.expected_path


def test_held_out_scenarios_are_genuinely_marked_held_out():
    held_out = {load_scenario(sid).id for sid in list_scenario_ids() if load_scenario(sid).split == "held_out"}
    assert held_out == {"cache-ttl-001", "redis-unavailable-001"}


def test_new_fault_injectors_are_registered():
    assert isinstance(get_injector("cache_ttl_regression"), CacheTtlInjector)
    assert isinstance(get_injector("redis_unavailable"), RedisUnavailableInjector)


def test_unknown_fault_raises():
    with pytest.raises(ValueError):
        get_injector("not_a_real_fault")
