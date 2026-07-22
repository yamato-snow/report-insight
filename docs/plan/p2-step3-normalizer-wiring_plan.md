---
date: 2026-07-20
model: fable
status: draft
issue: ""
topic: 表記ゆれ正規化器の IngestService 本番配線（P2 第3歩）
predecessor: p2-observability-metrics-cost-alarm_handoff.md
---

# P2 第3歩: 表記ゆれ正規化器の IngestService 本番配線

## 背景

- Fable 関与理由: 設計は P2 監査（2026-07-19）で合意済み。本 plan は配線位置と
  port 定義の固定のみ（F2: ドリフト防止の軽量ゲート）。
- P1 で `app/infra/text/normalize.py`（`TextNormalizer`。決定的・副作用なし）を実装し、
  評価ハーネスで「人手修正 → 正規化辞書還流 → 精度回復」の効果を実証済み。
  ただし**本番の取込パイプライン（IngestService）には未配線**（normalize.py の
  docstring にも「配線は P2 で行う」と明記）。
- 配線しないと、本番では表記ゆれ（「ろうすい」↔「漏水」等）が分類精度を下げたままになる。

## 設計（固定事項）

1. **port 追加**: `app/services/ports.py` に `TextNormalizerPort`（Protocol）を追加。
   ```python
   class TextNormalizerPort(Protocol):
       """表記ゆれ正規化。分類前にテキストを正規形へ揃える。"""
       def normalize(self, text: str) -> str: ...
   ```
   既存 `TextNormalizer` は structural typing でそのまま適合（infra 側の変更不要）。
   `NullNormalizer`（無変換）を `NULL_METRICS` と同じ流儀で ports.py に定義し既定値にする。
2. **適用位置**: `IngestService.ingest_from_key` の **マスキング後・分類前**。
   `masked.masked_text` を normalize してから `classify_report` に渡す。
   - **raw_text は正規化しない**（DB 保存は原文のまま。原本性維持）
   - 埋め込み・検索側への適用は今回やらない（対象外参照）
3. **対応表のロード**: `app/core/config.py` に
   `normalizer_corrections_path: str | None = None`（env: `NORMALIZER_CORRECTIONS_PATH`）
   を追加。`app/core/di.py` の `build_container` で
   path 指定あり → `TextNormalizer.from_file(path)`、なし → `NullNormalizer`（無変換）
   を生成し `IngestService` に注入。
   - 本番用対応表の初期値は `tests/llm_eval/golden_corrections.json` を
     `data/golden_corrections.json` 等へ**コピーしない**。運用還流で蓄積する前提のため、
     初期状態は「未設定＝無変換」でよい（P1 実証と本番運用の分離）
4. **アーキテクチャ制約**: services は infra を import しない（import-linter）。
   IngestService は `TextNormalizerPort` のみを知る。domain には手を入れない。

## 対象範囲

- `app/services/ports.py`（Protocol + NullNormalizer 追加）
- `app/services/ingest.py`（コンストラクタ引数追加・分類前の normalize 呼び出し）
- `app/core/config.py` / `app/core/di.py`（設定と注入）
- `tests/unit/test_ingest.py`（正規化が分類入力に効くことの検証を追加）
- `tests/unit/fakes.py`（必要なら Fake normalizer 追加）

## 検証手順

1. `make lint`（ruff / mypy strict / import-linter）green
2. `uv run pytest tests/unit` green（新規テスト含む）
3. `docker compose up → make demo` の回帰（正規化未設定＝無変換で挙動不変）

## 完了条件

- [ ] `TextNormalizerPort` と `NullNormalizer` が ports.py に定義されている
- [ ] IngestService がマスキング後・分類前に normalize を適用している
      （raw_text の保存値は原文のまま）
- [ ] `NORMALIZER_CORRECTIONS_PATH` 設定で `TextNormalizer.from_file` が注入され、
      未設定時は無変換で従来挙動と完全一致する
- [ ] ユニットテスト: 対応表を与えた Fake/実 normalizer で「分類器に渡るテキストが
      正規化済み」「raw_text は原文のまま保存」を検証し green
- [ ] `make lint` + `tests/unit` green（mypy strict の success ファイル数維持）
- [ ] PR 作成（`app/` + `tests/unit/` のみ。`prompts/**`・`tests/llm_eval/**` に触れず
      llm-regression（実API課金）を発火させない）

## 対象外（今回やらないこと）

- 検索クエリ側・埋め込みチャンク側への正規化適用（効果測定してから別判断）
- 本番用対応表ファイルの整備・S3 等からの動的ロード（運用還流の仕組みは後続）
- needs_review → 対応表への還流 UI/スクリプト（改善ループの自動化は別トラック）
- prompts / 評価ハーネスの変更

## ロールバック方法

- 未 apply・アプリ層のみの変更。`git revert` 1コミットで完結
- 緊急時は `NORMALIZER_CORRECTIONS_PATH` を未設定に戻すだけで無変換（従来挙動）に戻る
