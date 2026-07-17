# API設計書 — Report Insight

| 項目 | 内容 |
|---|---|
| 文書バージョン | 1.0 |
| ベースURL | `/api/v1` |
| 認証 | セッションCookie（SSO想定の抽象化。詳細は[基本設計書 §3](02_basic_design.md#3-セキュリティ設計)） |

---

## 1. 共通仕様

### エラーレスポンス（RFC 9457 Problem Details）

```json
{
  "type": "https://example.com/errors/not-found",
  "title": "Report not found",
  "status": 404,
  "detail": "report_id=123 は存在しません",
  "request_id": "req_abc123"
}
```

| ステータス | 用途 |
|---|---|
| 400 | バリデーションエラー（詳細を `errors[]` で返す） |
| 401 / 403 | 未認証 / 権限外（他支店の物件など） |
| 404 | リソースなし |
| 422 | LLM処理が完了していない報告書への操作など、状態起因の拒否 |
| 429 | レートリミット（検索API: 10 req/min/user） |
| 503 | LLM APIの障害時（Retry-After 付き） |

### ページネーション

カーソル方式。`?cursor=xxx&limit=50`（デフォルト50、最大200）。レスポンスに `next_cursor` を含む。

## 2. エンドポイント一覧

| メソッド | パス | 概要 | 対応要件 |
|---|---|---|---|
| GET | `/reports` | 報告書一覧（フィルタ/ソート） | F-4-1 |
| GET | `/reports/{id}` | 報告書詳細（構造化結果含む） | F-4-1 |
| PATCH | `/reports/{id}/analysis` | AI分類の人間による修正・確定 | F-1-5, F-4-4 |
| GET | `/reports/review-queue` | 未分類キュー（確信度低） | F-4-4 |
| POST | `/search` | RAG検索（SSEストリーミング） | F-2 |
| POST | `/monthly-reports` | 月次報告書ドラフト生成（非同期） | F-3-1 |
| GET | `/monthly-reports/{id}` | ドラフト取得（生成中は202） | F-3-1 |
| PATCH | `/monthly-reports/{id}` | ドラフト編集・承認 | F-3-2 |
| GET | `/monthly-reports/{id}/pdf` | 確定済み報告書のPDF | F-3-3 |
| GET | `/properties` | 物件一覧（権限内のみ） | 共通 |
| GET | `/healthz` / `/readyz` | 死活監視（ALBヘルスチェック） | 運用 |

報告書の**登録APIは存在しない**（取込はS3→SQS→workerの非同期パイプラインのみ。基本設計書 §2.1）。

## 3. 主要エンドポイント詳細

### GET /reports

```
GET /api/v1/reports?property_id=101&category=equipment_failure&urgency=high&status=needs_review&from=2026-07-01&to=2026-07-17&sort=-reported_at
```

```json
{
  "items": [
    {
      "id": 1234,
      "property": {"id": 101, "name": "第一〇〇ビル"},
      "reported_at": "2026-07-16T10:30:00+09:00",
      "reporter_role": "巡回スタッフ",
      "raw_text": "3階廊下の天井から水漏れ…",
      "analysis": {
        "category": "equipment_failure",
        "urgency": "high",
        "action_required": true,
        "normalized_summary": "3F廊下天井にて漏水。天井材にシミ、滴下あり。",
        "confidence": 0.94,
        "status": "auto_classified"
      }
    }
  ],
  "next_cursor": "eyJpZCI6MTIzNH0"
}
```

`analysis.status`: `auto_classified`（AI確定）/ `needs_review`（人間確認待ち）/ `human_verified`（人間確定）/ `processing` / `failed`

### PATCH /reports/{id}/analysis

人間がAI分類を修正・確定する。**修正履歴は評価データセットの改善に使う**（[LLM設計書 §4](05_llm_design.md)）。

```json
// リクエスト
{"category": "claim", "urgency": "medium", "action_required": true}
// レスポンス: 200、status は human_verified になる
```

### POST /search（SSE）

```json
{"query": "第一〇〇ビルで過去に雨漏り対応した事例", "filters": {"property_id": null, "from": null, "to": null}}
```

SSEイベント列：

```
event: sources        # 先に根拠を返す（UIは即表示）
data: {"reports": [{"id": 987, "reported_at": "2025-06-10", "summary": "..."}]}

event: token
data: {"text": "2025年6月に同物件で"}

event: done
data: {"citations": [987, 1012], "latency_ms": 2100, "input_tokens": 3200, "output_tokens": 450}
```

- 引用IDはAPI層で実在検証済みのもののみ返す
- 該当事例が0件の場合、LLM生成を行わず `event: no_results` を返す（ハルシネーション防止・コスト節約）

### POST /monthly-reports

```json
// リクエスト
{"property_id": 101, "month": "2026-06"}
// レスポンス: 202 Accepted
{"id": 55, "status": "generating"}
```

生成完了までポーリング（`GET /monthly-reports/55` が `status: draft` を返すまで）。同一物件×月の再生成は既存ドラフトを versioning して保持。

### PATCH /monthly-reports/{id}

```json
{"body_markdown": "（編集後の本文）", "action": "save"}     // 下書き保存
{"action": "approve"}                                        // 承認・確定
```

`approved` 後の編集は 422。承認操作は audit_logs に記録される。

## 4. 権限マトリクス

| 操作 | 支店管理者 | 品質管理部 |
|---|---|---|
| 自支店の報告書閲覧・修正 | ✅ | ✅ |
| 他支店の報告書閲覧 | ❌ | ✅ |
| 検索 | 自支店スコープ | 全社スコープ |
| 月次報告書の生成・承認 | 自支店のみ | ❌（閲覧のみ） |
