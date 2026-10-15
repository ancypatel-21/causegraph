"""Change-event persistence. See docs/adr/0002-telemetry-stack.md.

Fault injectors call `record` when they toggle a fault, standing in for
real deploy/config/schema change events (spec section 4.2 CHANGED_BY edges,
section 5.1 step 5).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from causegraph.db import ChangeEventRow, session_scope
from causegraph.schemas import ChangeEvent


class ChangeEventRepository:
    def record(self, event: ChangeEvent) -> ChangeEvent:
        with session_scope() as session:
            session.add(
                ChangeEventRow(
                    id=event.id,
                    node_id=event.node_id,
                    type=event.type,
                    version_before=event.version_before,
                    version_after=event.version_after,
                    timestamp=event.timestamp,
                    metadata_json=event.metadata,
                )
            )
        return event

    def recent_for_node(
        self, node_id: str, start: datetime, end: datetime
    ) -> list[ChangeEvent]:
        with session_scope() as session:
            rows = (
                session.query(ChangeEventRow)
                .filter(
                    ChangeEventRow.node_id == node_id,
                    ChangeEventRow.timestamp >= start,
                    ChangeEventRow.timestamp <= end,
                )
                .order_by(ChangeEventRow.timestamp.desc())
                .all()
            )
            return [self._to_model(row) for row in rows]

    def recent_for_nodes(
        self, node_ids: list[str], lookback: timedelta, reference_time: datetime
    ) -> dict[str, list[ChangeEvent]]:
        start = reference_time - lookback
        result: dict[str, list[ChangeEvent]] = {}
        for node_id in node_ids:
            result[node_id] = self.recent_for_node(node_id, start, reference_time)
        return result

    @staticmethod
    def _to_model(row: ChangeEventRow) -> ChangeEvent:
        return ChangeEvent(
            id=row.id,
            node_id=row.node_id,
            type=row.type,
            version_before=row.version_before,
            version_after=row.version_after,
            timestamp=row.timestamp,
            metadata=row.metadata_json or {},
        )
