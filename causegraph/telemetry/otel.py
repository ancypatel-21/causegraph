"""OpenTelemetry setup. See docs/adr/0002-telemetry-stack.md."""

from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_NAMESPACE, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_initialized = False


def setup_tracing(service_name: str) -> None:
    global _initialized
    if _initialized:
        return

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")
    namespace = os.environ.get("OTEL_SERVICE_NAMESPACE", "causegraph")

    resource = Resource.create({SERVICE_NAME: service_name, SERVICE_NAMESPACE: namespace})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    HTTPXClientInstrumentor().instrument()
    _initialized = True


def instrument_app(app: FastAPI, service_name: str) -> None:
    setup_tracing(service_name)
    FastAPIInstrumentor.instrument_app(app)


def current_trace_context() -> tuple[str | None, str | None]:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx is None or ctx.trace_id == 0:
        return None, None
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
