/* docs/mockups/testcases.js から docs/12_uat_cases.md を生成する。
   テストケースの正本は testcases.js 側。ドキュメントは常にここから作り直すこと。
   使い方: node scripts/gen_uat_doc.mjs */

import { readFileSync, writeFileSync } from "node:fs";

const SRC = "docs/mockups/testcases.js";
const DEST = "docs/12_uat_cases.md";

// testcases.js は素の <script> 用ファイルなので、評価して定数を取り出す
const src = readFileSync(SRC, "utf8");
const UAT_GROUPS = new Function(`${src}; return UAT_GROUPS;`)();

const total = UAT_GROUPS.reduce((n, g) => n + g.cases.length, 0);
const autoCount = UAT_GROUPS.reduce((n, g) => n + g.cases.filter((c) => c.auto).length, 0);
const manualCount = total - autoCount;
const byWhere = (w) =>
  UAT_GROUPS.reduce((n, g) => n + g.cases.filter((c) => c.where === w).length, 0);

const out = [];
out.push("# 受入テストケース — Report Insight", "");
out.push("> **このファイルは自動生成です。** 直接編集せず、`docs/mockups/testcases.js` を直してから");
out.push("> `node scripts/gen_uat_doc.mjs` を実行すること。", "");
out.push("クライアントの3大課題（報告書の確認負荷／過去事例の属人化／月次報告書の作成負荷）が");
out.push("実際に解決されているかを、**利用者の立場ごとに手で確認する**ためのケース一覧。", "");
out.push(`全 ${total} ケース（モックで実施 ${byWhere("モック")} 件 / 本体を起動して実施 ${byWhere("本体")} 件）。`, "");
out.push(
  `うち ${autoCount} 件はパイプラインの振り分けを機械判定できるため \`make scenario\`（および「受入シナリオ」画面）で自動化済み。` +
  `**人が手で確認するのは残り ${manualCount} 件**（文章の妥当性・画面の操作性・権限の見え方など、人にしか判断できないもの）。`,
  "",
);

out.push("## 進め方", "");
out.push("**実施環境は本体のみ**（2026-07-21 整理。モック 8100 は受入テストから退役）。", "");
out.push("```bash");
out.push("LLM_PROVIDER=anthropic docker compose up -d   # 実APIで起動");
out.push("make migrate && make demo                     # 初回のみ（100件投入）");
out.push("```");
out.push("");
out.push("1. 自動判定分は <http://localhost:8000/scenarios> で各『実行』を押す（または `make scenario`）");
out.push("2. 手動分は各ケースの URL を開き、**画面上部の利用者セレクタで立場を切り替えてから**操作する");
out.push("3. 結果を下表の「判定」に記入する", "");

out.push("## 立場（ロール）", "");
out.push("| 立場 | uid | 見える範囲 | 月次 |");
out.push("|---|---|---|---|");
out.push("| 東京支店マネージャ | 1 | 第一グランドビル / サンライズ集合住宅 / みどり台レジデンス（69件） | 作成・承認可 |");
out.push("| 大阪支店マネージャ | 3 | なにわタワー / 堺筋テラス（31件） | 作成・承認可 |");
out.push("| 本社品質管理部 | 2 | 全5物件を横断（100件） | **閲覧のみ** |");
out.push("");

for (const g of UAT_GROUPS) {
  out.push(`## ${g.id}. ${g.title}`, "");
  out.push(g.intro, "");
  for (const c of g.cases) {
    out.push(`### ${c.id}`, "");
    out.push("| 項目 | 内容 |");
    out.push("|---|---|");
    out.push(`| 立場 | ${c.role} |`);
    out.push(`| 実施場所 | ${c.where} |`);
    out.push(`| 対応要件 | ${c.req} |`);
    out.push(`| 前提 | ${c.pre} |`);
    out.push(`| 手順 | ${c.steps.map((s, i) => `${i + 1}. ${s}`).join("<br>")} |`);
    out.push(`| 期待する結果 | ${c.expect} |`);
    out.push(
      c.auto
        ? `| 判定 | 自動（\`${c.auto}\`・受入シナリオ画面）。手動確認は任意 |`
        : `| 判定 | ☐ OK　☐ NG |`,
    );
    out.push("");
  }
}

writeFileSync(DEST, out.join("\n"));
console.log(`generated ${DEST} (${total} cases)`);
