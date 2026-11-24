from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_alembic_upgrades_empty_sqlite_database_to_canonical_model(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    config = Config(repository_root / "apps/backend/alembic.ini")
    database_path = tmp_path / "migration.db"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert revision == "0004_clinical_text"
    assert {
        "source_artifacts",
        "import_manifests",
        "patients",
        "encounters",
        "conditions",
        "observations",
        "medication_requests",
        "allergies",
        "clinical_notes",
        "clinical_note_chunks",
        "clinical_assertions",
        "source_resource_mappings",
    } <= tables

    command.downgrade(config, "0002_canonical_clinical_model")
    command.upgrade(config, "head")
    command.check(config)
