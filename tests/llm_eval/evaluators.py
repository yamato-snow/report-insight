"""評価ロジック（ポート注入で純粋化）。実API/Fake いずれのクライアントでも動く。

- eval_classification: マスキング→分類し、正解ラベルと突き合わせる（DB不要）。
- eval_search: ingest 済みコーパスに対し検索し recall@k と引用実在率を測る（DB必要）。
- eval_faithfulness: 検索→回答→judge で忠実性を採点する（実APIのjudge関数を注入）。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence

from app.domain.entities import SearchFilters, User
from app.domain.values import Role, Urgency
from app.services.ports import EmbeddingClient, LLMClient, PIIMaskerPort, SearchRepository
from tests.llm_eval.datasets import ClassificationCase, FaithfulnessCase, SearchCase
from tests.llm_eval.metrics import (
    SEARCH_TOP_K,
    ClassificationReport,
    FaithfulnessReport,
    SearchReport,
)

_CITATION_RE = re.compile(r"\[report:(\d+)\]")

# judge: (question, answer, grounded_fact) -> 1..5 のスコア（実APIで実装して注入）
JudgeFn = Callable[[str, str, str], Awaitable[float | None]]


async def eval_classification(
    llm: LLMClient, masker: PIIMaskerPort, cases: Sequence[ClassificationCase]
) -> ClassificationReport:
    correct = 0
    high_total = 0
    high_hit = 0
    inj_total = 0
    inj_correct = 0
    for case in cases:
        masked = await masker.mask(case.raw_text)
        envelope = await llm.classify_report(masked.masked_text)
        predicted = envelope.result
        is_correct = predicted.category.value == case.expected_category
        if is_correct:
            correct += 1
        if case.expected_urgency == Urgency.HIGH.value:
            high_total += 1
            if predicted.urgency is Urgency.HIGH:
                high_hit += 1
        if "injection" in case.tags:
            inj_total += 1
            if is_correct:
                inj_correct += 1
    total = len(cases)
    return ClassificationReport(
        total=total,
        accuracy=correct / total if total else 0.0,
        urgency_high_recall=high_hit / high_total if high_total else 1.0,
        injection_total=inj_total,
        injection_correct=inj_correct,
    )


async def eval_search(
    *,
    embedder: EmbeddingClient,
    repository: SearchRepository,
    doc_id_to_report_id: dict[str, int],
    cases: Sequence[SearchCase],
    user: User | None = None,
) -> SearchReport:
    """各質問で当該文書が top-k に入るか（recall@k）と引用実在率を測る。"""
    qa = user or User(id=2, email="qa@e.com", role=Role.QA, branch_id=None)
    permitted = await repository.permitted_property_ids(qa)
    hits_in_topk = 0
    all_cited: set[int] = set()
    for case in cases:
        expected_id = doc_id_to_report_id[case.doc_id]
        query_vec = await embedder.embed_query(case.question)
        results = await repository.hybrid_search(
            query_vec, SearchFilters(), permitted, SEARCH_TOP_K
        )
        top_ids = [h.report_id for h in results]
        if expected_id in top_ids:
            hits_in_topk += 1
        all_cited.update(top_ids)
    existing = await repository.existing_report_ids(list(all_cited), permitted)
    citation_rate = len(all_cited & existing) / len(all_cited) if all_cited else 1.0
    total = len(cases)
    return SearchReport(
        total=total,
        recall_at_k=hits_in_topk / total if total else 0.0,
        citation_existence_rate=citation_rate,
    )


async def eval_faithfulness(
    *,
    llm: LLMClient,
    embedder: EmbeddingClient,
    repository: SearchRepository,
    judge: JudgeFn,
    cases: Sequence[FaithfulnessCase],
    user: User | None = None,
) -> FaithfulnessReport:
    """検索→回答生成→judge で忠実性を採点する（1..5 平均）。"""
    qa = user or User(id=2, email="qa@e.com", role=Role.QA, branch_id=None)
    permitted = await repository.permitted_property_ids(qa)
    scores: list[float] = []
    for case in cases:
        query_vec = await embedder.embed_query(case.question)
        sources = await repository.hybrid_search(
            query_vec, SearchFilters(), permitted, SEARCH_TOP_K
        )
        parts: list[str] = []
        stream = llm.stream_answer(case.question, sources)
        async for token in stream:
            parts.append(token)
        answer = "".join(parts)
        score = await judge(case.question, answer, case.grounded_fact)
        if score is None:  # judge がパースできなかったケースは平均から除外（0.0 汚染を防ぐ）
            continue
        scores.append(score)
    valid = len(scores)
    return FaithfulnessReport(
        total=valid,
        mean_score=sum(scores) / valid if valid else 0.0,
    )


def parse_citations(text: str) -> set[int]:
    return {int(m) for m in _CITATION_RE.findall(text)}
