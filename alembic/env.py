import os
from logging.config import fileConfig
import sys
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from alembic import context
from app.db.base import Base  # noqa
from app import models  # noqa: F401

config = context.config

# ── Read DATABASE_URL from environment (never from alembic.ini interpolation) ─
_db_url = os.getenv("DATABASE_URL")
if not _db_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set.\n"
        "Set it before running alembic, e.g.:\n"
        "  $env:DATABASE_URL='postgresql+asyncpg://user:pass@host/db'  (PowerShell)\n"
        "  export DATABASE_URL=postgresql+asyncpg://user:pass@host/db  (bash)"
    )

# Override whatever is in alembic.ini — env var always wins
config.set_main_option("sqlalchemy.url", _db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online_entry():
    import asyncio
    asyncio.run(run_migrations_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online_entry()