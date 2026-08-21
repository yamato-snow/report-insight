"""合成報告書ジェネレータ（デモ＋評価セット共用。1日実装計画 / LLM設計書 §4）。

境界例・悪文・表記ゆれ・プロンプトインジェクション・低確信度サンプルを意図的に含む。
各サンプルは正解ラベル付きで返し、評価ハーネス（P1）が再利用できる。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.domain.values import Urgency
from scripts.templates import TEMPLATES as _TEMPLATES
from scripts.templates import Sample, SampleLabel

__all__ = [
    "BRANCHES",
    "NOTATION_DRIFT",
    "PROPERTIES",
    "USERS",
    "NoiseConfig",
    "Sample",
    "SampleLabel",
    "generate",
]

# 物件は 2 支店に分ける（認可テスト用）。branch 1: 101-103 / branch 2: 201-202
BRANCHES = {1: "東京支店", 2: "大阪支店"}
PROPERTIES = {
    101: (1, "第一グランドビル"),
    102: (1, "サンライズ集合住宅"),
    103: (1, "みどり台レジデンス"),
    201: (2, "なにわタワー"),
    202: (2, "堺筋テラス"),
}
# user 1: 東京支店管理者 / user 2: 品質管理部(QA・全社) / user 3: 大阪支店管理者
USERS = {
    1: (1, "tokyo-mgr@example.com", "branch_manager"),
    2: (None, "qa@example.com", "qa"),
    3: (2, "osaka-mgr@example.com", "branch_manager"),
}


_PROPERTY_IDS = list(PROPERTIES.keys())


# --- ノイズ注入（本番相当の"汚いデータ"を再現。P1 劣化検知の substrate） ----------
#
# 表記ゆれ（漢字→かな）は現場報告の実問題であり、キーワード依存の分類を脆くする。
# 下記マップの「正規形（キーワード）→ ドリフト形」を適用すると分類の手掛かりが外れ、
# 分類精度が決定的に低下する。正規化（app.infra.text.normalize）で逆変換すれば回復する。
# = 劣化検知 → 改善フローの閉ループを、実APIなし・決定的に再現するための素材。
NOTATION_DRIFT: dict[str, str] = {
    "漏水": "ろうすい",
    "水漏れ": "みずもれ",
    "故障": "こしょう",
    "破損": "はそん",
    "異音": "いおん",
    "停止": "ていし",
    "不具合": "ふぐあい",
    "苦情": "くじょう",
    "騒音": "そうおん",
    "清掃": "せいそう",
    "火災": "かさい",
    "ガス": "がす",
    "要望": "ようぼう",
}
# 情報欠損（末尾の具体を落として曖昧化）。低確信度・分類難のサンプルを増やす。
_MISSING_SUFFIX = "（詳細は後日確認）"


@dataclass(frozen=True)
class NoiseConfig:
    """汚いデータの割合制御。各値は 0.0〜1.0 の適用率（サンプル単位で独立判定）。"""

    notation: float = 0.0  # 表記ゆれ（漢字→かな）を適用する割合
    missing: float = 0.0  # 情報欠損（曖昧化）を適用する割合
    seed: int = 1234  # ノイズ適用判定の乱数シード（再現性のため generate の seed と分離）

    @classmethod
    def clean(cls) -> NoiseConfig:
        return cls()


def _apply_notation_drift(text: str) -> tuple[str, bool]:
    """既知キーワードを かな表記へ置換する。1件でも置換したら True を返す。"""
    drifted = text
    for canonical, variant in NOTATION_DRIFT.items():
        drifted = drifted.replace(canonical, variant)
    return drifted, drifted != text


def _apply_missing_info(text: str) -> str:
    """末尾の一文（具体的な状況説明）を落として曖昧化する。"""
    # 句点で分割し、最後の実質文を欠落させる（1文しかなければ丸ごと曖昧化）。
    parts = [p for p in text.split("。") if p]
    if len(parts) >= 2:
        return "。".join(parts[:-1]) + "。" + _MISSING_SUFFIX
    return "状況不明。" + _MISSING_SUFFIX


# 1日あたりの報告件数。100件投入で約2週間分の分布になる。
_REPORTS_PER_DAY = 7


def _time_of_day(sample: Sample, rng: random.Random) -> dict[str, int]:
    """報告時刻を事象の性質に合わせて割り当てる。

    定常業務（清掃・点検）は日中に限る。緊急案件だけが夜間・早朝に発生しうる、
    という現場の実態に寄せる（深夜3時の定期清掃報告のような不自然さを避ける）。
    """
    if sample.label.urgency is Urgency.HIGH:
        # 緊急は終日発生しうるが、それでも日中が多い。
        hour = rng.choice([1, 5, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 19, 22])
    else:
        hour = rng.randrange(9, 18)  # 定常業務は 9:00〜17:59
    return {"hours": hour, "minutes": rng.choice([0, 10, 15, 20, 30, 40, 45, 50])}


def generate(
    count: int, *, seed: int = 42, noise: NoiseConfig | None = None
) -> list[tuple[dict[str, object], Sample]]:
    """count 件の報告書ペイロード(JSON化可能)と正解ラベルを返す。

    テンプレートを循環させつつ物件・日時を割り当てる。全テンプレートを最低1回含める。
    noise を渡すと、指定割合で表記ゆれ・情報欠損を注入する（正解ラベルは不変。
    "本番の汚いデータでは精度が落ちる" を再現し、劣化検知の評価に使う）。
    """
    rng = random.Random(seed)  # noqa: S311 — デモデータ生成用（暗号用途ではない）
    noise_rng = random.Random(noise.seed if noise else 0)  # noqa: S311 — 同上
    base = datetime(2026, 6, 1, tzinfo=UTC)
    out: list[tuple[dict[str, object], Sample]] = []
    for i in range(count):
        sample = _TEMPLATES[i % len(_TEMPLATES)]
        property_id = _PROPERTY_IDS[rng.randrange(len(_PROPERTY_IDS))]
        reported_at = base + timedelta(days=i // _REPORTS_PER_DAY, **_time_of_day(sample, rng))
        source_key = f"reports/2026-06/{i:04d}.json"

        raw_text = sample.raw_text
        extra_tags: list[str] = []
        if noise is not None:
            # サンプル単位で独立に適用可否を判定（割合は近似的に保たれる）。
            if noise_rng.random() < noise.notation:
                raw_text, changed = _apply_notation_drift(raw_text)
                if changed:
                    extra_tags.append("drift")
            if noise_rng.random() < noise.missing:
                raw_text = _apply_missing_info(raw_text)
                extra_tags.append("missing")
        # ラベルは不変。タグにノイズ種別を足して診断に使えるようにする。
        emitted = (
            sample
            if not extra_tags
            else Sample(
                raw_text=raw_text,
                reporter_role=sample.reporter_role,
                label=sample.label,
                tags=[*sample.tags, *extra_tags],
                # ノイズ適用後の本文には正解要約が対応しない（要約も劣化する）。
                summary="",
            )
        )

        payload: dict[str, object] = {
            "source_key": source_key,
            "property_id": property_id,
            "reported_at": reported_at.isoformat(),
            "reporter_role": sample.reporter_role,
            "raw_text": raw_text,
            "photo_meta": {},
        }
        out.append((payload, emitted))
    return out
