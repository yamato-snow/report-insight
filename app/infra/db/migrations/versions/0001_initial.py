"""initial schema (DB設計書 04 の全テーブル + pgvector + HNSW)

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "branches",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("branch_id", sa.BigInteger(), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("role", sa.Text(), nullable=False),
    )

    op.create_table(
        "properties",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("branch_id", sa.BigInteger(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
    )
    op.create_index("ix_properties_branch_id", "properties", ["branch_id"])

    op.create_table(
        "reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("property_id", sa.BigInteger(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reporter_role", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("photo_meta", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("source_key", name="uq_reports_source_key"),
    )
    op.create_index("ix_reports_property_id", "reports", ["property_id"])
    op.create_index("ix_reports_reported_at", "reports", ["reported_at"])

    op.create_table(
        "report_analyses",
        sa.Column(
            "report_id",
            sa.BigInteger(),
            sa.ForeignKey("reports.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("urgency", sa.String(16), nullable=False),
        sa.Column("action_required", sa.Boolean(), nullable=False),
        sa.Column("normalized_summary", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(precision=24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "analyzed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_report_analyses_category", "report_analyses", ["category"])
    op.create_index("ix_report_analyses_urgency", "report_analyses", ["urgency"])
    op.create_index("ix_report_analyses_status", "report_analyses", ["status"])

    op.create_table(
        "report_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "report_id",
            sa.BigInteger(),
            sa.ForeignKey("reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    )
    op.create_index("ix_report_chunks_report_id", "report_chunks", ["report_id"])
    # HNSW（IVFFlat はデータ増加時に再構築が必要なため。DB設計書 §2）
    op.execute(
        "CREATE INDEX ix_report_chunks_embedding_hnsw "
        "ON report_chunks USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "monthly_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("property_id", sa.BigInteger(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("body_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("approved_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("property_id", "month", "version", name="uq_monthly_pmv"),
    )
    op.create_index("ix_monthly_reports_property_id", "monthly_reports", ["property_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("monthly_reports")
    op.execute("DROP INDEX IF EXISTS ix_report_chunks_embedding_hnsw")
    op.drop_table("report_chunks")
    op.drop_table("report_analyses")
    op.drop_table("reports")
    op.drop_table("properties")
    op.drop_table("users")
    op.drop_table("branches")
