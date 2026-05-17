import pytest
from sqlalchemy.engine import Engine

import ai_agent.broker.fx as fx
from ai_agent.db.engine import create_engine_from_url, init_schema


@pytest.fixture(autouse=True)
def _no_network_fx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seed the FX cache so no test reaches the live rate service."""
    monkeypatch.setattr(fx, "_rates_cache", {})


@pytest.fixture
def in_memory_engine() -> Engine:
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(engine)
    return engine
