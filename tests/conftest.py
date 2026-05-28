from __future__ import annotations

import pytest

from tests.fixtures.build_fixtures import build


@pytest.fixture(scope="session", autouse=True)
def rebuild_generated_fixtures() -> None:
    build()
