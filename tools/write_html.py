# -*- coding: utf-8 -*-
html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 问数</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif;background:#f5f6fa;color:#1a1a2e;min-height:100vh}
header{display:flex;align-items:center;gap:12px;padding:14px 32px;background:#fff;border-bottom:1px solid #e8eaf0;position:sticky;top:0;z-index:10}
.brand-icon{font-size:22px}.brand-name{font-size:18px;font-weight:700;color:#2563eb}.brand-sub{font-size:13px;color:#9ca3af;flex:1;margin-left:4px}
main{max-width:960px;margin:0 auto;padding:32px 24px;display:flex;flex-direction:column;gap:20px}
.input-card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;display:flex;gap:12px;align-items:flex-end;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.input-card textarea{flex:1;border:none;outline:none;resize:none;font-size:15px;line-height:1.6;font-family:inherit;color:#1a1a2e;background:transparent}
.input-card textarea::placeholder{color:#9ca3af}
.btn-primary{padding:10px 24px;background:#2563eb;color:#fff;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;min-width:88px;transition:background .2s}
.btn-primary:hover:not(:disabled){background:#1d4ed8}.btn-primary:disabled{opacity:.5;cursor:not-allowed}
.btn-ghost{padding:6px 14px;background:transparent;border:1px solid #d1d5db;border-radius:6px;font-size:13px;color:#374151;cursor:pointer}
.btn-ghost:hover{background:#f3f4f6}.btn-ghost.sm{padding:3px 10px;font-size:12px}
.examples{display:flex;flex-wrap:wrap;gap:8px}
.chip{padding:6px 14px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:20px;font-size:13px;color:#2563eb;cursor:pointer;transition:background .15s}
.chip:hover{background:#dbeafe}
.result-card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06);display:none}
.result-card.visible{display:block}
.summary-box{display:flex;align-items:flex-start;gap:10px;padding:14px 16px;background:linear-gradient(135deg,#eff6ff,#f0fdf4);border-bottom:1px solid #e5e7eb}
.summary-icon{font-size:18px;flex-shrink:0;margin-top:1px}
.summary-text{font-size:15px;line-height:1.7;color:#1e3a5f;font-weight:500}
.sql-block{border-bottom:1px solid #f3f4f6}
.sql-header{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;font-size:12px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;background:#f9fafb}
.sql-code{padding:12px 16px;font-size:13px;font-family:"Cascadia Code","Consolas",monospace;color:#1e40af;white-space:pre-wrap;word-break:break-all;background:#f0f4ff;line-height:1.6}
.result-meta{padding:10px 16px;font-size:13px;color:#6b7280;border-bottom:1px solid #f3f4f6}
.table-wrap{overflow-x:auto;max-height:420px;overflow-y:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
th{background:#f9fafb;padding:10px 14px;text-align:left;font-weight:600;color:#374151;border-bottom:1px solid #e5e7eb;white-space:nowrap;position:sticky;top:0}
td{padding:9px 14px;color:#1a1a2e;border-bottom:1px solid #f3f4f6}
tr:last-child td{border-bottom:none}tr:hover td{background:#f9fafb}
.error-box{padding:16px;color:#dc2626;font-size:14px}
.empty-tip{padding:24px 16px;text-align:center;color:#9ca3af;font-size:14px}
.history-title{font-size:12px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:.05em}
.history-list{display:flex;flex-direction:column;gap:6px;margin-top:8px}
.history-item{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;cursor:pointer;transition:background .15s;gap:12px}
.history-item:hover{background:#f9fafb}.history-q{font-size:14px;color:#374151;flex:1}.history-meta{font-size:12px;color:#9ca3af;white-space:nowrap}
.schema-panel{background:#1e1e2e;color:#cdd6f4;padding:20px 32px;max-height:360px;overflow:auto;display:none}
.schema-panel.visible{display:block}.schema-panel pre{font-size:13px;line-height:1.7;font-family:monospace}
@keyframes spin{to{transform:rotate(360deg)}}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle}
</style>
</head>
<body>
<header>
  <span class="brand-icon">&#9889;</span>
  <span class="brand-name">AI 问数</span>
  <span class="brand-sub">自然语言数据库查询</span>
  <button class="btn-ghost" id="schemaBtn" onclick="toggleSchema()">查看表结构</button>
</header>
<div class="schema-panel" id="schemaPanel"><pre id="schemaText">加载中…</pre></div>
<main>
  <div class="input-card">
    <textarea id="question" rows="3"
      placeholder="用中文描述你想查询的内容，按 Enter 发送（Shift+Enter 换行）"
      onkeydown="handleKey(event)"></textarea>
    <button class="btn-primary" id="queryBtn" onclick="doQuery()">查询</button>
  </div>
  <div class="examples" id="examples"></div>
  <div class="result-card" id="resultCard">
    <div class="summary-box" id="summaryBox" style="display:none">
      <span class="summary-icon">&#129504;</span>
      <span class="summary-text" id="summaryText"></span>
    </div>
    <div class="sql-block" id="sqlBlock">
      <div class="sql-header">
        <span>生成的 SQL</span>
        <button class="btn-ghost sm" onclick="toggleSql()">收起</button>
      </div>
      <pre class="sql-code" id="sqlCode"></pre>
    </div>
    <div id="resultBody"></div>
  </div>
  <div id="historySection" style="display:none">
    <div class="history-title">历史查询</div>
    <div class="history-list" id="historyList"></div>
  </div>
</main>
<script>
const BASE = 'http://localhost:8100';
const EXAMPLES = [
  '在建项目有哪些？','每种合同类型各有多少条？',
  '总合同金额最高的前5个项目','有哪些付款是逾期未付的？',
  '智慧园区项目下所有合同的变更情况','已完成合同的质保金退还了多少？',
  '各项目的施工合同金额汇总','待审批的变更有哪些？金额是多少？',
];
let history = [], sqlVisible = true, schemaLoaded = false, schemaVisible = false;

const exBox = document.getElementById('examples');
EXAMPLES.forEach(q => {
  const btn = document.createElement('button');
  btn.className = 'chip'; btn.textContent = q;
  btn.onclick = () => doQuery(q); exBox.appendChild(btn);
});

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doQuery(); }
}

async function toggleSchema() {
  schemaVisible = !schemaVisible;
  document.getElementById('schemaPanel').classList.toggle('visible', schemaVisible);
  document.getElementById('schemaBtn').textContent = schemaVisible ? '隐藏表结构' : '查看表结构';
  if (schemaVisible && !schemaLoaded) {
    try {
      const d = await (await fetch(BASE + '/api/schema')).json();
      document.getElementById('schemaText').textContent = d.schema;
      schemaLoaded = true;
    } catch(e) {
      document.getElementById('schemaText').textContent = '加载失败：' + e.message;
    }
  }
}

function toggleSql() {
  sqlVisible = !sqlVisible;
  document.getElementById('sqlCode').style.display = sqlVisible ? '' : 'none';
  document.querySelector('#sqlBlock .btn-ghost').textContent = sqlVisible ? '收起' : '展开';
}

async function doQuery(q) {
  const ta = document.getElementById('question');
  const text = (q !== undefined ? q : ta.value).trim();
  if (!text) return;
  ta.value = text;
  const btn = document.getElementById('queryBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  document.getElementById('resultCard').classList.remove('visible');
  try {
    const res = await fetch(BASE + '/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: text }),
    });
    const data = await res.json();
    showResult(data); addHistory(text, data);
  } catch(e) {
    showResult({ sql: '', columns: [], rows: [], row_count: 0, error: '请求失败：' + e.message });
  } finally {
    btn.disabled = false; btn.textContent = '查询';
  }
}

function showResult(data) {
  document.getElementById('resultCard').classList.add('visible');

  // 自然语言摘要
  const summaryBox = document.getElementById('summaryBox');
  const summaryText = document.getElementById('summaryText');
  if (data.summary) {
    summaryText.textContent = data.summary;
    summaryBox.style.display = 'flex';
  } else {
    summaryBox.style.display = 'none';
  }

  const sqlBlock = document.getElementById('sqlBlock');
  if (data.sql) {
    document.getElementById('sqlCode').textContent = data.sql;
    sqlBlock.style.display = '';
    sqlVisible = true;
    document.getElementById('sqlCode').style.display = '';
    document.querySelector('#sqlBlock .btn-ghost').textContent = '收起';
  } else { sqlBlock.style.display = 'none'; }

  const body = document.getElementById('resultBody');
  if (data.error) { body.innerHTML = '<div class="error-box">❌ ' + escHtml(data.error) + '</div>'; return; }
  if (data.row_count === 0) { body.innerHTML = '<div class="empty-tip">查询成功，暂无数据</div>'; return; }

  let html = '<div class="result-meta">共 ' + data.row_count + ' 条结果</div><div class="table-wrap"><table><thead><tr>';
  data.columns.forEach(c => { html += '<th>' + escHtml(c) + '</th>'; });
  html += '</tr></thead><tbody>';
  data.rows.forEach(row => {
    html += '<tr>';
    row.forEach(cell => { html += '<td>' + (cell !== null ? escHtml(String(cell)) : '—') + '</td>'; });
    html += '</tr>';
  });
  html += '</tbody></table></div>';
  body.innerHTML = html;
}

function addHistory(question, data) {
  history.unshift({ question, data, time: new Date().toLocaleTimeString() });
  if (history.length > 20) history.pop();
  renderHistory();
}

function renderHistory() {
  const sec = document.getElementById('historySection');
  const list = document.getElementById('historyList');
  sec.style.display = history.length ? '' : 'none';
  list.innerHTML = history.map((item, i) =>
    '<div class="history-item" onclick="restoreHistory(' + i + ')">' +
    '<span class="history-q">' + escHtml(item.question) + '</span>' +
    '<span class="history-meta">' + item.time + ' · ' +
    (item.data.error ? '❌' : item.data.row_count + ' 条') + '</span></div>'
  ).join('');
}

function restoreHistory(i) {
  const item = history[i];
  document.getElementById('question').value = item.question;
  showResult(item.data);
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
</script>
</body>
</html>"""

with open('D:/claude/text2sql/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print('写入完成，字节数:', len(html.encode('utf-8')))
