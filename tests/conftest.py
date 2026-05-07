import pytest
from sqlalchemy.engine import Engine

from ai_agent.db.engine import create_engine_from_url, init_schema


@pytest.fixture
def in_memory_engine() -> Engine:
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(engine)
    return engine
