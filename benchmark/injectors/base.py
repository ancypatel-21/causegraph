"""Fault injector interface. Each injector knows how to turn one scenario's
`fault` on and off against the real running services, via their admin HTTP
endpoints -- never via arbitrary shell execution (spec section 2.2)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class FaultInjector(ABC):
    fault_name: str

    @abstractmethod
    async def enable(self) -> None: ...

    @abstractmethod
    async def disable(self) -> None: ...
