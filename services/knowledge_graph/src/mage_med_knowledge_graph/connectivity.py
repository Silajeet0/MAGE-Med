"""Minimal, bounded Neo4j connectivity used by readiness checks."""

from typing import Protocol

from neo4j import Driver, GraphDatabase


class DriverFactory(Protocol):
    """Callable shape used to inject the official driver in tests."""

    def __call__(
        self,
        uri: str,
        *,
        auth: tuple[str, str],
        connection_timeout: float,
    ) -> Driver: ...


def create_neo4j_driver(
    *,
    uri: str,
    username: str,
    password: str,
    timeout_seconds: float,
    driver_factory: DriverFactory = GraphDatabase.driver,
) -> Driver:
    """Create the official driver without exposing driver construction to callers."""

    return driver_factory(
        uri,
        auth=(username, password),
        connection_timeout=timeout_seconds,
    )


class Neo4jConnectivity:
    """Own an official Neo4j driver and verify it with a fixed read query."""

    def __init__(
        self,
        *,
        uri: str,
        username: str,
        password: str,
        database: str,
        timeout_seconds: float,
        driver_factory: DriverFactory = GraphDatabase.driver,
    ) -> None:
        self._database = database
        self._driver = create_neo4j_driver(
            uri=uri,
            username=username,
            password=password,
            timeout_seconds=timeout_seconds,
            driver_factory=driver_factory,
        )

    def verify(self) -> None:
        """Verify connectivity and execute one fixed query against the configured database."""

        self._driver.verify_connectivity()
        with self._driver.session(database=self._database) as session:
            record = session.run("RETURN 1 AS ready").single(strict=True)
            if record is None or record["ready"] != 1:
                raise RuntimeError("Neo4j readiness query returned an unexpected result")

    def close(self) -> None:
        """Release driver resources."""

        self._driver.close()
