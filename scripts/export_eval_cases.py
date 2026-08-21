"""人間確認済みの分類結果を評価セットへ還流する（LLM設計書 §4 の「還流」の出口側）。

未分類キューで人が確定した分類（status=human_verified）は「人間が保証した正解ラベル付きの
本番実例」であり、合成テンプレより代表性が高い。これを human_cases.json へ蓄積し、
評価ハーネス（tests.llm_eval.run）が合成100件に加えて採点対象にする。

表記ゆれの還流（export_corrections.py → 正規化辞書）と対になる、評価セット側の還流。

使い方:
    python -m scripts.export_eval_cases            # DBから抽出して還流
    python -m scripts.export_eval_cases --dry-run  # 件数確認のみ
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.di import build_container
from app.core.logging import configure_logging, get_logger
from app.infra.db import models

logger = get_logger("export_eval_cases")

_DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tests/llm_eval/human_cases.json"


async def _fetch_verified_cases(container) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """human_verified の報告書＋確定ラベルを評価ケース形式で返す。"""
    async with container.session_factory() as session:
        rows = await session.execute(
            select(
                models.Report.source_key,
                models.Report.raw_text,
                models.Report.reporter_role,
                models.ReportAnalysis.category,
                models.ReportAnalysis.urgency,
                models.ReportAnalysis.action_required,
            )
            .join(models.ReportAnalysis, models.ReportAnalysis.report_id == models.Report.id)
            .where(models.ReportAnalysis.status == "human_verified")
            .order_by(models.Report.id)
        )
    return [
        {
            "source_key": source_key,
            "raw_text": raw_text,
            "reporter_role": reporter_role,
            "expected_category": category,
            "expected_urgency": urgency,
            "expected_action_required": action_required,
            "tags": ["human_verified"],
        }
        for source_key, raw_text, reporter_role, category, urgency, action_required in rows.all()
    ]


def merge(out_path: Path, incoming: list[dict[str, Any]]) -> tuple[int, int]:
    """incoming を評価セットへマージ。(追加数, 総数) を返す。source_key で重複排除・後勝ち。

    後勝ちにするのは、同じ報告書が再修正された場合に最新の人間判断を正とするため。
    """
    existing: list[dict[str, Any]] = []
    if out_path.exists():
        data = json.loads(out_path.read_text(encoding="utf-8"))
        existing = list(data.get("cases", []))
    by_key: dict[str, dict[str, Any]] = {str(c["source_key"]): c for c in existing}
    added = 0
    for case in incoming:
        if str(case["source_key"]) not in by_key:
            added += 1
        by_key[str(case["source_key"])] = case
    cases = sorted(by_key.values(), key=lambda c: str(c["source_key"]))
    doc = {
        "_comment": (
            "人間確認済み（human_verified）の分類を評価セットへ還流したもの。"
            "scripts/export_eval_cases.py が生成し、tests.llm_eval が合成ケースに追加で採点する。"
            "手編集しない（再実行で上書きされる）。"
        ),
        "cases": cases,
    }
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return added, len(cases)


async def run(out: Path, dry_run: bool) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    container = build_container(settings)
    try:
        incoming = await _fetch_verified_cases(container)
    finally:
        await container.aclose()
    if dry_run:
        print(f"human_verified: {len(incoming)} 件（--dry-run のため書き込みなし）")  # noqa: T201
        return
    added, total = merge(out, incoming)
    logger.info("export_eval_cases.done", added=added, total=total)
    print(f"還流: +{added}件 追加（評価セット 計{total}件） -> {out}")  # noqa: T201


def main() -> int:
    parser = argparse.ArgumentParser(description="人間確認済み分類を評価セットへ還流する")
    parser.add_argument("--out", default=str(_DEFAULT_OUT), help="出力先JSON")
    parser.add_argument("--dry-run", action="store_true", help="件数確認のみ")
    args = parser.parse_args()
    asyncio.run(run(Path(args.out), args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
