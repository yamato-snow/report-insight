"""月次報告書PDFが日本語を実際に描画できることの検証（F-3-3）。

背景: 他の月次テストは FakePdfRenderer に差し替えているため、**実レンダラ（WeasyPrint）の
経路が一度も検証されていなかった**。その結果、コンテナに日本語フォントが無いことに気づかず、
PDF の日本語が全て豆腐（□）になる不具合を受入テストまで見逃した（2026-07-21）。

WeasyPrint はネイティブ依存（pango/cairo）をコンテナ内でのみ解決するため、ホストでは skip する。
実行は `make test-pdf`（api コンテナ内で pytest を起動する）。

tests/integration/ ではなく専用ディレクトリに置く理由: integration の conftest は
testcontainers で PostgreSQL を起動するが、コンテナ内から Docker は使えないため。
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app.infra.pdf.renderer import WeasyPrintPdfRenderer

# 日本語（CJK字形の埋め込みが必要）と英数字のみ（埋め込み不要）の同等文書。
# フォントが無いと日本語側は豆腐になり、字形が埋め込まれないためサイズが伸びない。
_JA = "# 第一グランドビル\n\n設備不具合が最多で、苦情・要望も確認されました。"
_EN = "# Building One\n\nEquipment failures were most common this month."

# 実測（フォント有）は約20倍。フォント欠落時はほぼ同サイズになるため、
# 十分な余裕を持たせた 5倍 を閾値にする。
_MIN_RATIO = 5.0


def _weasyprint_available() -> bool:
    # ネイティブ依存が無い環境では import 時に OSError（ライブラリ未解決）になる
    try:
        import weasyprint  # noqa: F401, PLC0415 — 可用性の確認のみ
    except (ImportError, OSError):
        return False
    return True


requires_weasyprint = pytest.mark.skipif(
    not _weasyprint_available(),
    reason="WeasyPrint のネイティブ依存はコンテナ内でのみ解決する（make test-pdf）",
)


@requires_weasyprint
def test_japanese_font_is_available_to_the_renderer() -> None:
    """fontconfig が日本語フォントを解決できること（PDF 文字化けの直接原因を検知する）。"""
    fc_list = shutil.which("fc-list")
    assert fc_list, "fontconfig (fc-list) がありません。コンテナ内で実行してください。"
    result = subprocess.run(  # noqa: S603 — 解決済みの絶対パスを固定引数で実行
        [fc_list, ":lang=ja", "family"], capture_output=True, text=True, check=False
    )
    families = [line for line in result.stdout.splitlines() if line.strip()]
    assert families, (
        "日本語フォントが見つかりません。PDF の日本語が豆腐（□）になります。"
        "Dockerfile の fonts-noto-cjk が入っているか確認してください。"
    )


@requires_weasyprint
async def test_japanese_glyphs_are_embedded_in_pdf() -> None:
    """日本語PDFにCJK字形が埋め込まれること。

    フォント欠落時は豆腐になり字形が埋め込まれないため、英数字のみの文書と
    ほぼ同サイズになる。実際の描画結果をバイト数の比で判定する。
    """
    renderer = WeasyPrintPdfRenderer()
    ja = await renderer.render(title="月次報告", body_markdown=_JA)
    en = await renderer.render(title="Monthly", body_markdown=_EN)

    assert ja.startswith(b"%PDF"), "PDF として出力されていません"
    ratio = len(ja) / len(en)
    assert ratio >= _MIN_RATIO, (
        f"日本語PDFにCJK字形が埋め込まれていません（ja={len(ja)}B / en={len(en)}B / "
        f"比={ratio:.1f}倍 < {_MIN_RATIO}倍）。日本語が豆腐になっている可能性が高いです。"
    )
