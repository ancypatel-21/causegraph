"""Prometheus metrics helpers shared across services. See ADR 0002."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest


class ServiceMetrics:
    """Per-service metric set, each labeled by `service` so Prometheus/PromQL
    queries stay uniform across every node in the dependency graph."""

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        self.registry = CollectorRegistry()

        self.request_latency = Histogram(
            "causegraph_request_latency_seconds",
            "Request latency in seconds",
            ["service", "route"],
            registry=self.registry,
        )
        self.request_errors = Counter(
            "causegraph_request_errors_total",
            "Total request errors",
            ["service", "route"],
            registry=self.registry,
        )
        self.requests_total = Counter(
            "causegraph_requests_total",
            "Total requests handled",
            ["service", "route"],
            registry=self.registry,
        )
        # Generic domain gauge so each service can report its own health
        # signal (null-feature rate, consumer lag, quality proxy, ...)
        # without every service needing a bespoke metric type.
        self.domain_gauge = Gauge(
            "causegraph_domain_signal",
            "Service-specific domain signal (see the `signal` label)",
            ["service", "signal"],
            registry=self.registry,
        )

    def observe_request(self, route: str, duration_seconds: float, error: bool = False) -> None:
        self.requests_total.labels(service=self.service_name, route=route).inc()
        self.request_latency.labels(service=self.service_name, route=route).observe(duration_seconds)
        if error:
            self.request_errors.labels(service=self.service_name, route=route).inc()

    def set_signal(self, signal: str, value: float) -> None:
        self.domain_gauge.labels(service=self.service_name, signal=signal).set(value)


def mount_metrics(app: FastAPI, metrics: ServiceMetrics) -> None:
    @app.get("/metrics")
    def metrics_endpoint() -> Response:
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    @app.middleware("http")
    async def _timing_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in ("/metrics", "/healthz"):
            return await call_next(request)
        start = time.perf_counter()
        error = False
        try:
            response = await call_next(request)
            error = response.status_code >= 500
            return response
        except Exception:
            error = True
            raise
        finally:
            duration = time.perf_counter() - start
            metrics.observe_request(request.url.path, duration, error=error)
