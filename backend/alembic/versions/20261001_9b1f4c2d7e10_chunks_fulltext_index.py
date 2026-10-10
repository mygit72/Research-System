"""chunks full-text index (PostgreSQL)

GIN index over to_tsvector('english', text) for the PostgreSQL FTS sparse
retriever (SPARSE_RETRIEVER=postgres). The expression must match the query in
app/services/retrieval/sparse.py exactly, or PostgreSQL won't use the index.
No-op on SQLite (local development uses the in-memory BM25 retriever).

Revision ID: 9b1f4c2d7e10
Revises: 6cade2ad7875
Create Date: 2026-10-01 12:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9b1f4c2d7e10"
down_revision: str | None = "6cade2ad7875"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_chunks_text_fts ON chunks "
            "USING gin (to_tsvector('english'::regconfig, text))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_chunks_text_fts")
