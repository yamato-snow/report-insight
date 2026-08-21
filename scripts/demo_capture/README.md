# デモ素材の撮影（demo_capture）

スクリーンショットと無音の操作キャプチャ（webm → GIF/mp4）を Playwright で撮る。
Playwright はプロジェクト依存に含めず `uv run --with` で使う（pyproject / uv.lock を汚さない）。

## 前提

1. スタックが実APIで起動しシード済みであること（課金あり・数百円/回。撮り直しは同一DBで行い再シードしない）

   ```bash
   LLM_PROVIDER=anthropic docker compose up -d
   make migrate && make demo
   ```

2. 初回のみブラウザ取得:

   ```bash
   uv run --with playwright playwright install chromium
   ```

## 撮影

```bash
uv run --with playwright python scripts/demo_capture/capture.py --all      # 全シーン
uv run --with playwright python scripts/demo_capture/capture.py --scene search_stream
uv run --with playwright python scripts/demo_capture/capture.py --scene home --dark  # ダーク版
```

- 出力: `out/shots/*.png` / `out/video/*.webm`（ビューポートのみ記録。URLバーは写らない）
- 注意: `monthly` シーンは月次ドラフトを1件生成・承認する（実API課金・数円）。
  `review_queue` は未分類キューを1件消費する。キューが空になったら `make demo` で再シード（課金・数分）

## 変換と配置

```bash
scripts/demo_capture/convert.sh            # 全 webm → out/gif/ out/mp4/
scripts/demo_capture/convert.sh search_stream
```

- README / docs に載せるものだけ `docs/images/` へコピーする（GIF は各3MB以下を厳守）
- `out/`（生 webm / mp4）はコミットしない（.gitignore 済み）。3〜5分動画の完成品もリポジトリ外で配布する

## 台本との対応

各シーンがどのカット・ナレーションに対応するかは `docs/demo/05_video_script.md` を参照。
