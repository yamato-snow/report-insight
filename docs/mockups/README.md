# 画面モック（役目を終えた設計資料）

> **2026-07-21: 受入テストから退役しました。** ここは「本体に実装する前に見た目と操作を
> 確認する」ための下書きで、承認を経て本体（FastAPI + HTMX）へ実装済みです。
> **受入テストは本体 <http://localhost:8000> で実施してください**（手順は
> [docs/12_uat_cases.md](../12_uat_cases.md)）。ポートを2つ立てる必要はありません。

## 生きているファイル

| ファイル | 役割 | 現状 |
|---|---|---|
| `testcases.js` | **受入テストケースの唯一の正本** | 現役。`node scripts/gen_uat_doc.mjs` が `docs/12_uat_cases.md` を生成する |
| `checklist.html` | ケース一覧に OK/NG を付ける画面 | 参考。本体側で実施するため通常は不要 |
| その他の html/css/js | 画面モック（本体へ実装済み） | 参考資料 |

`testcases.js` だけは本体の受入テストの正本として使い続けるので**消さないこと**。

## 参考: モックを見たい場合

```bash
python3 -m http.server 8100 --directory <絶対パス>/docs/mockups
```

（`--directory` は絶対パスで渡す。相対だと 404 になる）

## 本体との対応

| モック | 本体 |
|---|---|
| `admin.html` | `/admin?uid=1` |
| `monthly-list.html` / `monthly-edit.html` | `/monthly?uid=1` |
| `audit.html` | `/audit?uid=1` |
| `pipeline.html`（データの流れ） | `/scenarios`（自動判定）＋ CloudWatch 監視（DLQ は UI を持たない） |
| `submit.html`（報告の投入） | 本番は S3 → SQS → ワーカー（要件どおり投入画面は作らない） |
