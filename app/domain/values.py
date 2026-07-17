"""ドメインの値オブジェクト・Enum・定数（コーディング規約 §2: 分類値の直書き禁止）。"""

from __future__ import annotations

from enum import StrEnum


class Category(StrEnum):
    """事象分類（DB設計書 04: report_analyses.category）。"""

    CLEANING = "cleaning"
    EQUIPMENT_FAILURE = "equipment_failure"
    CLAIM = "claim"
    OTHER = "other"


class Urgency(StrEnum):
    """緊急度。high は即時通知対象（基本設計 §2.1）。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AnalysisStatus(StrEnum):
    """構造化結果のステータス（DB設計書 04: report_analyses.status）。"""

    PROCESSING = "processing"
    AUTO_CLASSIFIED = "auto_classified"
    NEEDS_REVIEW = "needs_review"
    HUMAN_VERIFIED = "human_verified"
    FAILED = "failed"


class MonthlyStatus(StrEnum):
    """月次報告書のステータス（DB設計書 04: monthly_reports.status）。"""

    GENERATING = "generating"
    DRAFT = "draft"
    APPROVED = "approved"
    FAILED = "failed"


class Role(StrEnum):
    """利用者ロール（基本設計 §3 認可）。qa は全支店アクセス可。"""

    BRANCH_MANAGER = "branch_manager"
    QA = "qa"


class AuditAction(StrEnum):
    """監査ログの操作種別（DB設計書 04: audit_logs.action / 09 §6）。"""

    SEARCH = "search"
    APPROVE_MONTHLY = "approve_monthly"
    OVERRIDE_ANALYSIS = "override_analysis"


# --- 定数 ---------------------------------------------------------------

# confidence 閾値の既定値。実運用値は env(CONFIDENCE_THRESHOLD) で上書きし、
# 評価セットで較正する（LLM設計書 §2）。
DEFAULT_CONFIDENCE_THRESHOLD = 0.85

# RAG 検索の上位k件（基本設計 §2.2 / DB設計書 §2）。
SEARCH_TOP_K = 8

# 長文チャンク分割の閾値（DB設計書 §2: >1,500字のみ分割）。
LONG_TEXT_CHARS = 1500
