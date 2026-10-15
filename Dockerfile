FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY causegraph ./causegraph
COPY benchmark ./benchmark
COPY services ./services

RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
