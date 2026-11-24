"""Alembic environment for the SQLite operational store."""

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from mage_med_backend.config import Settings
from mage_med_backend.persistence import Base
from sqlalchemy import Enum, String, engine_from_config, pool
from sqlalchemy.engine import make_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _compare_sqlite_type(
    migration_context: object,
    inspected_column: object,
    metadata_column: object,
    inspected_type: object,
    metadata_type: object,
) -> bool | None:
    """Treat reflected SQLite strings as equivalent to constrained enums."""

    dialect = migration_context.dialect  # type: ignore[attr-defined]
    if (
        dialect.name == "sqlite"
        and isinstance(metadata_type, Enum)
        and isinstance(inspected_type, String)
    ):
        return False
    return None


def _database_url() -> str:
    configured = config.get_main_option("sqlalchemy.url") or Settings().database_url
    url = make_url(configured)
    if url.get_backend_name() != "sqlite":
        raise RuntimeError("Alembic migrations are restricted to SQLite")
    if url.database and url.database != ":memory:":
        Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return configured


def run_migrations_offline() -> None:
    """Run migrations without creating an Engine."""

    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=_compare_sqlite_type,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations through a live SQLite connection."""

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=_compare_sqlite_type,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
