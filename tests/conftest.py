"""Shared test configuration.

Unit tests (tests/unit) never touch the network or a database and always
run in CI. Integration and e2e tests (tests/integration, tests/e2e) exercise
the real Docker Compose stack (spec section 16) and only run when that stack
is already up -- set RUN_LIVE_STACK_TESTS=1 after `make up` to opt in.
"""

import os

import pytest

requires_live_stack = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_STACK_TESTS") != "1",
    reason="set RUN_LIVE_STACK_TESTS=1 with the compose stack running (`make up`) to run this test",
)
