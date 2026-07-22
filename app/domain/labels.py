"""分類値・緊急度などの日本語表示ラベル（唯一の正本）。

画面・PDF・LLM プロンプトのいずれもここを参照する。以前は services と api に別々の
辞書があり「設備不具合／設備異常」のように表記が割れていたため、ドメイン層に一本化した。
ドメインは外部依存ゼロの制約下にあるが、これは素の辞書なので問題ない（import-linter §domain）。
"""

from __future__ import annotations

from app.domain.values import AnalysisStatus, Category, MonthlyStatus, Role, Urgency

CATEGORY_JP: dict[Category, str] = {
    Category.CLEANING: "清掃",
    Category.EQUIPMENT_FAILURE: "設備不具合",
    Category.CLAIM: "苦情・要望",
    Category.OTHER: "その他",
}

URGENCY_JP: dict[Urgency, str] = {
    Urgency.HIGH: "高",
    Urgency.MEDIUM: "中",
    Urgency.LOW: "低",
}

ANALYSIS_STATUS_JP: dict[AnalysisStatus, str] = {
    AnalysisStatus.PROCESSING: "処理中",
    AnalysisStatus.AUTO_CLASSIFIED: "AI分析済",
    AnalysisStatus.NEEDS_REVIEW: "未分類（要確認）",
    AnalysisStatus.HUMAN_VERIFIED: "人間確認済",
    AnalysisStatus.FAILED: "処理失敗",
}

MONTHLY_STATUS_JP: dict[MonthlyStatus, str] = {
    MonthlyStatus.GENERATING: "作成中",
    MonthlyStatus.DRAFT: "ドラフト（編集できます）",
    MonthlyStatus.APPROVED: "承認済み（確定）",
    MonthlyStatus.FAILED: "作成に失敗",
}

ROLE_JP: dict[Role, str] = {
    Role.BRANCH_MANAGER: "支店管理者",
    Role.QA: "本社品質管理部",
}


def _assert_exhaustive() -> None:
    for enum_cls, labels in (
        (Category, CATEGORY_JP),
        (Urgency, URGENCY_JP),
        (AnalysisStatus, ANALYSIS_STATUS_JP),
        (MonthlyStatus, MONTHLY_STATUS_JP),
        (Role, ROLE_JP),
    ):
        missing = set(enum_cls) - set(labels)
        if missing:
            raise RuntimeError(f"{enum_cls.__name__} のラベル未定義: {sorted(missing)}")


_assert_exhaustive()
