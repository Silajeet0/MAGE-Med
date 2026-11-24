from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import Mock

from mage_med_knowledge_graph import Neo4jConnectivity


def test_connectivity_uses_fixed_readiness_query() -> None:
    record = {"ready": 1}
    result = Mock()
    result.single.return_value = record
    session = Mock()
    session.run.return_value = result

    @contextmanager
    def session_context(**kwargs: Any) -> Iterator[Mock]:
        assert kwargs == {"database": "neo4j"}
        yield session

    driver = Mock()
    driver.session.side_effect = session_context
    factory = Mock(return_value=driver)

    connectivity = Neo4jConnectivity(
        uri="bolt://example.invalid:7687",
        username="neo4j",
        password="local-test-password",
        database="neo4j",
        timeout_seconds=1.0,
        driver_factory=factory,
    )
    connectivity.verify()
    connectivity.close()

    driver.verify_connectivity.assert_called_once_with()
    session.run.assert_called_once_with("RETURN 1 AS ready")
    result.single.assert_called_once_with(strict=True)
    driver.close.assert_called_once_with()
