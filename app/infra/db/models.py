"""SQLAlchemy 2 モデル（DB設計書 04 の全テーブル）。ORMは infra に閉じる（規約）。"""

from __future__ import annotations

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 1024


class Base(DeclarativeBase):
    pass


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    branch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("branches.id"), nullable=True
    )  # NULL = 品質管理部
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # branch_manager | qa


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("branches.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    property_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("properties.id"), nullable=False, index=True
    )
    source_key: Mapped[str] = mapped_column(Text, nullable=False)  # S3キー（冪等性キー）
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    reporter_role: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    photo_meta: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    analysis: Mapped[ReportAnalysis | None] = relationship(
        back_populates="report", uselist=False, cascade="all, delete-orphan"
    )
    chunks: Mapped[list[ReportChunk]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("source_key", name="uq_reports_source_key"),)


class ReportAnalysis(Base):
    __tablename__ = "report_analyses"

    report_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    urgency: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    action_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    normalized_summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float(precision=24), nullable=False)  # PG REAL
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    report: Mapped[Report] = relationship(back_populates="analysis")


class ReportChunk(Base):
    __tablename__ = "report_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    report: Mapped[Report] = relationship(back_populates="chunks")


class MonthlyReport(Base):
    __tablename__ = "monthly_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    property_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("properties.id"), nullable=False, index=True
    )
    month: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("property_id", "month", "version", name="uq_monthly_pmv"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # search|approve|...
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
