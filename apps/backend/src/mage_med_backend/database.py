"""SQLite engine creation and bounded connectivity checks."""

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url


def create_sqlite_engine(database_url: str) -> Engine:
    """Create the configured SQLAlchemy engine with SQLite safety defaults."""

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError("MAGE-Med operational persistence must use SQLite")

    if url.database and url.database != ":memory:":
        Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


class SqliteConnectivity:
    """Execute a real SQLite connection check without accessing patient data."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def verify(self) -> None:
        """Open a connection and execute a fixed constant query."""

        with self._engine.connect() as connection:
            value = connection.execute(text("SELECT 1")).scalar_one()
            if value != 1:
                raise RuntimeError("SQLite readiness query returned an unexpected result")

    def close(self) -> None:
        """Dispose pooled database resources."""

        self._engine.dispose()
