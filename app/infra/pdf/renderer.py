"""WeasyPrint による PDF レンダラ（PdfRendererPort 実装）。

WeasyPrint はネイティブ依存（pango/cairo）を要するため import は render 内で遅延させる
（ホスト/軽量CIでモジュール import 時に失敗しないため。引き継ぎ注意 §3-9）。
Markdown→HTML の変換は html=False（生HTMLを無効化）で行い、本文由来のタグ注入を防ぐ。
"""

from __future__ import annotations

import asyncio
from html import escape

from markdown_it import MarkdownIt

_HTML_TEMPLATE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  @page {{ size: A4; margin: 20mm; }}
  body {{ font-family: "Noto Sans CJK JP", "Hiragino Sans", sans-serif;
          font-size: 11pt; line-height: 1.7; color: #111; }}
  h1 {{ font-size: 18pt; border-bottom: 2px solid #333; padding-bottom: 6px; }}
  h2 {{ font-size: 13pt; margin-top: 20px; border-left: 4px solid #666; padding-left: 8px; }}
  table {{ border-collapse: collapse; width: 60%; margin: 8px 0; }}
  th, td {{ border: 1px solid #999; padding: 4px 10px; }}
  th {{ background: #f0f0f0; }}
  td:last-child {{ text-align: right; }}
</style>
</head>
<body>
{body_html}
</body>
</html>
"""


class WeasyPrintPdfRenderer:
    """PdfRendererPort の WeasyPrint 実装。"""

    def __init__(self) -> None:
        self._md = MarkdownIt("commonmark", {"html": False}).enable("table")

    async def render(self, *, title: str, body_markdown: str) -> bytes:
        body_html = self._md.render(body_markdown)
        html = _HTML_TEMPLATE.format(title=escape(title), body_html=body_html)
        # WeasyPrint は同期・ブロッキング。イベントループを塞がないよう別スレッドで実行する。
        return await asyncio.to_thread(_render_pdf, html)


def _render_pdf(html: str) -> bytes:
    from weasyprint import HTML  # noqa: PLC0415 — 遅延import（ネイティブ依存はコンテナ内で解決）

    result: bytes = HTML(string=html).write_pdf()
    return result
