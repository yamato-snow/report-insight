"""全シナリオを pytest としても実行する（CI の unit ジョブが拾う）。

CLI（run.py）とロジックを共有し、シナリオ1本＝テスト1件として OK/NG を判定する。
"""

from __future__ import annotations

import pytest
from tests.scenarios.runner import list_scenarios, run_scenario


@pytest.mark.parametrize("path", list_scenarios(), ids=lambda p: p.stem)
async def test_scenario(path) -> None:  # type: ignore[no-untyped-def]
    result = await run_scenario(path)
    assert result.ok, "NG: " + "; ".join(
        f"{c.field} 期待={c.expected!r} 実際={c.actual!r}" for c in result.failed_checks
    )
