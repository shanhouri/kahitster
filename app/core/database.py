from collections.abc import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


def engine_config(url: str) -> tuple[str, dict]:
    """Turn a database URL as a provider hands it out into one we can use.

    Hosted Postgres (Neon, Render, ...) gives `postgresql://...?sslmode=require`.
    The async driver wants its own scheme and takes TLS as an argument, not as
    a URL parameter.
    """
    if not url.startswith(("postgres://", "postgresql://")):
        return url, {}

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    # Free databases suspend when idle and drop our pooled connections; check
    # each one before use and do not keep any for long.
    options: dict = {"pool_pre_ping": True, "pool_recycle": 300}
    if query.pop("sslmode", "disable") != "disable":
        options["connect_args"] = {"ssl": "require"}
    query.pop("channel_binding", None)  # libpq-only; asyncpg rejects it
    url = urlunsplit(("postgresql+asyncpg", parts.netloc, parts.path, urlencode(query), ""))
    return url, options


_url, _options = engine_config(get_settings().database_url)
engine = create_async_engine(_url, **_options)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


# Columns added after the first release: (table, column, SQL definition).
# create_all only makes missing tables, so existing databases get these here.
_ADDED_COLUMNS = [
    # Quizzes from before hosts had accounts go to whoever signs in first
    # (see api/auth.py).
    ("quizzes", "owner_id", "INTEGER REFERENCES accounts(id)"),
    ("quiz_songs", "names_checked", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def _upgrade(conn) -> None:
    inspector = inspect(conn)
    for table, column, definition in _ADDED_COLUMNS:
        if column not in {c["name"] for c in inspector.get_columns(table)}:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


async def init_db() -> None:
    from app import models  # noqa: F401 -- registers the tables on Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_upgrade)
