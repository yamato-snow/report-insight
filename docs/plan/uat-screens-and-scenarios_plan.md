---
date: 2026-07-20
model: opus
status: done
issue: ""
topic: 受入テスト基盤（本体への画面組み込み＋シナリオJSON化）
predecessor: tfstate-backend-bootstrap_plan.md
---

# 受入テスト基盤: 本体への画面組み込みとシナリオJSONによる自動判定

## 背景

- 2026-07-20、CEO の指摘により **AWS 構築（tfstate bootstrap）を凍結**。
  「ローカルで動くものをユーザーが受け入れテストしてからクラウドへ」という順序に是正した。
  tfstate bootstrap はコード完成済み・apply は IAM 権限不足で未実施（`chore/tfstate-backend-bootstrap` ブランチ）
- 調査の結果、**API はほぼ完成しているが画面が不足**していることが判明。
  特に月次報告書は生成・編集・承認・PDF がすべて API にあるのに画面が1枚も無く、
  クライアントの3大課題のうち「月次報告書の作成負荷」が受入テスト不能だった
- `docs/mockups/` に HTML/CSS/JS のモックを作成し、CEO が画面内容を確認済み

## 決定事項（CEO 合意 2026-07-20）

1. **月次報告書 UI は今回作る**（基本設計 §8 の「Phase 2 送り」を今回分だけ見直し）。
   理由: これが無いと依頼主の3大課題の1つが受入テストから丸ごと抜ける
2. **現場スタッフ向けの報告画面は作らない**（要件どおりスコープ外を維持）。
   ただし受入テストの入口として**検査用の投入治具**は用意する
3. **製品画面と検査用治具は分離する**。治具は本体に組み込まない
4. **機械判定できるものはシナリオJSONに移す**。手動チェックリストは
   「人にしか判断できないもの」（文面の妥当性・操作性）だけに瘦せさせる
5. **順番: 先に本体へ組み込む → 本物の画面で受入テストを回す**。
   モック上でのテストは本体の保証にならないため

## 対象範囲

### A. 本体への画面組み込み（FastAPI + Jinja + HTMX）

モック `docs/mockups/` を正とし、以下を実装する。

| # | 内容 | 現状 | 対象ファイル |
|---|---|---|---|
| A-1 | 一覧に**物件名**を表示（現在は property_id の数値） | 未 | `templates/_reports_table.html`, `routers/admin_ui.py` |
| A-2 | **ページ送り**（現在 limit=50 固定・cursor=None 固定） | 未 | `routers/admin_ui.py`, `_reports_table.html` |
| A-3 | **報告書詳細**（原文が読める。現在は行に遷移先が無い） | 未 | 新 `templates/_report_detail.html`, `admin_ui.py` |
| A-4 | **分類の上書き UI**（`PATCH /reports/{id}/analysis` は実装済、画面が無い） | API のみ | 同上 |
| A-5 | **月次報告書 UI**（一覧・生成・編集・承認・PDF。API は全て実装済） | API のみ | 新 `routers/monthly_ui.py`, 新テンプレート |
| A-6 | **監査ログ画面**（受入条件の「監査ログに残る」の確認手段） | 未 | 新ルータ/テンプレート。※要調査: 監査ログの参照系 API が無い可能性あり |
| A-7 | **利用者切替 UI**（現在は `?uid=` の手打ち。SSO の抽象点は維持） | 未 | 共通ヘッダ |

### B. シナリオJSONによる自動判定

現状 LLM 評価の期待値は **Python コード内**（`scripts/synth.py` の `_TEMPLATES`、
`tests/llm_eval/datasets.py` の `_SEARCH_DOCS` / `_FAITHFULNESS`、閾値は
`tests/llm_eval/metrics.py` の定数）にあり、**JSON を差し替えてケースを増やせない**。

| # | 内容 |
|---|---|
| B-1 | `tests/scenarios/*.json` を新設。1ファイル＝1シナリオ（入力報告書群＋個別期待値＋全体期待値） |
| B-2 | ランナー `tests/scenarios/run.py`。JSON を読み、Fake LLM で流し、期待値と突合して OK/NG と差分を出す。終了コードで合否 |
| B-3 | `make scenario`（全件）/ `make scenario NAME=xxx`（単体）を Makefile に追加 |
| B-4 | CI（`.github/workflows/ci.yml`）の unit ジョブ相当に組み込む（実 API 不要・課金ゼロで回ること） |
| B-5 | 検査用テスト画面からシナリオを選択して実行できるようにする（人が目でも確認できる） |
| B-6 | 手動チェックリスト（`docs/mockups/testcases.js`、現在29件）から機械判定へ移せる分を削り、人の判断が要るものだけ残す |

**シナリオJSONの形（確定）**:

```json
{
  "name": "緊急案件が通知され、迷った報告はキューに回る",
  "requirements": ["F-1-2", "F-1-4", "F-1-5"],
  "inputs": [
    { "property": "新宿センタービル",
      "text": "地下1階の配管から水漏れ。床が濡れて危険なため止水しました。",
      "expect": { "category": "equipment_failure", "urgency": "high",
                  "notified": true, "queued": false } }
  ],
  "expect_overall": { "lost": 0, "notified": 1, "queued": 1 }
}
```

## 対象外（今回やらないこと）

- **AWS の構築・apply**（受入テスト通過後に `tfstate-backend-bootstrap_plan.md` から再開）
- 現場スタッフ向けの報告画面の製品実装（要件どおりスコープ外を維持）
- SSO(SAML) の実装（`X-User-Id` / `uid` の抽象点は維持したまま）
- 検索画面の作り直し（既に実装済・今回変更しない）
- LLM 評価の閾値（`metrics.py`）の設定ファイル化（B の対象は入力と期待値。閾値は現状維持）
- モック（`docs/mockups/`）の本体への移植以外の作り込み

## 検証手順

1. `make up && make migrate && make demo` で本体を起動しデータ投入
2. A-1〜A-7 を `http://localhost:8000/admin` 系で手動確認
3. `make test`（unit 42件）と `make test-integration`（21件）が引き続き通ること
4. `make scenario` が全シナリオ OK で終了コード 0
5. わざと期待値を外したシナリオを1件作り、**NG が正しく検出され終了コードが 1 になる**こと（ランナー自体の検算）
6. `docs/12_uat_cases.md` を再生成（`node scripts/gen_uat_doc.mjs`）し、本物の画面で受入テストを実施

## 完了条件

- [ ] A-1〜A-5 が本体に実装され、`http://localhost:8000` で操作できる
- [ ] A-6 監査ログの確認手段がある（参照系 API が無ければ追加するか、代替手段を明記）
- [ ] A-7 利用者切替が画面上でできる（`?uid=` の手打ちが不要）
- [ ] 承認後の月次報告書が編集不可になり、PDF が実ファイルとしてダウンロードできる
- [ ] QA ロールで月次の作成・承認ができないことを本物の画面で確認できる
- [ ] `tests/scenarios/*.json` が3本以上あり、`make scenario` が通る
- [ ] シナリオの NG 検出が機能する（検証手順5）
- [ ] `make test` / `make test-integration` が引き続き通る
- [ ] CI にシナリオ実行が組み込まれ、実 API 不要で回る
- [ ] 手動チェックリストが「人の判断が要るもの」だけに整理されている
- [ ] PR 作成（AWS 関連の変更を含めないこと）

## ロールバック方法

- 本体への画面追加は新規ルータ/テンプレートが中心。既存 API は変更しないため、
  ルータ登録を外せば元に戻る（`app/api/main.py` の `include_router` を削除）
- `_reports_table.html` / `admin_ui.py` は既存を変更するため、revert で戻す
- シナリオ基盤は追加のみ（`tests/scenarios/`、Makefile ターゲット、CI ジョブ）で、
  既存のテストには手を触れないため独立して revert 可能
- `docs/mockups/` は本体実装後も残す（治具として使うため）。不要になれば削除のみ

## 実装時差分（2026-07-21 完了）

### A. 本体への画面組み込み — 完了、本物の画面で検証済み
- A-1〜A-5 実装。物件名表示・ページ送り（keyset）・報告書詳細・分類の直し・月次UI（生成→編集→承認→PDF）
- A-6 監査ログ画面（参照系 `SqlAuditRepository.list_recent` を新設）
- A-7 利用者切替（共通ヘッダ `_topbar.html`。SSO 抽象点は維持）
- 実データ130件（実API・Haiku 分類）で全画面を実機確認

### B. シナリオJSON — 完了
- `tests/scenarios/cases/*.json`（3本）＋ `runner.py`（実 IngestService + Fake LLM/Embedding + 本物 PIIMasker）
- `make scenario` / `make scenario NAME=xxx`、CI の unit ジョブに追加（実API不要・課金ゼロ）
- 受入シナリオ画面 `/scenarios`（env≠prod のみマウント・tests 依存は遅延import）
- 手動チェックリスト（testcases.js）: 振り分け系4件を `auto` 印にし、手動は25件へ整理

### 実装中に見つけて直した既存不具合（計画外）
1. **月次報告書に QA 制限が無かった**（設計では閲覧のみ）→ `MonthlyService._deny_qa_writes` 追加。API でも 403
2. **絞り込みで「すべて」が 422**（空文字が型に不一致）→ `_empty_to_none` バリデータ
3. **UI 書き込みが未コミット**（unit_of_work 未使用）→ 全書き込み経路を修正
4. **所見に英字 enum が漏れる**（`cat.value` を LLM へ）＋ラベル定義が2箇所で不一致
   → `app/domain/labels.py` に唯一の正本を作り、画面・PDF・プロンプトを統一

### LLM プロバイダ
- `.env` のキーは渡っていたが `LLM_PROVIDER=fake` のままだった。`anthropic` で起動し直し、
  分類・所見が実 Claude で動くことを確認（起動コマンドで上書き。.env は不変更）

### 検証結果
- unit 46 / integration 22 / scenario 3（CLI・pytest）すべて green。ruff/mypy/import-linter pass
- 完了条件は全項目クリア

### 参考: 起動メモ
- 本体: `LLM_PROVIDER=anthropic docker compose up -d`（fake なら省略可）
- モック: `python3 -m http.server 8100 --directory <絶対パス>/docs/mockups`
- ワーカー再起動時は埋め込みモデル再ロードで数十秒かかる（詰まりではない）

## 受入テスト実施（2026-07-21・追記）

全29ケースを本体（実データ100件・実API）で実施。**機能面の不合格ゼロ**（OK 28／要判断 1）。
実施環境は本体 8000 に一本化し、モック 8100 は受入テストから退役させた。

指摘2件はいずれも対応済み。

1. **検索3秒未達 → 計測対象の誤りだった**。要件は「検索応答3秒以内（LLM生成部は
   ストリーミング表示）」で、3秒の対象は**読み始められるまで**。総生成時間を測っていた。
   分解計測の結果 初回表示は 880〜2,302ms で**元から要件を満たしていた**。
   再発防止として `first_token_ms` / `retrieval_ms` を追加し画面表示・警告を実装
2. **エレベーター事例がデモデータに無く代表クエリが空振り** → `scripts/synth.py` に
   4パターン追加、実APIで100件再分類。同クエリが3種類に整理されて返ることを確認

残る手動確認（人の判断）: AIの要約の質、月次報告書「所見」の文面。

開発ログ（記事・面接用の記録）: `docs/handbook/devlog-2026-07-uat.md`

## 次のステップ（この計画の外）
- 上記2点を CEO が目視確認
- 通過後に `tfstate-backend-bootstrap_plan.md` から AWS 構築を再開（IAM 権限付与が前提）
