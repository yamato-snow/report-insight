# DB設計書 — Report Insight

| 項目 | 内容 |
|---|---|
| 文書バージョン | 1.0 |
| DBMS | PostgreSQL 16 + pgvector（選定理由: [ADR-001](adr/ADR-001-vector-store.md)） |
| マイグレーション | Alembic |

---

## 1. ER図

```mermaid
erDiagram
    branches ||--o{ properties : has
    branches ||--o{ users : belongs
    properties ||--o{ reports : has
    reports ||--|| report_analyses : has
    reports ||--o{ report_chunks : embeds
    properties ||--o{ monthly_reports : has
    users ||--o{ audit_logs : acts

    branches {
        bigint id PK
        text name
    }
    users {
        bigint id PK
        bigint branch_id FK "NULL=品質管理部"
        text email UK
        text role "branch_manager | qa"
    }
    properties {
        bigint id PK
        bigint branch_id FK
        text name
        text address
    }
    reports {
        bigint id PK
        bigint property_id FK
        text source_key UK "S3オブジェクトキー（冪等性キー）"
        timestamptz reported_at
        text reporter_role
        text raw_text
        jsonb photo_meta
        timestamptz created_at
    }
    report_analyses {
        bigint report_id PK_FK
        text category "cleaning|equipment_failure|claim|other"
        text urgency "high|medium|low"
        boolean action_required
        text normalized_summary
        real confidence
        text status "processing|auto_classified|needs_review|human_verified|failed"
        text model_id "監査用: どのモデル・プロンプトverで分類したか"
        text prompt_version
        int input_tokens
        int output_tokens
        timestamptz analyzed_at
    }
    report_chunks {
        bigint id PK
        bigint report_id FK
        int chunk_index
        text content
        vector embedding "vector(1024)"
    }
    monthly_reports {
        bigint id PK
        bigint property_id FK
        date month
        int version
        text body_markdown
        text status "generating|draft|approved|failed"
        bigint approved_by FK
        timestamptz approved_at
    }
    audit_logs {
        bigint id PK
        bigint user_id FK
        text action "search|approve|override_analysis"
        jsonb payload
        timestamptz created_at
    }
```

## 2. 設計ポイント

### 冪等性

`reports.source_key`（S3オブジェクトキー）に UNIQUE 制約。SQS再配信時は `INSERT ... ON CONFLICT (source_key) DO NOTHING` で二重登録を防ぐ。

### 分析結果を reports と分離する理由

- 再分析（プロンプト改善後の再実行）時に reports 本体を不変に保てる
- `model_id` / `prompt_version` / トークン数を分析ごとに記録し、コスト集計と品質追跡を可能にする（[LLM設計書 §5](05_llm_design.md)）

### チャンク戦略

- 報告書は短文（平均300字）のため原則1報告書=1チャンク。長文（>1,500字）のみ意味段落で分割
- `content` には正規化サマリ＋原文を結合して埋め込む（表記ゆれ対策：正規化語彙が検索にヒットしやすくなる）

### ベクトルインデックス

```sql
CREATE INDEX ON report_chunks USING hnsw (embedding vector_cosine_ops);
```

- HNSW を採用（IVFFlat はデータ増加時に再構築が必要になるため）
- 想定規模：400件/日 × 365日 ≒ 15万行/年 → pgvector で十分（[ADR-001](adr/ADR-001-vector-store.md)）

### ハイブリッド検索クエリ（概形）

```sql
SELECT r.id, rc.content,
       1 - (rc.embedding <=> :query_vec) AS similarity
FROM report_chunks rc
JOIN reports r          ON r.id = rc.report_id
JOIN report_analyses ra ON ra.report_id = r.id
WHERE (:property_id IS NULL OR r.property_id = :property_id)
  AND (:category    IS NULL OR ra.category  = :category)
  AND (:from        IS NULL OR r.reported_at >= :from)
  AND r.property_id = ANY(:permitted_property_ids)   -- 認可はSQLレイヤで強制
ORDER BY rc.embedding <=> :query_vec
LIMIT 8;
```

認可フィルタ（`permitted_property_ids`）を検索SQLに必ず含め、アプリ層のフィルタ漏れで他支店データが漏れる事故を構造的に防ぐ。

## 3. マイグレーション運用

- Alembic リビジョンは PR 単位で1本。CI で `alembic upgrade head → downgrade -1 → upgrade head` を検証
- 本番適用はデプロイパイプライン内で ECS タスク実行（基本設計書 §6）
