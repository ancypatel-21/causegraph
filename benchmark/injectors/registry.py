from __future__ import annotations

from benchmark.injectors.base import FaultInjector
from benchmark.injectors.cache_ttl import CacheTtlInjector
from benchmark.injectors.consumer_lag import ConsumerLagInjector
from benchmark.injectors.latency import LatencyInjector
from benchmark.injectors.redis_unavailable import RedisUnavailableInjector
from benchmark.injectors.schema_break import SchemaBreakInjector

_REGISTRY: dict[str, type[FaultInjector]] = {
    "incompatible_schema": SchemaBreakInjector,
    "latency": LatencyInjector,
    "consumer_lag": ConsumerLagInjector,
    "cache_ttl_regression": CacheTtlInjector,
    "redis_unavailable": RedisUnavailableInjector,
}


def get_injector(fault_name: str) -> FaultInjector:
    injector_cls = _REGISTRY.get(fault_name)
    if injector_cls is None:
        raise ValueError(f"no fault injector registered for '{fault_name}'")
    return injector_cls()
