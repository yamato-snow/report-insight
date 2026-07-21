"""AnthropicLLMClient — 実API実装（評価ハーネス・本番用。LLM設計書 §1-2）。

- 分類は Structured Output（tools）で JSON を強制（自由文パースしない）
- 原文は <report> タグで囲みデータと指示を分離（インジェクション対策 §7）
- 静的な system プロンプトは prompt cache 対象にして入力コストを削減（§5）
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from anthropic import (
    APIConnectionError,
    APIStatusError,
    AsyncAnthropic,
    InternalServerError,
    RateLimitError,
)

from app.domain.entities import (
    ClassificationEnvelope,
    ClassificationResult,
    LLMCallMeta,
    MonthlyNarration,
    MonthlyStats,
    SearchHit,
)
from app.domain.errors import RetryableError
from app.domain.labels import CATEGORY_JP, URGENCY_JP
from app.infra.llm.prompts import load_prompt


def _to_retryable(exc: Exception) -> Exception:
    """一時障害はリトライ可能例外へ変換（規約 §4: worker が SQS 再配信に委ねる）。"""
    if isinstance(exc, (RateLimitError, APIConnectionError, InternalServerError)):
        return RetryableError(str(exc))
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:
        return RetryableError(str(exc))
    return exc


class AnthropicLLMClient:
    """LLMClient の Anthropic 実装。"""

    def __init__(
        self,
        *,
        api_key: str,
        model_classify: str,
        model_generate: str,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model_classify = model_classify
        self._model_generate = model_generate
        self._classify_prompt = load_prompt("classify_v1")
        self._answer_prompt = load_prompt("answer_v1")
        self._monthly_prompt = load_prompt("monthly_v1")

    async def classify_report(self, masked_text: str) -> ClassificationEnvelope:
        tool = self._classify_prompt["tool"]
        system = [
            {
                "type": "text",
                "text": self._classify_prompt["system"],
                "cache_control": {"type": "ephemeral"},  # 静的部分をキャッシュ（§5）
            }
        ]
        try:
            # infra境界: SDKの厳格な型に対し実行時は正しい形（規約 §2）
            response = await self._client.messages.create(  # type: ignore[call-overload]
                model=self._model_classify,
                max_tokens=1024,
                system=system,
                tools=[
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                        "input_schema": tool["input_schema"],
                    }
                ],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[
                    {
                        "role": "user",
                        "content": f"<report>\n{masked_text}\n</report>",
                    }
                ],
            )
        except Exception as exc:
            raise _to_retryable(exc) from exc

        payload = _extract_tool_input(response, tool["name"])
        result = ClassificationResult.model_validate(payload)
        meta = LLMCallMeta(
            model_id=self._model_classify,
            prompt_version=str(self._classify_prompt["version"]),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return ClassificationEnvelope(result=result, meta=meta)

    async def narrate_monthly(self, *, property_name: str, stats: MonthlyStats) -> MonthlyNarration:
        try:
            response = await self._client.messages.create(
                model=self._model_generate,
                max_tokens=512,
                system=[
                    {
                        "type": "text",
                        "text": self._monthly_prompt["system"],
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": f"<stats>\n{_render_stats(property_name, stats)}\n</stats>",
                    }
                ],
            )
        except Exception as exc:
            raise _to_retryable(exc) from exc

        body = "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", None) == "text"
        ).strip()
        meta = LLMCallMeta(
            model_id=self._model_generate,
            prompt_version=str(self._monthly_prompt["version"]),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return MonthlyNarration(body=body, meta=meta)

    def stream_answer(self, query: str, sources: Sequence[SearchHit]) -> _AnthropicAnswerStream:
        return _AnthropicAnswerStream(
            client=self._client,
            model=self._model_generate,
            system=self._answer_prompt["system"],
            prompt_version=str(self._answer_prompt["version"]),
            query=query,
            sources=sources,
        )


def _extract_tool_input(response: Any, tool_name: str) -> dict[str, Any]:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return dict(block.input)
    raise RetryableError("LLM がツール呼び出しを返しませんでした")


def _render_stats(property_name: str, stats: MonthlyStats) -> str:
    """確定集計を LLM 入力用のプレーンテキストへ整形する（数値はここが唯一の出所）。"""
    lines = [
        f"物件: {property_name}",
        f"対象月: {stats.month.year}年{stats.month.month}月",
        f"総報告件数: {stats.total}",
        f"要対応件数: {stats.action_required}",
        "分類別:",
    ]
    # 所見の散文に英字の enum 値が漏れないよう、LLM には日本語ラベルで渡す
    lines += [f"  - {CATEGORY_JP[cat]}: {n}" for cat, n in stats.by_category.items()]
    lines.append("緊急度別:")
    lines += [f"  - {URGENCY_JP[urg]}: {n}" for urg, n in stats.by_urgency.items()]
    return "\n".join(lines)


def _render_sources(sources: Sequence[SearchHit]) -> str:
    lines = ["<sources>"]
    for hit in sources:
        lines.append(
            f'  <report id="{hit.report_id}" date="{hit.reported_at.date().isoformat()}">'
            f"{hit.content}</report>"
        )
    lines.append("</sources>")
    return "\n".join(lines)


class _AnthropicAnswerStream:
    """回答ストリーム。usage は消費完了後に確定する。"""

    def __init__(
        self,
        *,
        client: AsyncAnthropic,
        model: str,
        system: str,
        prompt_version: str,
        query: str,
        sources: Sequence[SearchHit],
    ) -> None:
        self._client = client
        self._model = model
        self._system = system
        self._prompt_version = prompt_version
        self._query = query
        self._sources = sources
        self._usage = LLMCallMeta(
            model_id=model, prompt_version=prompt_version, input_tokens=0, output_tokens=0
        )

    def __aiter__(self) -> AsyncIterator[str]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[str]:
        user_content = f"{_render_sources(self._sources)}\n\n質問: {self._query}"
        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=1024,
                system=self._system,
                messages=[{"role": "user", "content": user_content}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
        except Exception as exc:
            raise _to_retryable(exc) from exc
        self._usage = LLMCallMeta(
            model_id=self._model,
            prompt_version=self._prompt_version,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
        )

    @property
    def usage(self) -> LLMCallMeta:
        return self._usage
