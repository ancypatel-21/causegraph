"""Structured JSON logging correlated with the active trace. See ADR 0002."""

from __future__ import annotations

import json
import logging
import sys
import time

from causegraph.telemetry.otel import current_trace_context


class _JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        trace_id, span_id = current_trace_context()
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "service": self.service_name,
            "level": record.levelname,
            "message": record.getMessage(),
            "trace_id": trace_id,
            "span_id": span_id,
            "logger": record.name,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload)


def get_logger(service_name: str) -> logging.Logger:
    logger = logging.getLogger(service_name)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter(service_name))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
