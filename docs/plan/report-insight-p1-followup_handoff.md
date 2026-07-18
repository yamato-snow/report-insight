---
date: 2026-07-18
model: opus
status: draft
issue: ""
topic: report-insight P1 フォローアップ（CI緑化→実アプリスモーク→リポジトリ整備）実行引き継ぎ
predecessor: report-insight-p1_plan.md
---

# report-insight P1 フォローアップ 実行引き継ぎ（別Opusセッション用）

このファイルは **P1 実装完了後の「実行・検証・整備」だけ**を新しい Opus セッションへ渡すための handoff。
設計判断は含まない（含まれたら中断して報告）。作業ディレクトリは
`/Volumes/My_SSD/Sandbox/yukikobo/products/report-insight`。

---

## 現在地（2026-07-18）

- **実装**: P1 計画 `docs/plan/report-insight-p1_plan.md` の §4 全タスク（F-3〜4.6）を実装し `main` にマージ済み。
- **リモート**: `origin = github.com/yamato-snow/report-insight.git`。
  - `origin/main` = `d343362`（push 済み）
  - **ローカル `main` = `5d03b7a`（未push・1コミット先行）** … 内容は下記②の CI 修正。
- **CI（GitHub Actions）現況**: 直近 main 実行で**実ゲートは全て green**
  （lint / unit / integration / gitleaks / sast(bandit) / sca(pip-audit)）。
  `build` ジョブのみ `aquasecurity/trivy-action@0.28.0`（存在しないタグ）で解決失敗していた。
  → **修正コミット `5d03b7a` 済み**（`@v0.30.0` に是正。`iac-scan` 側の同参照も同時修正）。**未検証（未push）**。
- **ローカル差分**: `docs/presentations/`（PDF/PPTX・約2.5MB）が**未追跡**のまま。
  マージ済みローカルブランチ6本＋`docs/runbook` が残存。
- **品質ゲート（ローカル最終確認済み）**: `make lint` green / unit 29 / integration 21。

---

## 完了条件（このセッションのゴール）

必須（無料・すぐ）
- [ ] ① 未pushの CI 修正（`5d03b7a`）を `origin/main` へ push
- [ ] ② push 後の main CI が **全ジョブ green**（`build`＝Docker build→Trivy(image)→SBOM を含む）
- [ ] ③ 実アプリスモーク: `make up && make migrate && make demo` が成功（100件が S3→SQS→worker→DB 通過）
- [ ] ④ **コンテナ実物の PDF 検証**: F-3 月次を生成→承認→`GET /api/v1/monthly-reports/{id}/pdf` が
      WeasyPrint で実 PDF を返す（ホストで検証不可だった箇所。integration は Fake レンダラだった）
- [ ] ⑤ F-4 管理画面をブラウザで表示確認（一覧・フィルタ・未分類キュー・月次承認）

整備（軽作業）
- [ ] ⑥ `main` ブランチ保護を設定（必須チェック: lint / unit / integration / gitleaks / sast / sca）
- [ ] ⑦ `docs/presentations/` の扱いを決定（`.gitignore` 追記 or commit or 削除）
- [ ] ⑧ マージ済みローカルブランチを削除

任意（コスト/認証ゲートあり・ユーザー確認必須）
- [ ] ⑨ `make eval` 実走＋README ステータス記録（要 `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY`・約¥300）
      ＋ GitHub 側に `ANTHROPIC_API_KEY` secret と `llm-eval` environment を設定（未設定だと
      prompts 変更時の `llm-regression` ジョブが落ちる）
- [ ] ⑩ `terraform plan`（envs/dev・ダミーtfvars。要 AWS 認証。plan 計画 §4.4 の残り完了条件）

---

## 手順

### ① / ② CI 緑化
```bash
cd /Volumes/My_SSD/Sandbox/yukikobo/products/report-insight
git log --oneline origin/main..main      # 5d03b7a が push 対象であることを確認
git push origin main                      # ← 外向き操作。実行前にユーザー確認
gh run watch                              # 直近 run を追跡。build が green か確認
gh run list --limit 3
```
- build が落ちたら `gh run view <id> --log-failed` で原因確認。Trivy(image) が Critical CVE で
  落ちる場合は `ignore-unfixed: true` 済みなので、通常はベースイメージ更新（Dockerfile）で対応。

### ③〜⑤ 実アプリスモーク（Docker 必須）
```bash
make up && make migrate && make demo      # フルパイプライン（緊急通知は webhook-mock で確認）
```
その後 F-3 PDF を実物確認（seed 済み物件で月次を生成）:
```bash
# 例: property_id は seed_demo が作る物件ID（make demo のログ / DB で確認）
curl -s -XPOST localhost:8000/api/v1/monthly-reports \
  -H 'X-User-Id: 2' -H 'content-type: application/json' \
  -d '{"property_id": <PID>, "month": "2026-06-01"}'          # → 202, id を控える
curl -s localhost:8000/api/v1/monthly-reports/<id> -H 'X-User-Id: 2'   # draft を確認
curl -s -XPATCH localhost:8000/api/v1/monthly-reports/<id> \
  -H 'X-User-Id: 2' -H 'content-type: application/json' -d '{"action":"approve"}'
curl -s localhost:8000/api/v1/monthly-reports/<id>/pdf -H 'X-User-Id: 2' -o /tmp/monthly.pdf
file /tmp/monthly.pdf                                          # → PDF document であること
```
F-4 管理画面はブラウザで `http://localhost:8000/`（UI ルート）や `/reports` 系を確認
（`X-User-Id` ヘッダ認証。実ルートは `app/api/routers/ui.py` / `reports.py` を参照）。

### ⑥ ブランチ保護
```bash
gh api -X PUT repos/yamato-snow/report-insight/branches/main/protection \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[contexts][]=lint' \
  -f 'required_status_checks[contexts][]=unit' \
  -f 'required_status_checks[contexts][]=integration' \
  -f 'required_status_checks[contexts][]=gitleaks' \
  -f 'required_status_checks[contexts][]=sast' \
  -f 'required_status_checks[contexts][]=sca' \
  -F 'enforce_admins=true' -F 'required_pull_request_reviews=null' -F 'restrictions=null'
```
（GUI 設定でも可。まず①②で green を確認してから設定すること。）

### ⑦ presentations の扱い（ユーザーに確認）
- 成果物として残すなら commit、リポジトリを軽く保つなら `.gitignore` に `docs/presentations/` 追記。

### ⑧ ブランチ削除
```bash
git branch --merged main | grep -E 'feat/|docs/runbook' | xargs -n1 git branch -d
```

---

## 対象外（今回やらない）

- **P2**: AWS dev への `terraform apply` / OIDC デプロイジョブ / スモーク→承認→prod / デモ動画。
  詳細は `docs/plan/report-insight-p1_plan.md` §6 が正。
- 新機能・UX作り込み・アーキ変更（発生したら handoff の範囲外＝中断して報告・必要なら Fable 昇格）。

## 前提が崩れたら

- 軽微（コマンド差異・ポート等）→ `仮定:` を明記して続行。
- 重大（CI 修正しても build が別要因で落ちる／実PDFが壊れている等の設計起因）→ 中断して報告。

## ロールバック

- CI 修正の取り消し: `git revert 5d03b7a`（push 済みなら revert コミットを push）。
- ローカル環境: `make down-v` で DB 含め再構築。新規外部副作用なし（apply は対象外）。

---

## 新セッションでの起動

Opus の新セッションで一言:

> `docs/plan/report-insight-p1-followup_handoff.md に従って実行して`
