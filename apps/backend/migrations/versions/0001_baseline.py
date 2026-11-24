"""Establish the empty operational-store migration baseline.

Revision ID: 0001_baseline
Revises: None
Create Date: 2026-11-23
"""

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create no domain tables before their owning milestone."""


def downgrade() -> None:
    """Remove no domain tables from the empty baseline."""
