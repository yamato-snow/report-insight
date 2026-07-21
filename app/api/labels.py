"""テンプレートへ渡す表示ラベル。実体はドメイン層の唯一の正本（app.domain.labels）。

以前はここに独自の辞書があり月次側と表記が割れていたため、ドメインへ委譲するだけにした。
"""

from __future__ import annotations

from app.domain.labels import (
    ANALYSIS_STATUS_JP,
    CATEGORY_JP,
    MONTHLY_STATUS_JP,
    ROLE_JP,
    URGENCY_JP,
)


def template_context() -> dict[str, object]:
    """全テンプレートに渡す共通のラベル辞書。"""
    return {
        "category_labels": CATEGORY_JP,
        "urgency_labels": URGENCY_JP,
        "status_labels": ANALYSIS_STATUS_JP,
        "monthly_status_labels": MONTHLY_STATUS_JP,
        "role_labels": ROLE_JP,
    }
