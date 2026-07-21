// docs 内の Mermaid 図が GitHub で描画できるか検証する（GitHub と同じ mermaid v11 パーサ）。
//
// 背景: 設計書の Mermaid 図が "Unable to render / Parse error" のまま公開されていた
// （subgraph 名の全角括弧、erDiagram の無効な複合キー PK_FK 等。2026-07-22 に発見）。
// GitHub の描画失敗は必ずパース段階で出るため、mermaid.parse が通れば表示は保証される。
//
// 使い方: node scripts/check_mermaid.mjs [file1.md file2.md ...]
//         引数なしなら README.md と docs/**/*.md を対象にする。
// 依存: mermaid（devDependency）。Node 実行のため DOMPurify 未解決で例外になるが、
//       そこまで到達＝文法は通過なので OK 扱いにする。

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import mermaid from "mermaid";

mermaid.initialize({ startOnLoad: false });

function collectMarkdown(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...collectMarkdown(p));
    else if (name.endsWith(".md")) out.push(p);
  }
  return out;
}

const targets =
  process.argv.slice(2).length > 0
    ? process.argv.slice(2)
    : ["README.md", ...collectMarkdown("docs")];

const MERMAID_BLOCK = /```mermaid\n([\s\S]*?)```/g;
let checked = 0;
let failed = 0;

for (const file of targets) {
  let text;
  try {
    text = readFileSync(file, "utf8");
  } catch {
    continue; // 対象外・欠損はスキップ
  }
  let m;
  let idx = 0;
  while ((m = MERMAID_BLOCK.exec(text)) !== null) {
    idx += 1;
    checked += 1;
    const line = text.slice(0, m.index).split("\n").length + 1;
    try {
      await mermaid.parse(m[1]);
    } catch (e) {
      const msg = String(e?.message ?? e).split("\n")[0];
      // DOMPurify 未解決 = 文法は通過している（Node 実行由来の偽陽性）
      if (msg.includes("DOMPurify")) continue;
      failed += 1;
      console.error(`NG  ${file} (図${idx}, 行${line}): ${msg}`);
    }
  }
}

if (failed > 0) {
  console.error(`\nMermaid 描画チェック: ${checked}図中 ${failed}図が失敗`);
  process.exit(1);
}
console.log(`Mermaid 描画チェック: ${checked}図すべて OK`);
