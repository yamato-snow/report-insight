"""FakeLLMClient — 決定的スタブ（unit/integration・デモ既定。LLM設計書 §2 / 規約 §6）。

実APIを呼ばず、キーワードで分類する。非決定性をテストに持ち込まないための実装。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from app.domain.entities import (
    ClassificationEnvelope,
    ClassificationResult,
    LLMCallMeta,
    MonthlyNarration,
    MonthlyStats,
    SearchHit,
)
from app.domain.labels import CATEGORY_JP
from app.domain.values import Category, Urgency
from app.infra.llm import summaries
from app.infra.llm.prompts import load_prompt

_HIGH_URGENCY_KEYWORDS = (
    "漏水",
    "水漏れ",
    "火災",
    "煙",
    "停電",
    "閉じ込め",
    "けが",
    "負傷",
    "防犯",
    "侵入",
    "ガス",
)
_EQUIPMENT_KEYWORDS = (
    "故障",
    "破損",
    "漏水",
    "水漏れ",
    "異音",
    "停止",
    "不具合",
    "設備",
    # 現場報告で頻出する不具合の言い回し（キーワードそのものは含まれないが設備事象）。
    "閉じ込め",
    "発煙",
    "焦げ臭",
    "ぐらつき",
    "緩み",
    "劣化",
    "ずれ",
    "点滅",
    "浮き",
    "反応しない",
    "動かない",
    "開かない",
    "閉まりきらない",
    "閉まりにくい",
    "上がらず",
    "止まらない",
    "起動しない",
    "開きっぱなし",
    "エラー",
)
# 「共用部・設備ともに異常なし」のような定型点検文で設備誤判定を避けるための打ち消し表現。
_NO_ISSUE_MARKERS = ("異常はありません", "異常なし", "指摘事項なし")
_CLEANING_KEYWORDS = ("清掃", "ゴミ", "汚れ", "美観", "落ち葉", "清掃中")
_CLAIM_KEYWORDS = ("苦情", "クレーム", "要望", "騒音", "トラブル", "不満")
_LOW_CONFIDENCE_MARKERS = ("曖昧", "不明", "判読不能", "？？")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class FakeLLMClient:
    """LLMClient の決定的実装。"""

    def __init__(self, prompt_name: str = "classify_v1") -> None:
        self._prompt = load_prompt(prompt_name)
        self._prompt_version = str(self._prompt.get("version", prompt_name))
        self._model_id = "fake-classify"

    async def classify_report(self, masked_text: str) -> ClassificationEnvelope:
        category = self._classify_category(masked_text)
        urgency = self._classify_urgency(masked_text)
        confidence = self._confidence(masked_text)
        action_required = urgency is Urgency.HIGH or category is Category.EQUIPMENT_FAILURE

        # 合成報告書には正解要約を持たせている（demo の見栄え。summaries 参照）。
        # 一致しない入力（表記ゆれ・情報欠損・任意入力）は従来どおり切り詰めへ落ちる。
        summary = summaries.lookup(masked_text)
        if summary is None:
            summary = masked_text.strip().replace("\n", " ")
            if len(summary) > 80:
                summary = summary[:78] + "…"

        result = ClassificationResult(
            category=category,
            urgency=urgency,
            action_required=action_required,
            normalized_summary=summary or "（本文なし）",
            confidence=confidence,
        )
        meta = LLMCallMeta(
            model_id=self._model_id,
            prompt_version=self._prompt_version,
            input_tokens=_estimate_tokens(masked_text),
            output_tokens=16,
        )
        return ClassificationEnvelope(result=result, meta=meta)

    def stream_answer(self, query: str, sources: Sequence[SearchHit]) -> _FakeAnswerStream:
        return _FakeAnswerStream(query, sources)

    async def narrate_monthly(self, *, property_name: str, stats: MonthlyStats) -> MonthlyNarration:
        # 決定的な所見（実APIを呼ばない）。数値は stats のみを参照する。
        top_category = max(stats.by_category.items(), key=lambda kv: kv[1], default=None)
        if stats.total == 0:
            body = f"{property_name}では対象月の報告はありませんでした。"
        else:
            lead = f"{property_name}では当月{stats.total}件の報告がありました。"
            if top_category is not None and top_category[1] > 0:
                cat_label = CATEGORY_JP[top_category[0]]
                lead += f"最多の分類は「{cat_label}」で{top_category[1]}件でした。"
            if stats.action_required > 0:
                lead += f"うち{stats.action_required}件が要対応であり、優先的な確認が必要です。"
            body = lead
        meta = LLMCallMeta(
            model_id="fake-generate",
            prompt_version=str(load_prompt("monthly_v1").get("version", "monthly_v1")),
            input_tokens=_estimate_tokens(property_name) + stats.total,
            output_tokens=_estimate_tokens(body),
        )
        return MonthlyNarration(body=body, meta=meta)

    @staticmethod
    def _classify_category(text: str) -> Category:
        # 「共用部・設備ともに異常なし」のような点検報告は不具合ではない。
        # ただし打ち消すのは設備判定だけで、清掃・苦情の判定はそのまま活かす
        # （例「清掃を実施。異常はありません」は cleaning のまま）。
        no_issue = any(m in text for m in _NO_ISSUE_MARKERS)
        # 「清掃中に設備破損」は equipment_failure を優先（LLM設計書 §2 の境界例）
        if not no_issue and any(k in text for k in _EQUIPMENT_KEYWORDS):
            return Category.EQUIPMENT_FAILURE
        if any(k in text for k in _CLAIM_KEYWORDS):
            return Category.CLAIM
        if any(k in text for k in _CLEANING_KEYWORDS):
            return Category.CLEANING
        return Category.OTHER

    @staticmethod
    def _classify_urgency(text: str) -> Urgency:
        if any(k in text for k in _HIGH_URGENCY_KEYWORDS):
            return Urgency.HIGH
        # 「異常なし」の点検報告は設備語を含んでも緊急度を上げない（category 判定と同じ）。
        if any(m in text for m in _NO_ISSUE_MARKERS):
            return Urgency.LOW
        if any(k in text for k in _EQUIPMENT_KEYWORDS):
            return Urgency.MEDIUM
        return Urgency.LOW

    @staticmethod
    def _confidence(text: str) -> float:
        if any(m in text for m in _LOW_CONFIDENCE_MARKERS) or len(text.strip()) < 8:
            return 0.60
        return 0.95


class _FakeAnswerStream:
    """決定的な回答ストリーム。実在する source の先頭を引用する。"""

    def __init__(self, query: str, sources: Sequence[SearchHit]) -> None:
        self._query = query
        self._sources = list(sources)
        top = self._sources[0]
        self._tokens: list[str] = [
            "検索結果によると、",
            f"{top.summary} ",
            f"[report:{top.report_id}]",
            " が該当します。",
        ]
        self._usage = LLMCallMeta(
            model_id="fake-generate",
            prompt_version=str(load_prompt("answer_v1").get("version", "answer_v1")),
            input_tokens=_estimate_tokens(query + "".join(s.content for s in sources)),
            output_tokens=_estimate_tokens("".join(self._tokens)),
        )

    def __aiter__(self) -> AsyncIterator[str]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[str]:
        for token in self._tokens:
            yield token

    @property
    def usage(self) -> LLMCallMeta:
        return self._usage
