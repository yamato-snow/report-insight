# デモガイド

Report Insight を人前で動かすための手引き。画面素材・台本・説明資料の索引を兼ねる。

| ドキュメント | 内容 |
|---|---|
| [01_user_flow.md](01_user_flow.md) | 操作フロー全体（取込 → AI分類 → 人間確認 → RAG検索 → 月次報告） |
| [02_ai_human_roles.md](02_ai_human_roles.md) | AIに任せた部分と人間が判断する部分（実装根拠つき） |
| [03_constraints.md](03_constraints.md) | 制約と意図的なスコープ外（架空データ・未デプロイ等） |
| [04_design_decisions.md](04_design_decisions.md) | 面談で説明できる設計判断の索引 |
| [05_video_script.md](05_video_script.md) | 3〜5分デモ動画の絵コンテ・ナレーション台本 |

## 起動（2系統）

### A. 実API（人に見せる本番用・課金あり）

```bash
LLM_PROVIDER=anthropic docker compose up -d   # 要 ANTHROPIC_API_KEY（.env）
make migrate
make demo    # 合成報告書100件を実Claudeで分類（数分・数百円）
```

### B. fake（リハーサル用・課金ゼロ・完全オフライン）

```bash
docker compose up -d      # 既定 LLM_PROVIDER=fake
make migrate && make demo # 決定的な擬似AI。要約・回答文は擬似生成なので見栄えは落ちる
```

http://localhost:8000/ を開く。デモデータはシード固定（`scripts/synth.py` seed=42）で再現可能。

## 推奨デモ順序（画面）

1. **トップ `/`** — 3課題と画面の対応を30秒で説明
2. **報告書一覧 `/admin`** — AI分類済み一覧 → 利用者切替で権限の違い（東京3物件 ⇄ 大阪2物件 ⇄ QAは全社横断）
3. **未分類キュー** — 確信度の低い報告書を人が直して確定 → キューから消える
4. **過去事例検索 `/search`** — 水漏れ事例（ストリーミング+引用+初回表示ms）→ 無関係クエリで「該当なし」
5. **月次報告書 `/monthly`** — ドラフト生成 → 編集 → 承認 → PDF
6. **監査ログ `/audit`** — 2〜5の操作が追記のみで残っていることを見せて締め

緊急通知の証拠は http://localhost:9000/received（webhook-mock の受信JSON）。

## 詰まったときの逃げ道

| 症状 | 対応 |
|---|---|
| worker 再起動直後に取込が進まない | 埋め込みモデルの再ロードで数十秒かかる（仕様）。待つ |
| 未分類キューが空（確定し尽くした） | `make demo` で再シード（実APIは課金・数分）。デモ直前の練習はキューを消費しないこと |
| 検索が遅い・失敗する | fake 起動なら即応答。実APIの失敗時は再実行 → それでもだめなら fake に切替えて続行 |
| 月次生成が終わらない | 画面は3秒ごとに自動リロード。2分超えたら `docker compose logs worker api` を確認 |
| 生成済み月次を使い回したい | 同月・同物件は再生成でversionが上がる。承認済みは編集不可なので別の月を選ぶ |

## 実施済みの品質担保（口頭で聞かれたら）

unit 48 / integration 22 / 受入シナリオ3（自動判定） / PDF日本語描画2 / LLM評価150件（実API・PASS）。
受入テスト29ケース実施・機能不合格ゼロ（[../12_uat_cases.md](../12_uat_cases.md)）。
