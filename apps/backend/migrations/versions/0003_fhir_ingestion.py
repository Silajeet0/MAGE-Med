"""Add FHIR import reporting, source mappings, and rejected assertion class.

Revision ID: 0003_fhir_ingestion
Revises: 0002_canonical_clinical_model
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_fhir_ingestion"
down_revision: str | None = "0002_canonical_clinical_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FACT_TABLES = (
    "patients",
    "encounters",
    "conditions",
    "observations",
    "medication_requests",
    "allergies",
    "clinical_notes",
    "clinical_assertions",
)


def upgrade() -> None:
    """Add import result persistence and align assertion classes with policy."""

    op.add_column(
        "import_manifests",
        sa.Column("primary_source_artifact_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "import_manifests",
        sa.Column(
            "validation_summary",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "import_manifests",
        sa.Column(
            "resource_outcomes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    with op.batch_alter_table("import_manifests") as batch:
        batch.create_foreign_key(
            "fk_import_manifest_primary_artifact",
            "source_artifacts",
            ["primary_source_artifact_id"],
            ["internal_id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_import_manifest_primary_artifact", ["primary_source_artifact_id"]
        )
    op.create_index(
        "ix_import_manifests_primary_source_artifact_id",
        "import_manifests",
        ["primary_source_artifact_id"],
    )

    op.create_table(
        "source_resource_mappings",
        sa.Column("internal_id", sa.String(length=36), primary_key=True),
        sa.Column("source_key", sa.String(length=1024), nullable=False, unique=True),
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
        sa.Column("resource_type", sa.String(length=128)),
        sa.Column("resource_id", sa.String(length=256)),
        sa.Column("full_url", sa.String(length=2048)),
        sa.Column("normalized_type", sa.String(length=128)),
        sa.Column("normalized_id", sa.String(length=36)),
        sa.Column("outcome_status", sa.String(length=64), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("original_resource", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome_status IN ('imported', 'updated', 'unusable', 'unsupported')",
            name="ck_source_resource_mapping_outcome",
        ),
    )
    for column in (
        "source_artifact_id",
        "import_manifest_id",
        "resource_type",
        "full_url",
        "normalized_id",
    ):
        op.create_index(
            f"ix_source_resource_mappings_{column}", "source_resource_mappings", [column]
        )

    for table_name in FACT_TABLES:
        with op.batch_alter_table(table_name) as batch:
            batch.drop_constraint("ck_%(table_name)s_assertion_type", type_="check")
            batch.create_check_constraint(
                f"ck_{table_name}_assertion_type_v2",
                "assertion_type IN ('observed', 'extracted', 'model_inferred', "
                "'hypothesized', 'clinician_confirmed', 'clinician_rejected')",
            )


def downgrade() -> None:
    """Remove FHIR import result persistence and restore prior assertion classes."""

    for table_name in reversed(FACT_TABLES):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_constraint(f"ck_{table_name}_assertion_type_v2", type_="check")
            batch.create_check_constraint(
                "ck_%(table_name)s_assertion_type",
                "assertion_type IN ('observed', 'extracted', 'model_inferred', "
                "'hypothesized', 'clinician_confirmed')",
            )

    op.drop_table("source_resource_mappings")
    op.drop_index("ix_import_manifests_primary_source_artifact_id", table_name="import_manifests")
    with op.batch_alter_table("import_manifests") as batch:
        batch.drop_constraint("uq_import_manifest_primary_artifact", type_="unique")
        batch.drop_constraint("fk_import_manifest_primary_artifact", type_="foreignkey")
        batch.drop_column("resource_outcomes")
        batch.drop_column("validation_summary")
        batch.drop_column("primary_source_artifact_id")
