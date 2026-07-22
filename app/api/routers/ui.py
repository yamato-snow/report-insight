"""UAT用の簡易検査UI（開発補助）。

本番機能ではなく、受け入れ試験を実画面で行うための最小フロント。
/api/v1/search（SSE）を fetch で叩き、sources→token→done を逐次表示する。
バックエンド仕様には一切触れない（読み取り専用のクライアント）。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"])

_PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Report Insight — 検査UI</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, "Hiragino Sans", sans-serif;
         margin: 0; padding: 24px; max-width: 900px; margin-inline: auto;
         line-height: 1.6; }
  h1 { font-size: 1.25rem; margin: 0 0 4px; }
  .sub { color: #888; font-size: .85rem; margin: 0 0 20px; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  label { font-size: .8rem; color: #888; display: block; margin-bottom: 2px; }
  select, input[type=text] { padding: 8px 10px; border: 1px solid #8886;
    border-radius: 8px; background: transparent; color: inherit; font-size: .95rem; }
  input[type=text] { flex: 1; min-width: 240px; }
  button { padding: 8px 18px; border: 0; border-radius: 8px; cursor: pointer;
    background: #2563eb; color: #fff; font-size: .95rem; }
  button:disabled { opacity: .5; cursor: default; }
  .field { flex: 1; min-width: 200px; }
  .card { border: 1px solid #8883; border-radius: 12px; padding: 16px; margin-top: 20px; }
  .card h2 { font-size: .8rem; text-transform: uppercase; letter-spacing: .05em;
    color: #888; margin: 0 0 10px; }
  .src { border-left: 3px solid #2563eb55; padding: 4px 0 4px 12px; margin: 8px 0;
    font-size: .9rem; }
  .src .id { font-family: ui-monospace, monospace; color: #2563eb; font-weight: 600; }
  .src .date { color: #888; font-size: .8rem; margin-left: 6px; }
  #answer { white-space: pre-wrap; min-height: 1.6em; }
  .cite { display: inline-block; background: #2563eb22; color: #2563eb;
    border-radius: 6px; padding: 0 6px; font-family: ui-monospace, monospace;
    font-size: .82rem; }
  .meta { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 12px;
    font-size: .82rem; color: #888; }
  .meta b { color: inherit; font-weight: 600; }
  .empty { color: #d97706; font-weight: 600; }
  .err { color: #dc2626; }
  .examples { margin-top: 8px; font-size: .82rem; color: #888; }
  .examples a { color: #2563eb; cursor: pointer; text-decoration: none; margin-right: 12px; }
</style>
</head>
<body>
  <h1>Report Insight — 検査UI</h1>
  <p class="sub">受け入れ試験用の最小クライアント。<code>POST /api/v1/search</code> を SSE で呼び出します。</p>

  <div class="row" style="margin-bottom:12px">
    <div>
      <label for="user">利用者（X-User-Id / 認可フィルタ）</label>
      <select id="user">
        <option value="1">1 — 東京支店マネージャ（自支店のみ）</option>
        <option value="3">3 — 大阪支店マネージャ（自支店のみ）</option>
        <option value="2">2 — QA（全社横断）</option>
        <option value="999">999 — 不明な利用者（401 期待）</option>
        <option value="">（ヘッダ無し・401 期待）</option>
      </select>
    </div>
  </div>

  <div class="row">
    <div class="field">
      <label for="q">検索クエリ（自然言語）</label>
      <input id="q" type="text" placeholder="例: エレベーターの故障事例" value="水漏れの対応事例">
    </div>
    <button id="go">検索</button>
  </div>
  <div class="examples">
    例:
    <a data-q="エレベーターの故障事例">エレベーター故障</a>
    <a data-q="水漏れの対応事例">水漏れ</a>
    <a data-q="入居者からの騒音の苦情">騒音クレーム</a>
    <a data-q="宇宙ステーションの月面基地">無関係クエリ</a>
  </div>

  <div class="card" id="sourcesCard" style="display:none">
    <h2>参照した報告書（sources）</h2>
    <div id="sources"></div>
  </div>

  <div class="card" id="answerCard" style="display:none">
    <h2>生成された回答（token → done）</h2>
    <div id="answer"></div>
    <div class="meta" id="meta"></div>
  </div>

<script>
const $ = (s) => document.querySelector(s);

document.querySelectorAll('.examples a').forEach(a =>
  a.addEventListener('click', () => { $('#q').value = a.dataset.q; run(); }));
$('#go').addEventListener('click', run);
$('#q').addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });

function esc(s){ return s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

async function run() {
  const q = $('#q').value.trim();
  if (!q) return;
  const uid = $('#user').value;
  $('#go').disabled = true;
  $('#sourcesCard').style.display = 'none';
  $('#answerCard').style.display = 'block';
  $('#sources').innerHTML = '';
  $('#answer').innerHTML = '<span style="color:#888">…検索中</span>';
  $('#meta').innerHTML = '';

  const headers = { 'Content-Type': 'application/json' };
  if (uid !== '') headers['X-User-Id'] = uid;

  let resp;
  try {
    resp = await fetch('/api/v1/search', {
      method: 'POST', headers, body: JSON.stringify({ query: q }),
    });
  } catch (e) {
    $('#answer').innerHTML = '<span class="err">通信エラー: ' + esc(String(e)) + '</span>';
    $('#go').disabled = false; return;
  }

  if (!resp.ok) {
    let detail = resp.status + ' ' + resp.statusText;
    try { const j = await resp.json(); if (j.detail) detail += ' — ' + j.detail; } catch {}
    $('#answer').innerHTML = '<span class="err">HTTP ' + esc(detail) + '</span>';
    $('#go').disabled = false; return;
  }

  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = '', answer = '';
  $('#answer').textContent = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\\n\\n')) >= 0) {
      const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
      handleEvent(chunk, (t) => { answer += t; renderAnswer(answer); });
    }
  }
  $('#go').disabled = false;
}

function handleEvent(chunk, onToken) {
  let ev = 'message', data = '';
  for (const line of chunk.split('\\n')) {
    if (line.startsWith('event:')) ev = line.slice(6).trim();
    else if (line.startsWith('data:')) data += line.slice(5).trim();
  }
  let payload = {};
  try { payload = JSON.parse(data); } catch { return; }

  if (ev === 'sources') {
    $('#sourcesCard').style.display = 'block';
    $('#sources').innerHTML = (payload.reports || []).map(r =>
      '<div class="src"><span class="id">report:' + r.id + '</span>' +
      '<span class="date">' + esc(r.reported_at || '') + '</span><br>' +
      esc(r.summary || '') + '</div>').join('') ||
      '<span class="empty">該当報告書なし</span>';
  } else if (ev === 'token') {
    onToken(payload.text || '');
  } else if (ev === 'no_results') {
    $('#answer').innerHTML = '<span class="empty">該当する事例が見つかりませんでした（0件ショートサーキット）</span>';
  } else if (ev === 'done') {
    const c = (payload.citations || []).map(id =>
      '<span class="cite">report:' + id + '</span>').join(' ') || '—';
    // 非機能要件(3秒)の対象は「読み始められるまで」= first_token_ms。基準超過は赤で示す。
    const ftt = payload.first_token_ms ?? null;
    const slow = ftt !== null && ftt > 3000;
    $('#meta').innerHTML =
      '<span>引用: ' + c + '</span>' +
      '<span>検索 <b>' + (payload.retrieval_ms ?? '—') + '</b> ms</span>' +
      '<span' + (slow ? ' class="err"' : '') + '>初回表示 <b>' + (ftt ?? '—') + '</b> ms' +
        (slow ? ' ⚠ 基準3秒超' : '') + '</span>' +
      '<span>生成完了 <b>' + (payload.latency_ms ?? '—') + '</b> ms</span>' +
      '<span>in <b>' + (payload.input_tokens ?? '—') + '</b> tok</span>' +
      '<span>out <b>' + (payload.output_tokens ?? '—') + '</b> tok</span>';
  } else if (ev === 'error') {
    $('#answer').innerHTML = '<span class="err">エラー: ' + esc(payload.detail || data) + '</span>';
  }
}

function renderAnswer(text) {
  $('#answer').innerHTML = esc(text).replace(/\\[report:(\\d+)\\]/g,
    '<span class="cite">report:$1</span>');
}
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> HTMLResponse:
    """UAT検査UI（ルート）。"""
    return HTMLResponse(_PAGE)
