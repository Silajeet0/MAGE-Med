from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from mage_med_backend.database import create_sqlite_engine
from mage_med_backend.persistence import SourceArtifactRecord
from mage_med_contracts import DataModality, SourceFormat
from sqlalchemy import text
from sqlalchemy.orm import Session


def _migrated_engine(tmp_path: Path):
    repository_root = Path(__file__).resolve().parents[3]
    database_path = tmp_path / "canonical.db"
    config = Config(repository_root / "apps/backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    return create_sqlite_engine(f"sqlite:///{database_path}")


def test_source_artifact_round_trip_preserves_original_resource(tmp_path: Path) -> None:
    engine = _migrated_engine(tmp_path)
    original = {
        "resourceType": "Patient",
        "id": "synthetic-patient",
        "name": [{"text": "SYNTHETIC Testpatient"}],
    }
    record = SourceArtifactRecord(
        internal_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        schema_version="1.0.0",
        modality=DataModality.STRUCTURED_CLINICAL_DATA,
        source_format=SourceFormat.FHIR_R4_JSON,
        source_locator="fixture.json",
        original_filename="fixture.json",
        media_type="application/fhir+json",
        sha256="a" * 64,
        raw_content=original,
        imported_at=datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
        synthetic=True,
    )
    with Session(engine) as session:
        session.add(record)
        session.commit()
        restored = session.get(SourceArtifactRecord, record.internal_id)
        assert restored is not None
        assert restored.raw_content == original

        restored.source_locator = "changed.json"
        with pytest.raises(ValueError, match="immutable"):
            session.commit()
        session.rollback()
    engine.dispose()


def test_sqlite_enforces_foreign_keys_for_clinical_facts(tmp_path: Path) -> None:
    engine = _migrated_engine(tmp_path)
    with engine.connect() as connection:
        enabled = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        assert enabled == 1
    engine.dispose()
