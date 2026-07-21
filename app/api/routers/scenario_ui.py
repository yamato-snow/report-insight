"""受入シナリオを画面から選んで実行する検査用UI（dev 限定）。

CLI（make scenario）と同じランナー（tests.scenarios.runner）を呼ぶため、画面とCIで
判定がずれない。これは製品機能ではなく受入テストの治具であり、本番（env=prod）では
main 側でマウントしない。tests パッケージへの依存は本番イメージに影響させないよう、
モジュール読み込み時ではなく各エンドポイント内で遅延 import する。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["scenario-ui"])

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/scenarios", response_class=HTMLResponse)
async def scenarios_home(request: Request) -> HTMLResponse:
    """シナリオ一覧（名前・対応要件・入力件数）。"""
    from tests.scenarios.runner import list_scenarios, run_scenario

    specs = []
    for path in list_scenarios():
        result = await run_scenario(path)
        specs.append(
            {
                "stem": path.stem,
                "name": result.name,
                "requirements": result.requirements,
                "input_count": len(result.inputs),
            }
        )
    return _TEMPLATES.TemplateResponse(request, "scenarios.html", {"specs": specs})


@router.get("/scenarios/{stem}/run", response_class=HTMLResponse)
async def scenario_run(request: Request, stem: str) -> HTMLResponse:
    """1シナリオを実行し、入力ごと・全体の OK/NG を返す（HTMX 部分テンプレート）。"""
    from tests.scenarios.runner import list_scenarios, run_scenario

    match = [p for p in list_scenarios() if p.stem == stem]
    if not match:
        return HTMLResponse(
            '<p class="ng-mark">該当するシナリオがありません。</p>', status_code=404
        )
    result = await run_scenario(match[0])
    return _TEMPLATES.TemplateResponse(request, "_scenario_result.html", {"result": result})
