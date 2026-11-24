"""Add clinical text provenance and deterministic note chunks.

Revision ID: 0004_clinical_text
Revises: 0003_fhir_ingestion
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_clinical_text"
down_revision: str | None = "0003_fhir_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Preserve note originals/origin and add traceable chunks."""

    with op.batch_alter_table("source_resource_mappings") as batch:
        batch.drop_constraint("ck_source_resource_mapping_outcome", type_="check")
        batch.create_check_constraint(
            "ck_source_resource_mapping_outcome_v2",
            "outcome_status IN ('imported', 'updated', 'unavailable', 'unusable', 'unsupported')",
        )

    with op.batch_alter_table("clinical_notes") as batch:
        batch.add_column(sa.Column("original_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source_label", sa.String(length=512)))
        batch.add_column(sa.Column("content_origin", sa.String(length=64), nullable=True))
    op.execute("UPDATE clinical_notes SET original_text = text WHERE original_text IS NULL")
    op.execute(
        "UPDATE clinical_notes SET content_origin = 'fhir_embedded' WHERE content_origin IS NULL"
    )
    with op.batch_alter_table("clinical_notes") as batch:
        batch.alter_column("original_text", nullable=False)
        batch.alter_column("content_origin", nullable=False)
        batch.create_check_constraint(
            "ck_clinical_notes_content_origin",
            "content_origin IN ('direct_file', 'fhir_embedded', 'fhir_local_file')",
        )

    op.create_table(
        "clinical_note_chunks",
        sa.Column("internal_id", sa.String(length=36), primary_key=True),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column(
            "note_id",
            sa.String(length=36),
            sa.ForeignKey("clinical_notes.internal_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("section", sa.String(length=256)),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("note_id", "chunk_index", name="uq_note_chunk_index"),
        sa.CheckConstraint("start_offset >= 0", name="ck_note_chunk_start"),
        sa.CheckConstraint("end_offset > start_offset", name="ck_note_chunk_offsets"),
    )
    op.create_index("ix_clinical_note_chunks_note_id", "clinical_note_chunks", ["note_id"])


def downgrade() -> None:
    """Remove chunk storage and note-origin fields."""

    op.drop_table("clinical_note_chunks")
    with op.batch_alter_table("clinical_notes") as batch:
        batch.drop_constraint("ck_clinical_notes_content_origin", type_="check")
        batch.drop_column("content_origin")
        batch.drop_column("source_label")
        batch.drop_column("original_text")
    with op.batch_alter_table("source_resource_mappings") as batch:
        batch.drop_constraint("ck_source_resource_mapping_outcome_v2", type_="check")
        batch.create_check_constraint(
            "ck_source_resource_mapping_outcome",
            "outcome_status IN ('imported', 'updated', 'unusable', 'unsupported')",
        )
