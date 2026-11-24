"""Add the canonical versioned clinical and provenance data model.

Revision ID: 0002_canonical_clinical_model
Revises: 0001_baseline
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_canonical_clinical_model"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fact_columns() -> list[sa.Column]:
    return [
        sa.Column("internal_id", sa.String(length=36), primary_key=True),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("modality", sa.String(length=64), nullable=False),
        sa.Column(
            "source_artifact_id",
            sa.String(length=36),
            sa.ForeignKey("source_artifacts.internal_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "import_manifest_id",
            sa.String(length=36),
            sa.ForeignKey("import_manifests.internal_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_locator", sa.String(length=2048), nullable=False),
        sa.Column("source_resource_type", sa.String(length=128)),
        sa.Column("source_resource_id", sa.String(length=256)),
        sa.Column("event_time", sa.DateTime(timezone=True)),
        sa.Column("event_date", sa.Date()),
        sa.Column("recorded_time", sa.DateTime(timezone=True)),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assertion_type", sa.String(length=64), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.CheckConstraint("schema_version = '1.0.0'", name="ck_%(table_name)s_schema_version"),
        sa.CheckConstraint(
            "modality IN ('structured_clinical_data', 'unstructured_clinical_text')",
            name="ck_%(table_name)s_modality",
        ),
        sa.CheckConstraint(
            "assertion_type IN ('observed', 'extracted', 'model_inferred', "
            "'hypothesized', 'clinician_confirmed')",
            name="ck_%(table_name)s_assertion_type",
        ),
    ]


def _patient_encounter_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "patient_id",
            sa.String(length=36),
            sa.ForeignKey("patients.internal_id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "encounter_id",
            sa.String(length=36),
            sa.ForeignKey("encounters.internal_id", ondelete="RESTRICT"),
        ),
    ]


def _index_fact_table(table_name: str, *, patient_context: bool = False) -> None:
    op.create_index(f"ix_{table_name}_source_artifact_id", table_name, ["source_artifact_id"])
    op.create_index(f"ix_{table_name}_import_manifest_id", table_name, ["import_manifest_id"])
    op.create_index(
        f"ix_{table_name}_source_resource",
        table_name,
        ["source_resource_type", "source_resource_id"],
    )
    if patient_context:
        op.create_index(f"ix_{table_name}_patient_id", table_name, ["patient_id"])
        op.create_index(f"ix_{table_name}_encounter_id", table_name, ["encounter_id"])


def upgrade() -> None:
    """Create canonical source, import, and clinical fact tables."""

    op.create_table(
        "source_artifacts",
        sa.Column("internal_id", sa.String(length=36), primary_key=True),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("modality", sa.String(length=64), nullable=False),
        sa.Column("source_format", sa.String(length=64), nullable=False),
        sa.Column("source_locator", sa.String(length=2048), nullable=False),
        sa.Column("original_filename", sa.String(length=512)),
        sa.Column("media_type", sa.String(length=256), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False, unique=True),
        sa.Column("raw_content", sa.JSON(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.CheckConstraint("schema_version = '1.0.0'", name="ck_source_artifact_version"),
        sa.CheckConstraint(
            "modality IN ('structured_clinical_data', 'unstructured_clinical_text')",
            name="ck_source_artifact_modality",
        ),
        sa.CheckConstraint(
            "source_format IN ('fhir_r4_json', 'json', 'csv', 'txt')",
            name="ck_source_artifact_format",
        ),
    )
    op.create_table(
        "import_manifests",
        sa.Column("internal_id", sa.String(length=36), primary_key=True),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("dataset_id", sa.String(length=256), nullable=False),
        sa.Column("dataset_version", sa.String(length=128), nullable=False),
        sa.Column("source_format", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("source_artifact_ids", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("importer_name", sa.String(length=128), nullable=False),
        sa.Column("importer_version", sa.String(length=32), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("seed", sa.Integer()),
        sa.Column("record_counts", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.UniqueConstraint("dataset_id", "dataset_version", "internal_id", name="uq_import_run"),
        sa.CheckConstraint("schema_version = '1.0.0'", name="ck_import_manifest_version"),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')", name="ck_import_manifest_status"
        ),
    )
    op.create_index("ix_import_manifests_dataset_id", "import_manifests", ["dataset_id"])

    op.create_table(
        "patients",
        *_fact_columns(),
        sa.Column("identifiers", sa.JSON(), nullable=False),
        sa.Column("family_name", sa.String(length=256)),
        sa.Column("given_names", sa.JSON(), nullable=False),
        sa.Column("birth_date", sa.Date()),
        sa.Column("administrative_gender", sa.String(length=64)),
        sa.Column("active", sa.Boolean()),
        sa.UniqueConstraint(
            "source_artifact_id",
            "source_resource_type",
            "source_resource_id",
            name="uq_patient_source_resource",
        ),
    )
    _index_fact_table("patients")

    op.create_table(
        "encounters",
        *_fact_columns(),
        sa.Column(
            "patient_id",
            sa.String(length=36),
            sa.ForeignKey("patients.internal_id", ondelete="RESTRICT"),
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("class_code", sa.JSON()),
        sa.Column("encounter_type", sa.JSON()),
        sa.Column("period_start", sa.DateTime(timezone=True)),
        sa.Column("period_end", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "source_artifact_id",
            "source_resource_type",
            "source_resource_id",
            name="uq_encounter_source_resource",
        ),
    )
    _index_fact_table("encounters")
    op.create_index("ix_encounters_patient_id", "encounters", ["patient_id"])

    op.create_table(
        "conditions",
        *_fact_columns(),
        *_patient_encounter_columns(),
        sa.Column("code", sa.JSON(), nullable=False),
        sa.Column("clinical_status", sa.JSON()),
        sa.Column("verification_status", sa.JSON()),
        sa.Column("onset_time", sa.DateTime(timezone=True)),
        sa.Column("onset_date", sa.Date()),
        sa.Column("abatement_time", sa.DateTime(timezone=True)),
        sa.Column("abatement_date", sa.Date()),
    )
    _index_fact_table("conditions", patient_context=True)

    op.create_table(
        "observations",
        *_fact_columns(),
        *_patient_encounter_columns(),
        sa.Column("code", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("value_quantity", sa.Numeric(18, 6)),
        sa.Column("value_unit", sa.String(length=128)),
        sa.Column("value_unit_system", sa.String(length=512)),
        sa.Column("value_unit_code", sa.String(length=128)),
        sa.Column("value_text", sa.Text()),
        sa.Column("data_absent_reason", sa.JSON()),
        sa.Column("reference_range", sa.JSON(), nullable=False),
    )
    _index_fact_table("observations", patient_context=True)

    op.create_table(
        "medication_requests",
        *_fact_columns(),
        *_patient_encounter_columns(),
        sa.Column("medication", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=False),
        sa.Column("authored_on", sa.DateTime(timezone=True)),
        sa.Column("dosage_text", sa.Text()),
    )
    _index_fact_table("medication_requests", patient_context=True)

    op.create_table(
        "allergies",
        *_fact_columns(),
        *_patient_encounter_columns(),
        sa.Column("substance", sa.JSON(), nullable=False),
        sa.Column("clinical_status", sa.JSON()),
        sa.Column("verification_status", sa.JSON()),
        sa.Column("allergy_type", sa.String(length=64)),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("criticality", sa.String(length=64)),
        sa.Column("reactions", sa.JSON(), nullable=False),
    )
    _index_fact_table("allergies", patient_context=True)

    op.create_table(
        "clinical_notes",
        *_fact_columns(),
        *_patient_encounter_columns(),
        sa.Column("note_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512)),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("authored_at", sa.DateTime(timezone=True)),
        sa.Column("author_reference", sa.String(length=512)),
    )
    _index_fact_table("clinical_notes", patient_context=True)

    op.create_table(
        "clinical_assertions",
        *_fact_columns(),
        *_patient_encounter_columns(),
        sa.Column("subject_record_type", sa.String(length=128), nullable=False),
        sa.Column("subject_record_id", sa.String(length=36), nullable=False),
        sa.Column("predicate", sa.String(length=256), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=64)),
        sa.Column("verification_status", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
    )
    _index_fact_table("clinical_assertions", patient_context=True)


def downgrade() -> None:
    """Remove the canonical clinical model in reverse dependency order."""

    for table_name in (
        "clinical_assertions",
        "clinical_notes",
        "allergies",
        "medication_requests",
        "observations",
        "conditions",
        "encounters",
        "patients",
        "import_manifests",
        "source_artifacts",
    ):
        op.drop_table(table_name)
