/* Report Insight — モック用のダミーデータと共通処理。
   本物のDBは使わず、この配列と localStorage だけで完結する。
   ロールごとの見え方の違い（自支店のみ / 全社横断）は本番と同じルールを再現している。 */

const BRANCHES = { 1: "東京支店", 2: "大阪支店" };

const USERS = [
  { id: 1, email: "tokyo-mgr@example.com", name: "東京支店マネージャ", role: "branch_manager", branch_id: 1 },
  { id: 3, email: "osaka-mgr@example.com", name: "大阪支店マネージャ", role: "branch_manager", branch_id: 2 },
  { id: 2, email: "qa@example.com", name: "本社品質管理部", role: "qa", branch_id: null },
];

const PROPERTIES = [
  { id: 101, name: "新宿センタービル", branch_id: 1 },
  { id: 102, name: "品川ゲートタワー", branch_id: 1 },
  { id: 201, name: "梅田スカイオフィス", branch_id: 2 },
  { id: 202, name: "難波ビジネスセンター", branch_id: 2 },
];

const CATEGORY_LABELS = {
  cleaning: "清掃", equipment_failure: "設備異常", complaint: "クレーム", other: "その他",
};
const URGENCY_LABELS = { high: "高", medium: "中", low: "低" };
const STATUS_LABELS = {
  analyzed: "AI分析済", needs_review: "未分類（要確認）", human_verified: "人間確認済",
};

/* 手書きの代表例（受入テストで文面を読む用）＋ 量を出すための自動生成。 */
const SEED_REPORTS = [
  { id: 1001, property_id: 101, reported_at: "2026-07-18 08:12", category: "equipment_failure", urgency: "high", status: "analyzed", confidence: 0.94,
    summary: "3号機エレベーターが5階で停止、閉じ込めなし。保守会社へ連絡済み。",
    body: "朝の巡回中、3号機エレベーターが5階で停止しているのを確認しました。中に人はいませんでした。管理室の表示灯は異常を示しており、すぐに保守会社（東洋エレベーター）へ連絡。10時頃に技術者が来る予定です。テナント各社には掲示で周知しました。" },
  { id: 1002, property_id: 101, reported_at: "2026-07-18 09:40", category: "cleaning", urgency: "low", status: "analyzed", confidence: 0.97,
    summary: "1階エントランス床の定期清掃を実施。異常なし。",
    body: "1階エントランスの床清掃を通常どおり実施しました。特に汚損や破損は見当たりません。観葉植物の水やりも併せて実施済みです。" },
  { id: 1003, property_id: 102, reported_at: "2026-07-18 11:05", category: "equipment_failure", urgency: "high", status: "needs_review", confidence: 0.41,
    summary: "地下2階駐車場で天井から水が落ちている。原因不明。",
    body: "地下2階の駐車場、C区画あたりの天井から水がポタポタ落ちています。上は機械室なので配管かもしれませんが、雨も降っていたので雨水の可能性もあります。バケツを置いて応急処置しました。判断がつかないので確認をお願いします。" },
  { id: 1004, property_id: 102, reported_at: "2026-07-17 16:22", category: "complaint", urgency: "medium", status: "analyzed", confidence: 0.88,
    summary: "7階テナントより、隣室の空調音がうるさいとの申し出。",
    body: "7階のテナント様より、隣の部屋の空調の音が響いてうるさいというご意見をいただきました。実際に室内で確認したところ、確かに低い唸り音がします。空調設備の点検が必要かもしれません。" },
  { id: 1005, property_id: 201, reported_at: "2026-07-18 07:55", category: "equipment_failure", urgency: "medium", status: "needs_review", confidence: 0.52,
    summary: "屋上の排水溝に落ち葉が詰まりぎみ。要対応か判断できず。",
    body: "屋上を見回ったところ、北側の排水溝に落ち葉と土がたまっていました。今はまだ水は流れていますが、台風が来たら詰まるかもしれません。すぐ対応すべきか、次回の定期清掃でよいか判断がつきません。" },
  { id: 1006, property_id: 201, reported_at: "2026-07-17 14:30", category: "complaint", urgency: "high", status: "human_verified", confidence: 0.79,
    summary: "2階トイレの水漏れでテナント床が濡れた。クレームあり。",
    body: "2階の女子トイレの給水管から水漏れがあり、隣接するテナント様の床の一部が濡れてしまいました。強くお叱りを受けています。止水は完了、業者手配済みです。" },
  { id: 1007, property_id: 202, reported_at: "2026-07-16 10:10", category: "cleaning", urgency: "low", status: "analyzed", confidence: 0.95,
    summary: "共用部ガラス清掃を実施。破損等なし。",
    body: "1〜3階の共用部ガラス清掃を実施しました。特筆すべき異常はありません。" },
  { id: 1008, property_id: 202, reported_at: "2026-07-15 13:45", category: "other", urgency: "low", status: "needs_review", confidence: 0.38,
    summary: "近隣工事の粉じんについて記載。分類しづらい内容。",
    body: "隣の敷地で解体工事が始まり、粉じんが飛んできています。うちの建物の被害というほどではないですが、外壁が少し汚れています。念のため報告します。" },
];

/* 26件まで水増しして「50件超のページ送り」を確認できるようにする */
function buildReports() {
  const list = SEED_REPORTS.slice();
  const cats = ["cleaning", "equipment_failure", "complaint", "other"];
  const urgs = ["low", "medium", "low", "medium", "high"];
  const props = [101, 102, 201, 202];
  for (let i = 0; i < 46; i++) {
    const cat = cats[i % cats.length];
    const conf = i % 9 === 0 ? 0.44 : 0.9 + (i % 8) / 100;
    list.push({
      id: 1100 + i,
      property_id: props[i % props.length],
      reported_at: `2026-07-${String(14 - Math.floor(i / 8)).padStart(2, "0")} ${String(8 + (i % 9)).padStart(2, "0")}:${String((i * 7) % 60).padStart(2, "0")}`,
      category: cat,
      urgency: urgs[i % urgs.length],
      status: conf < 0.85 ? "needs_review" : "analyzed",
      confidence: Number(conf.toFixed(2)),
      summary: `${CATEGORY_LABELS[cat]}に関する定常報告（サンプル ${i + 1} 件目）。`,
      body: `これはページ送りと絞り込みの動作を確認するためのサンプル報告書です。分類は「${CATEGORY_LABELS[cat]}」、確信度は ${conf.toFixed(2)} です。`,
    });
  }
  return list;
}

/* ---- 状態（localStorage に保存し、画面をまたいで引き継ぐ） ---- */

const STORE_KEY = "ri_mock_state_v1";

function loadState() {
  const raw = localStorage.getItem(STORE_KEY);
  if (raw) { try { return JSON.parse(raw); } catch (e) { /* 壊れていたら作り直す */ } }
  const fresh = { uid: 1, reports: buildReports(), monthly: [], audit: [] };
  saveState(fresh);
  return fresh;
}
function saveState(s) { localStorage.setItem(STORE_KEY, JSON.stringify(s)); }
function resetState() { localStorage.removeItem(STORE_KEY); location.reload(); }

const State = loadState();

function currentUser() { return USERS.find((u) => u.id === State.uid) || USERS[0]; }
function setUser(uid) { State.uid = Number(uid); saveState(State); location.reload(); }

function isQa(user) { return user.role === "qa"; }

/* 本番の認可ルールと同じ: QA は全物件、支店管理者は自支店の物件のみ */
function permittedProperties(user) {
  return isQa(user) ? PROPERTIES : PROPERTIES.filter((p) => p.branch_id === user.branch_id);
}
function canSee(user, report) {
  return permittedProperties(user).some((p) => p.id === report.property_id);
}
function propertyName(id) {
  const p = PROPERTIES.find((x) => x.id === id);
  return p ? p.name : `(不明な物件 ${id})`;
}
function findReport(id) { return State.reports.find((r) => r.id === Number(id)); }

function logAudit(action, target, detail) {
  State.audit.unshift({
    at: new Date().toLocaleString("ja-JP"),
    actor: currentUser().email, action, target, detail,
  });
  saveState(State);
}

/* ---- 共通ヘッダ（ナビ＋利用者切替＝ログイン相当） ---- */

function renderTopbar(active) {
  const u = currentUser();
  const scope = isQa(u) ? "全支店を横断できます" : `${BRANCHES[u.branch_id]}のみ表示されます`;
  const opts = USERS.map(
    (x) => `<option value="${x.id}" ${x.id === u.id ? "selected" : ""}>${x.name}（${x.role}）</option>`
  ).join("");
  document.body.insertAdjacentHTML("afterbegin", `
    <div class="topbar">
      <div class="nav">
        <a href="index.html" ${active === "home" ? 'class="active"' : ""}>ホーム</a>
        <a href="submit.html" ${active === "submit" ? 'class="active"' : ""}>報告を投入<span class="mockflag" style="margin-left:4px">検査用</span></a>
        <a href="pipeline.html" ${active === "pipeline" ? 'class="active"' : ""}>データの流れ<span class="mockflag" style="margin-left:4px">検査用</span></a>
        <a href="admin.html" ${active === "admin" ? 'class="active"' : ""}>報告書</a>
        <a href="monthly-list.html" ${active === "monthly" ? 'class="active"' : ""}>月次報告書</a>
        <a href="audit.html" ${active === "audit" ? 'class="active"' : ""}>監査ログ</a>
        <a href="checklist.html" ${active === "checklist" ? 'class="active"' : ""}>テスト表</a>
      </div>
      <div class="whoami">
        <span>利用者</span>
        <select onchange="setUser(this.value)">${opts}</select>
        <span>${scope}</span>
        <button class="secondary" onclick="resetState()" title="ダミーデータを初期状態に戻します">リセット</button>
      </div>
    </div>
  `);
}

/* ---- 月次報告書のダミー生成 ---- */

function generateMonthly(propertyId, month) {
  const reports = State.reports.filter(
    (r) => r.property_id === Number(propertyId) && r.reported_at.startsWith(month)
  );
  const byCat = {};
  const byUrg = {};
  reports.forEach((r) => {
    byCat[r.category] = (byCat[r.category] || 0) + 1;
    byUrg[r.urgency] = (byUrg[r.urgency] || 0) + 1;
  });
  const needAction = reports.filter((r) => r.urgency === "high").length;
  const catRows = Object.keys(CATEGORY_LABELS)
    .map((k) => `| ${CATEGORY_LABELS[k]} | ${byCat[k] || 0} |`).join("\n");
  const urgRows = Object.keys(URGENCY_LABELS)
    .map((k) => `| ${URGENCY_LABELS[k]} | ${byUrg[k] || 0} |`).join("\n");

  const body = `# ${propertyName(propertyId)} 月次報告書（${month}）

## 概要

当月の報告件数は **${reports.length}件**、うち要対応（緊急度：高）は **${needAction}件** でした。

## 分類別件数

| 分類 | 件数 |
|---|---|
${catRows}

## 緊急度別件数

| 緊急度 | 件数 |
|---|---|
${urgRows}

## 所見

当月は設備異常の報告が中心でした。特にエレベーターおよび給排水設備に関する事象が複数確認されており、経年劣化の兆候がうかがえます。いずれも当日中に一次対応を完了しており、テナント様の業務への影響は限定的でした。次月以降は予防保全の観点から、該当設備の点検頻度の見直しをご提案いたします。

*（この「所見」の文章のみ AI が生成しています。上記の件数はすべてデータベースの集計値です）*
`;
  const rec = {
    id: Date.now(),
    property_id: Number(propertyId),
    month,
    status: "draft",
    version: 1,
    body,
    approved_by: null,
    approved_at: null,
  };
  State.monthly.unshift(rec);
  saveState(State);
  return rec;
}

/* ---- ダミーAI: 投入された文章を仕分けする ----
   本番は Claude が分類するが、モックではキーワードで代用する。
   「確信度が低いと未分類キューに落ちる」という挙動を再現するのが目的。 */

const CLASSIFY_RULES = [
  { category: "equipment_failure", words: ["水漏れ", "漏水", "雨漏り", "故障", "停止", "エレベーター", "空調", "配管", "異常", "破損", "不具合", "詰まり"] },
  { category: "complaint", words: ["クレーム", "苦情", "お叱り", "うるさい", "申し出", "ご意見", "不満", "指摘", "怒"] },
  { category: "cleaning", words: ["清掃", "掃除", "ワックス", "ゴミ", "ごみ", "床磨き", "水やり", "ガラス清掃"] },
];

const HIGH_WORDS = ["閉じ込め", "停止", "水漏れ", "漏水", "雨漏り", "けが", "怪我", "危険", "緊急", "お叱り", "止水", "感電", "火"];
const HEDGE_WORDS = ["かもしれません", "かもしれない", "判断がつかない", "わかりません", "分かりません", "念のため", "どちらとも", "確認をお願い", "よいか"];

function classifyText(text) {
  const hits = CLASSIFY_RULES.map((rule) => ({
    category: rule.category,
    score: rule.words.filter((w) => text.includes(w)).length,
  })).sort((a, b) => b.score - a.score);

  const top = hits[0];
  const second = hits[1];
  const category = top.score > 0 ? top.category : "other";

  // 定常の清掃報告は緊急度を上げない。危険語があるときだけ「高」に倒す
  const urgency = HIGH_WORDS.some((w) => text.includes(w))
    ? "high"
    : category === "cleaning" || top.score === 0 ? "low" : "medium";

  // 迷う条件: 現場が自信なさげ / 手がかりが無い / 複数分類が拮抗
  const hedging = HEDGE_WORDS.some((w) => text.includes(w));
  const tied = second && top.score > 0 && top.score === second.score;

  let confidence, reason;
  if (hedging) {
    confidence = 0.48;
    reason = "現場の記述に判断を保留する表現があり、確信を持てませんでした。";
  } else if (top.score === 0) {
    confidence = 0.36;
    reason = "手がかりになる記述が見つからず、分類できませんでした。";
  } else if (tied) {
    confidence = 0.48;
    reason = "複数の分類の可能性が同程度あり、絞り込めませんでした。";
  } else {
    confidence = Math.min(0.98, 0.86 + top.score * 0.04);
    const hit = CLASSIFY_RULES.find((r) => r.category === category)
      .words.filter((w) => text.includes(w));
    reason = `「${hit.join("」「")}」という記述から判断しました。`;
  }

  return {
    category,
    urgency,
    confidence: Number(confidence.toFixed(2)),
    status: confidence < 0.85 ? "needs_review" : "analyzed",
    reason,
  };
}

/* 要約は先頭2文を切り出す簡易版（本番は LLM が生成） */
function summarize(text) {
  const s = text.replace(/\s+/g, " ").split("。").filter(Boolean);
  return s.slice(0, 2).join("。") + (s.length ? "。" : "");
}

function submitReport(propertyId, text, reportedAt) {
  const a = classifyText(text);
  const rec = {
    id: Math.max(...State.reports.map((r) => r.id)) + 1,
    property_id: Number(propertyId),
    reported_at: reportedAt,
    category: a.category,
    urgency: a.urgency,
    status: a.status,
    confidence: a.confidence,
    summary: summarize(text),
    body: text,
    reason: a.reason,
    submitted_by_mock: true,
  };
  State.reports.unshift(rec);
  saveState(State);
  return rec;
}

/* ごく簡易な Markdown → HTML（プレビュー用。本番は markdown-it を使用） */
function mdToHtml(md) {
  const lines = md.split("\n");
  let html = "", inTable = false;
  for (const line of lines) {
    if (/^\|/.test(line)) {
      if (/^\|[\s:|-]+\|$/.test(line)) continue;
      const cells = line.split("|").slice(1, -1).map((c) => c.trim());
      if (!inTable) { html += "<table>"; inTable = true; }
      html += "<tr>" + cells.map((c) => `<td>${c}</td>`).join("") + "</tr>";
      continue;
    }
    if (inTable) { html += "</table>"; inTable = false; }
    if (/^# /.test(line)) html += `<h1>${line.slice(2)}</h1>`;
    else if (/^## /.test(line)) html += `<h2>${line.slice(3)}</h2>`;
    else if (line.trim() === "") html += "";
    else html += `<p>${line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/^\*(.+)\*$/, "<em>$1</em>")}</p>`;
  }
  if (inTable) html += "</table>";
  return html;
}
