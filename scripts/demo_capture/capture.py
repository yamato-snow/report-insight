"""デモ素材の撮影スクリプト（Playwright・プロジェクト依存には含めない）。

前提: スタックが起動しシード済みであること（README.md 参照）。
実行:  uv run --with playwright python scripts/demo_capture/capture.py --all
       uv run --with playwright python scripts/demo_capture/capture.py --scene search_stream

出力: scripts/demo_capture/out/shots/*.png（スクリーンショット）
      scripts/demo_capture/out/video/*.webm（無音の操作キャプチャ。GIF/mp4 化は convert.sh）
ビューポートのみを記録するため、URL バー（?uid=）は素材に写らない。
"""

from __future__ import annotations

import argparse
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

BASE = "http://localhost:8000"
WEBHOOK = "http://localhost:9000"
OUT = Path(__file__).parent / "out"
SHOTS = OUT / "shots"
VIDEO = OUT / "video"

VIEWPORT = {"width": 1280, "height": 800}
SLOW_MO_MS = 300  # 人の目で追える操作速度（GIF 用）
TYPE_DELAY_MS = 60


def _shot(page: Page, name: str) -> None:
    page.screenshot(path=str(SHOTS / f"{name}.png"))


def _wait_reports_table(page: Page) -> None:
    """admin 一覧の HTMX 初回ロード完了（テーブルか空状態のどちらか）を待つ。"""
    page.wait_for_selector("#reports table, #reports .empty-state", timeout=15_000)


def _substantive_row(rows: Locator) -> Locator:
    """未分類キューから、内容の詰まった行を1つ選ぶ。

    キューには「なんか変」のような情報欠損サンプルが混ざる。これらは仕様どおりの
    低確信度サンプルだが、素材としては人が直す判断材料が無く弱い。
    要約セルが最も長い行＝具体が書かれている報告を選ぶ。
    """
    best_index, best_len = 0, -1
    for i in range(rows.count()):
        summary = rows.nth(i).locator("td").last.inner_text().strip()
        if len(summary) > best_len:
            best_index, best_len = i, len(summary)
    return rows.nth(best_index)


def _run_search(page: Page, query: str, done_selector: str) -> None:
    page.fill("#q", "")
    page.type("#q", query, delay=TYPE_DELAY_MS)
    page.click("#go")
    # SSE 完了（done イベントで #meta が埋まる／no_results で .empty が出る）を待つ
    page.wait_for_selector(done_selector, timeout=60_000)


def scene_home(page: Page) -> None:
    """トップページ（3課題カード）。"""
    page.goto(f"{BASE}/?uid=1")
    page.wait_for_selector(".problem-cards")
    _shot(page, "01_home")


def scene_search_stream(page: Page) -> None:
    """検索: SSE ストリーミング + 引用バッジ + 初回表示ms（ヒーロー素材）。"""
    page.goto(f"{BASE}/search?uid=1")
    _run_search(page, "水漏れの対応事例", "#meta span")
    page.locator("#answerCard").scroll_into_view_if_needed()
    time.sleep(0.5)
    _shot(page, "02_search_answer")


def scene_search_noresult(page: Page) -> None:
    """検索: 無関係クエリ → 推測で答えず「該当事例なし」（引用ゼロ）。

    実APIではベクトル近傍が常に返るため no_results イベントではなく、
    LLM が引用なしで「該当事例なし」と答える経路になる（どちらも捏造しない設計の証拠）。
    """
    page.goto(f"{BASE}/search?uid=1")
    _run_search(page, "宇宙ステーションの月面基地", "#meta span")
    page.locator("#answerCard").scroll_into_view_if_needed()
    time.sleep(0.5)
    _shot(page, "03_search_noresult")


def scene_auth_switch(page: Page) -> None:
    """認可: 利用者切替で見える範囲（物件・スコープ表示）が変わる。"""
    page.goto(f"{BASE}/admin?uid=1")
    _wait_reports_table(page)
    _shot(page, "04_admin_tokyo")
    for uid, name in ((3, "osaka"), (2, "qa")):
        page.select_option(".whoami select", str(uid))
        page.wait_for_url(f"**/admin?uid={uid}")
        _wait_reports_table(page)
        time.sleep(1.0)  # 切替結果を目視できる長さだけ映像に残す
        _shot(page, f"04_admin_{name}")


def scene_review_queue(page: Page) -> None:
    """人間確認: 未分類キュー → 分類を直す → 確定 → キューから消える。

    QA（全支店を見られる）で撮る。支店管理者だと自支店のキューに
    「なんか変」のような情報欠損サンプルしか残らない場合があり、
    「人が直す」場面の素材として弱くなるため。
    """
    page.goto(f"{BASE}/admin?uid=2")
    _wait_reports_table(page)
    page.click("#tabQueue")
    _wait_reports_table(page)
    _shot(page, "05_queue")
    rows = page.locator("#reports table tbody tr")
    if rows.count() == 0:
        raise RuntimeError("未分類キューが空です。make demo で再シードしてください")
    # 「なんか変」等の情報欠損サンプルは素材として弱い（人が直す判断材料が無い）。
    # 要約が最も長い行＝具体が書かれた報告を選ぶ（AIが迷った実例として説得力がある）。
    _substantive_row(rows).click()
    page.wait_for_selector("#detail form")
    page.locator("#detail").scroll_into_view_if_needed()
    time.sleep(0.5)
    _shot(page, "06_queue_detail")
    # 落書き＝清掃で対応する事象。AIが「その他」に寄せたのを人が正す筋書き。
    page.select_option("#detail form select[name=category]", "cleaning")
    page.select_option("#detail form select[name=urgency]", "low")
    page.click("#detail form button[type=submit]")
    page.wait_for_selector("#detail p.ok", timeout=15_000)
    _wait_reports_table(page)
    page.locator("#detail").scroll_into_view_if_needed()
    time.sleep(0.5)
    _shot(page, "07_queue_confirmed")


def scene_monthly(page: Page) -> None:
    """月次: 生成 → 2ペイン編集 → 承認 → 確定バナー。"""
    page.goto(f"{BASE}/monthly?uid=1")
    page.wait_for_selector("form")
    _shot(page, "08_monthly_list")
    # シードデータの報告書は 2026-06 に集中しているため対象月を固定する（当月だと件数が乏しい）
    page.select_option("form select[name=month]", "2026-06-01")
    page.click("form button[type=submit]")
    # generating 中は meta refresh(3s) で自動リロード。editor 出現まで待つ
    page.wait_for_selector(".editor textarea", timeout=120_000)
    _shot(page, "09_monthly_editor")
    textarea = page.locator(".editor textarea")
    textarea.focus()
    # 末尾にカーソルを置いてから追記する（OS 差のあるショートカットは使わない）
    textarea.evaluate("el => { el.selectionStart = el.selectionEnd = el.value.length; }")
    page.keyboard.type(
        "\n\n（支店長コメント）巡回頻度を見直し、次月は経過を報告します。", delay=TYPE_DELAY_MS
    )
    page.once("dialog", lambda d: d.accept())
    page.click("button.approve")
    page.wait_for_selector(".banner.ok", timeout=30_000)
    _shot(page, "10_monthly_approved")


def scene_audit(page: Page) -> None:
    """監査ログ: 上書き・承認・検索が追記のみで残る。"""
    page.goto(f"{BASE}/audit?uid=1")
    page.wait_for_selector("table, .empty-state")
    _shot(page, "11_audit")


def scene_webhook(page: Page) -> None:
    """緊急通知: webhook-mock の受信内容（Slack 通知の証拠）。"""
    page.goto(f"{WEBHOOK}/received")
    time.sleep(0.5)
    _shot(page, "12_webhook_received")


def scene_scenarios(page: Page) -> None:
    """受入シナリオ実行画面（取込パイプラインの自動判定・品質文化の証拠）。"""
    page.goto(f"{BASE}/scenarios")
    page.wait_for_selector(".scn")
    page.locator(".scn button").first.click()
    page.wait_for_selector(".ok-mark, .ng-mark", timeout=60_000)
    _shot(page, "13_scenarios")


SCENES: dict[str, Callable[[Page], None]] = {
    "home": scene_home,
    "search_stream": scene_search_stream,
    "search_noresult": scene_search_noresult,
    "auth_switch": scene_auth_switch,
    "review_queue": scene_review_queue,
    "monthly": scene_monthly,
    "audit": scene_audit,
    "webhook": scene_webhook,
    "scenarios": scene_scenarios,
}


def run_scene(name: str, color_scheme: str = "light") -> None:
    fn = SCENES[name]
    with sync_playwright() as p:
        browser = p.chromium.launch(slow_mo=SLOW_MO_MS)
        context = browser.new_context(
            viewport=VIEWPORT,
            color_scheme=color_scheme,  # type: ignore[arg-type]
            record_video_dir=str(VIDEO / name),
            record_video_size=VIEWPORT,
        )
        page = context.new_page()
        try:
            fn(page)
        finally:
            video = page.video
            context.close()
            browser.close()
            if video:
                # Playwright はランダム名で保存するのでシーン名に揃える
                src = Path(video.path())
                dest = VIDEO / f"{name}.webm"
                shutil.move(str(src), str(dest))
                shutil.rmtree(VIDEO / name, ignore_errors=True)
                print(f"video: {dest}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=sorted(SCENES), help="1シーンだけ撮る")
    parser.add_argument("--all", action="store_true", help="全シーンを順に撮る")
    parser.add_argument("--dark", action="store_true", help="ダークモードで撮る")
    args = parser.parse_args()

    SHOTS.mkdir(parents=True, exist_ok=True)
    VIDEO.mkdir(parents=True, exist_ok=True)
    scheme = "dark" if args.dark else "light"

    names = sorted(SCENES) if args.all else [args.scene] if args.scene else []
    if not names:
        parser.error("--scene か --all を指定してください")
    for name in names:
        print(f"== {name} ==")
        run_scene(name, scheme)


if __name__ == "__main__":
    main()
