from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from ai_agent.settings import get_settings


def create_engine_from_url(url: str, *, echo: bool = False) -> Engine:
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, echo=echo, connect_args=connect_args, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine_from_url(get_settings().database_url)


def init_schema(engine: Engine | None = None) -> None:
    SQLModel.metadata.create_all(engine or get_engine())


@contextmanager
def get_session(engine: Engine | None = None) -> Iterator[Session]:
    with Session(engine or get_engine()) as session:
        yield session
