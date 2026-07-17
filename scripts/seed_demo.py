"""make demo: 基礎データ投入→合成報告書をS3へ→worker処理を待機→件数レポート。

完了条件（1日実装計画）: docker compose up → make demo で S3→SQS→worker→DB が自動で通る。
"""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import get_settings
from app.core.di import build_container
from app.core.logging import configure_logging, get_logger
from app.infra.db import models
from scripts.synth import BRANCHES, PROPERTIES, USERS, generate

logger = get_logger("seed_demo")


async def _ensure_base_data(container) -> None:  # type: ignore[no-untyped-def]
    async with container.session_factory() as session:
        await session.execute(
            pg_insert(models.Branch)
            .values([{"id": bid, "name": name} for bid, name in BRANCHES.items()])
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await session.execute(
            pg_insert(models.Property)
            .values(
                [
                    {"id": pid, "branch_id": bid, "name": name}
                    for pid, (bid, name) in PROPERTIES.items()
                ]
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await session.execute(
            pg_insert(models.User)
            .values(
                [
                    {"id": uid, "branch_id": bid, "email": email, "role": role}
                    for uid, (bid, email, role) in USERS.items()
                ]
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await session.commit()


async def _count_reports(container) -> int:  # type: ignore[no-untyped-def]
    async with container.session_factory() as session:
        result = await session.execute(select(func.count()).select_from(models.Report))
        return int(result.scalar_one())


async def _summary(container) -> dict[str, dict[str, int]]:  # type: ignore[no-untyped-def]
    async with container.session_factory() as session:
        by_cat = (
            await session.execute(
                select(models.ReportAnalysis.category, func.count()).group_by(
                    models.ReportAnalysis.category
                )
            )
        ).all()
        by_status = (
            await session.execute(
                select(models.ReportAnalysis.status, func.count()).group_by(
                    models.ReportAnalysis.status
                )
            )
        ).all()
    return {
        "by_category": {c: n for c, n in by_cat},
        "by_status": {s: n for s, n in by_status},
    }


async def run(count: int, timeout_s: int) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    container = build_container(settings)
    try:
        await _ensure_base_data(container)
        baseline = await _count_reports(container)

        samples = generate(count)
        for payload, _sample in samples:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            await container.storage.put_object(str(payload["source_key"]), body)
        logger.info("seed_demo.uploaded", count=len(samples))

        target = baseline + count
        elapsed = 0
        while elapsed < timeout_s:
            current = await _count_reports(container)
            if current >= target:
                break
            await asyncio.sleep(2)
            elapsed += 2

        current = await _count_reports(container)
        summary = await _summary(container)
        logger.info(
            "seed_demo.done",
            uploaded=count,
            reports_in_db=current,
            processed=current - baseline,
            **summary,
        )
        print(  # noqa: T201 — CLI 出力
            f"\n=== demo 完了 ===\n"
            f"投入: {count} 件 / DB: {current} 件（処理: {current - baseline} 件）\n"
            f"分類別: {summary['by_category']}\n"
            f"状態別: {summary['by_status']}\n"
        )
    finally:
        await container.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="合成報告書のデモ投入")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=180, help="処理待機の上限秒")
    args = parser.parse_args()
    asyncio.run(run(args.count, args.timeout))


if __name__ == "__main__":
    main()
