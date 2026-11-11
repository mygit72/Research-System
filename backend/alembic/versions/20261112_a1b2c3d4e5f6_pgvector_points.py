"""Add pgvector extension and vector_points table for PostgreSQL.

Revision ID: a1b2c3d4e5f6
Revises: ed9b4054f6d5
Create Date: 2026-11-12 02:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "ed9b4054f6d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS vector_points (
                collection_name VARCHAR(120) NOT NULL,
                id UUID NOT NULL,
                user_id UUID NOT NULL,
                document_id UUID,
                version_id UUID,
                section_kind VARCHAR(60),
                doc_type VARCHAR(60),
                year INTEGER,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                vector vector,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                PRIMARY KEY (collection_name, id)
            );
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_vector_points_lookup "
            "ON vector_points (collection_name, user_id);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_vector_points_doc "
            "ON vector_points (collection_name, document_id);"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_vector_points_ver "
            "ON vector_points (collection_name, version_id);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS vector_points;")

