"""Integration layer (spec section 16): Kafka -> feature-worker ->
feature-store -> model-service -> ranking-api, exercised against the real
Compose stack on localhost ports.
"""

from __future__ import annotations

import time

import httpx

from tests.conftest import requires_live_stack

EVENT_API = "http://localhost:18001"
RANKING_API = "http://localhost:8004"


@requires_live_stack
def test_event_propagates_to_a_ranking_score():
    item_id = f"it-{int(time.time())}"

    for _ in range(10):
        resp = httpx.post(
            f"{EVENT_API}/events",
            json={"user_id": "itest-user", "item_id": item_id, "event_type": "impression"},
            timeout=5.0,
        )
        assert resp.status_code == 200

    # Give the Kafka consumer time to process and write the feature.
    time.sleep(3.0)

    resp = httpx.get(
        f"{RANKING_API}/rank",
        params={"user_id": "itest-user", "candidates": item_id},
        timeout=5.0,
    )
    assert resp.status_code == 200
    ranked = resp.json()["ranked_items"]
    assert ranked[0]["item_id"] == item_id
    assert ranked[0]["feature_skew"] is False
