from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from ai_agent.settings import get_settings


def _normalize_postgres_driver(url: str) -> str:
    # We ship psycopg (v3) but not psycopg2. SQLAlchemy's bare
    # postgresql:// scheme resolves to psycopg2 by default, so steer
    # it to psycopg explicitly when the user supplies a generic URL.
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def create_engine_from_url(url: str, *, echo: bool = False) -> Engine:
    url = _normalize_postgres_driver(url)
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
