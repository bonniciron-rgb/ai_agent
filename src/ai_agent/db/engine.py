import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from ai_agent.settings import get_settings

logger = logging.getLogger(__name__)


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
    engine = engine or get_engine()
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    """Add model columns that are absent from already-existing tables.

    ``create_all`` only ever issues ``CREATE TABLE`` — it never ALTERs an
    existing table, so a column added to a model after its table was first
    created stays missing (and every query selecting it then fails). This
    reconciles that drift. It only ever ADDs columns as nullable; it never
    drops, retypes, or adds NOT NULL (which would break on populated rows).

    Postgres-only — SQLite dev/test databases are always created fresh, so
    they never drift and ``ADD COLUMN IF NOT EXISTS`` is not SQLite syntax.
    """
    if engine.dialect.name != "postgresql":
        return
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in present:
                    continue
                col_type = col.type.compile(engine.dialect)
                conn.exec_driver_sql(
                    f'ALTER TABLE "{table.name}" ADD COLUMN IF NOT EXISTS "{col.name}" {col_type}'
                )
                logger.warning(
                    "Schema drift: added missing column %s.%s (%s)",
                    table.name,
                    col.name,
                    col_type,
                )


@contextmanager
def get_session(engine: Engine | None = None) -> Iterator[Session]:
    with Session(engine or get_engine()) as session:
        yield session
