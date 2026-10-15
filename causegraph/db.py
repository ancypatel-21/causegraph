"""SQLAlchemy engine, session, and ORM tables backing the shared schemas.

Tables mirror causegraph.schemas.models exactly (spec section 15). Pydantic
models are the API/contract layer; these are the storage layer. Keeping them
separate means the API schema can evolve without a migration on every tweak,
and tests can assert against plain dicts without touching the engine.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class ChangeEventRow(Base):
    __tablename__ = "change_events"

    id = Column(String, primary_key=True)
    node_id = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False)
    version_before = Column(String, nullable=True)
    version_after = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    metadata_json = Column(JSON, nullable=False, default=dict)


class IncidentRow(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True)
    started_at = Column(DateTime, nullable=False)
    detected_at = Column(DateTime, nullable=True)
    symptom_nodes = Column(JSON, nullable=False, default=list)
    trigger_signal = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    workload_id = Column(String, nullable=True)
    scenario_id = Column(String, nullable=True, index=True)
    metadata_json = Column(JSON, nullable=False, default=dict)


class HypothesisRow(Base):
    __tablename__ = "hypotheses"

    pk = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(String, nullable=False, index=True)
    candidate_node = Column(String, nullable=False)
    rank = Column(Integer, nullable=False)
    score = Column(Float, nullable=False)
    score_components = Column(JSON, nullable=False, default=dict)
    causal_path = Column(JSON, nullable=False, default=list)
    evidence_ids = Column(JSON, nullable=False, default=list)
    contradicting_evidence_ids = Column(JSON, nullable=False, default=list)


class EvidenceRow(Base):
    __tablename__ = "evidence"

    id = Column(String, primary_key=True)
    incident_id = Column(String, nullable=False, index=True)
    candidate_node = Column(String, nullable=False)
    evidence_type = Column(String, nullable=False)
    source = Column(String, nullable=False)
    observed_at = Column(DateTime, nullable=False)
    value = Column(JSON, nullable=False, default=dict)
    reliability = Column(Float, nullable=False)
    supports = Column(Boolean, nullable=False)


class BenchmarkRunRow(Base):
    __tablename__ = "benchmark_runs"

    id = Column(String, primary_key=True)
    git_sha = Column(String, nullable=False)
    scenario_id = Column(String, nullable=False, index=True)
    scenario_version = Column(String, nullable=False)
    seed = Column(Integer, nullable=False)
    workload_config = Column(JSON, nullable=False, default=dict)
    method = Column(String, nullable=False, index=True)
    method_config = Column(JSON, nullable=False, default=dict)
    llm_config = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    metrics = Column(JSON, nullable=False, default=dict)


_engine = None
_SessionFactory: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        url = os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://causegraph:causegraph@localhost:5432/causegraph",
        )
        _engine = create_engine(url, pool_pre_ping=True, future=True)
    return _engine


def init_db() -> None:
    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def utcnow() -> datetime:
    return datetime.utcnow()
