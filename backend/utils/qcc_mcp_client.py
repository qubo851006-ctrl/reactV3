"""
企查查 (QCC) MCP 客户端

对接 6 个独立 HTTP MCP 端点，所有工具统一使用 searchKey 参数。

端点：
  company   基本工商信息
  risk      风险信息
  ipr       知识产权
  operation 经营信息
  executive 高管信息
  history   历史信息

对外接口与 utils/mcp_client.py 保持一致：
  query_company(company_name, categories) -> dict
  format_company_markdown(result) -> str
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from config import QCC_TOKEN, AI_HTTP_VERIFY_SSL

logger = logging.getLogger(__name__)

# ── 端点 URL ─────────────────────────────────────────────────────────────────
_ENDPOINT_URLS: dict[str, str] = {
    "company":   "https://agent.qcc.com/mcp/company/stream",
    "risk":      "https://agent.qcc.com/mcp/risk/stream",
    "ipr":       "https://agent.qcc.com/mcp/ipr/stream",
    "operation": "https://agent.qcc.com/mcp/operation/stream",
    "executive": "https://agent.qcc.com/mcp/executive/stream",
    "history":   "https://agent.qcc.com/mcp/history/stream",
}

# ── 每个类别预设调用的工具（工具名, 展示标题）────────────────────────────────
# 全部工具均使用 searchKey 参数（企业名称或统一社会信用代码）
_CATEGORY_TOOLS: dict[str, list[tuple[str, str]]] = {
    "company": [
        ("get_company_registration_info", "工商登记信息"),
        ("get_key_personnel",             "主要人员"),
        ("get_shareholder_info",          "股东结构"),
    ],
    "risk": [
        ("get_dishonest_info",        "失信被执行"),
        ("get_judgment_debtor_info",  "被执行信息"),
        ("get_case_filing_info",      "立案信息"),
        ("get_business_exception",    "经营异常"),
        ("get_serious_violation",     "严重违法"),
        ("get_administrative_penalty","行政处罚"),
    ],
    # ipr / operation / executive / history：动态发现后全部调用
}

_ENDPOINT_LABELS: dict[str, tuple[str, str]] = {
    "company":   ("🏢", "基本信息"),
    "risk":      ("⚠️", "风险信息"),
    "ipr":       ("💡", "知识产权"),
    "operation": ("📊", "经营信息"),
    "executive": ("👔", "高管信息"),
    "history":   ("📋", "历史信息"),
}

_DEFAULT_CATEGORIES = ["company", "risk"]


# ── MCP 协议底层 ─────────────────────────────────────────────────────────────

def _base_headers() -> dict[str, str]:
    if not QCC_TOKEN:
        raise RuntimeError("QCC_TOKEN 未配置，请在服务器 .env 中添加：QCC_TOKEN=<your_token>")
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {QCC_TOKEN}",
    }


def _parse_mcp_response(resp: httpx.Response) -> dict:
    text = resp.text
    ct = resp.headers.get("content-type", "")
    if "text/event-stream" in ct or text.strip().startswith("data:"):
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                    if "result" in data:
                        return data["result"]
                except (json.JSONDecodeError, KeyError):
                    continue
        return {}
    try:
        return resp.json().get("result", {})
    except Exception:
        return {}


def _extract_content(result: dict) -> Any:
    items = result.get("content", [])
    if not items:
        return None
    text = items[0].get("text", "") if isinstance(items[0], dict) else ""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


# ── Session 封装 ─────────────────────────────────────────────────────────────

class _Session:
    def __init__(self, client: httpx.Client, url: str) -> None:
        self._client = client
        self._url = url
        self._headers = _base_headers()

    def initialize(self) -> None:
        resp = self._client.post(self._url, headers=self._headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "legal-app", "version": "1.0"},
            },
        }, timeout=15)
        sid = resp.headers.get("mcp-session-id", "")
        if sid:
            self._headers["mcp-session-id"] = sid
        try:
            self._client.post(self._url, headers=self._headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            }, timeout=10)
        except Exception:
            # initialized 通知是可选握手步骤,失败不影响后续工具调用
            logger.debug("MCP notifications/initialized 发送失败(可忽略)", exc_info=True)

    def list_tools(self) -> list[dict]:
        resp = self._client.post(self._url, headers=self._headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }, timeout=15)
        return _parse_mcp_response(resp).get("tools", [])

    def call_tool(self, name: str, search_key: str, req_id: int = 3) -> Any:
        resp = self._client.post(self._url, headers=self._headers, json={
            "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
            "params": {"name": name, "arguments": {"searchKey": search_key}},
        }, timeout=30)
        return _extract_content(_parse_mcp_response(resp))


# ── 分类别查询 ───────────────────────────────────────────────────────────────

def _query_preset_category(
    client: httpx.Client,
    category: str,
    search_key: str,
) -> dict[str, Any]:
    """查询有预设工具列表的端点（company / risk）。"""
    url = _ENDPOINT_URLS[category]
    tools = _CATEGORY_TOOLS[category]
    sess = _Session(client, url)
    sess.initialize()

    results: dict[str, Any] = {}
    for i, (tool_name, label) in enumerate(tools):
        try:
            data = sess.call_tool(tool_name, search_key, req_id=10 + i)
            results[label] = data if data is not None else "暂无数据"
        except Exception as e:
            results[label] = f"查询失败：{e}"

    return results


def _query_dynamic_category(
    client: httpx.Client,
    category: str,
    search_key: str,
) -> dict[str, Any]:
    """查询无预设工具列表的端点，动态发现工具后全部调用。"""
    url = _ENDPOINT_URLS[category]
    sess = _Session(client, url)
    sess.initialize()
    tools = sess.list_tools()

    if not tools:
        return {"_error": "该端点无可用工具"}

    results: dict[str, Any] = {}
    for i, tool in enumerate(tools):
        name = tool.get("name", "")
        desc = tool.get("description", name)[:20]
        label = desc.rstrip("，。、")
        try:
            data = sess.call_tool(name, search_key, req_id=10 + i)
            if data is not None:
                results[label] = data
        except Exception:
            # 单个工具失败会让该维度数据缺失,用户却看不出来 —— 必须留痕
            logger.warning("QCC MCP 工具 %r 调用失败,该维度数据缺失", name, exc_info=True)

    return results or {"_error": "所有工具均无返回数据"}


# ── 公开接口 ─────────────────────────────────────────────────────────────────

def query_company(
    company_name: str,
    categories: list[str] | None = None,
) -> dict:
    """
    查询企业信息。

    Returns:
        {
            "precise_name": company_name,   # QCC 直接接受模糊名称，无需二次搜索
            "company": {"工商登记信息": {...}, "主要人员": {...}, ...},
            "risk":    {"失信被执行": {...}, ...},
            ...
        }
    Raises:
        RuntimeError: 连接或初始化失败
    """
    if categories is None:
        categories = list(_DEFAULT_CATEGORIES)

    invalid = [c for c in categories if c not in _ENDPOINT_URLS]
    if invalid:
        raise ValueError(f"未知类别：{invalid}，可用：{list(_ENDPOINT_URLS.keys())}")

    try:
        with httpx.Client(timeout=30, verify=AI_HTTP_VERIFY_SSL) as client:
            output: dict[str, Any] = {"precise_name": company_name}
            for cat in categories:
                if cat in _CATEGORY_TOOLS:
                    output[cat] = _query_preset_category(client, cat, company_name)
                else:
                    output[cat] = _query_dynamic_category(client, cat, company_name)
            return output

    except Exception as e:
        raise RuntimeError(f"QCC MCP 连接失败：{e}") from e


# ── Markdown 渲染 ────────────────────────────────────────────────────────────

def _format_value(v: Any, depth: int = 0) -> str:
    """递归格式化任意值为可读字符串，最多展开两层。"""
    if v is None or v == "" or v == [] or v == {}:
        return "—"
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v or "—"
    if isinstance(v, list):
        if not v:
            return "—"
        count = len(v)
        items = []
        for item in v[:3]:
            items.append(_format_value(item, depth + 1) if depth < 1 else str(item)[:60])
        suffix = f"…（共 {count} 条）" if count > 3 else ""
        return "、".join(items) + suffix
    if isinstance(v, dict):
        if depth >= 1:
            # 内层字典：取前 3 个 key 拼成一行
            parts = [f"{k}：{v2}" for k, v2 in list(v.items())[:3] if v2 not in (None, "", [], {})]
            return "；".join(parts) or "—"
        # 外层字典：展开成表格行
        parts = [f"{k}：{_format_value(v2, 1)}" for k, v2 in v.items() if v2 not in (None, "", [], {})]
        return "；".join(parts[:6]) or "—"
    return str(v)


def _render_tool_result(label: str, data: Any) -> str:
    """渲染单个工具结果为 Markdown 小节。"""
    if isinstance(data, str) and (data.startswith("查询失败") or data == "暂无数据"):
        return f"\n*{label}：{data}*\n"

    if data is None or data == {} or data == []:
        return f"\n*{label}：暂无数据*\n"

    lines = [f"\n**{label}**\n", "| 字段 | 内容 |", "|------|------|"]

    if isinstance(data, list):
        for i, item in enumerate(data[:5], 1):
            if isinstance(item, dict):
                summary = "；".join(
                    f"{k}：{_format_value(v, 1)}"
                    for k, v in list(item.items())[:4]
                    if v not in (None, "", [], {})
                )
                lines.append(f"| {i} | {summary or '—'} |")
            else:
                lines.append(f"| {i} | {_format_value(item)} |")
        if len(data) > 5:
            lines.append(f"| … | 共 {len(data)} 条，此处展示前 5 条 |")
    elif isinstance(data, dict):
        for k, v in data.items():
            if v in (None, "", [], {}):
                continue
            v_str = _format_value(v).replace("\n", " ")
            lines.append(f"| {k} | {v_str} |")
    else:
        lines.append(f"| 结果 | {_format_value(data)} |")

    return "\n".join(lines) + "\n"


def _render_category(cat: str, cat_data: dict[str, Any]) -> str:
    icon, label = _ENDPOINT_LABELS.get(cat, ("📄", cat))
    parts = [f"\n### {icon} {label}"]

    if "_error" in cat_data:
        return "\n".join(parts) + f"\n> ⚠️ {cat_data['_error']}\n"

    for tool_label, tool_data in cat_data.items():
        parts.append(_render_tool_result(tool_label, tool_data))

    return "\n".join(parts)


def format_company_markdown(result: dict) -> str:
    """将 query_company 结果格式化为 Markdown，用于聊天显示。"""
    name = result.get("precise_name", "未知企业")
    parts = [f"## 🏢 {name}\n*数据来源：企查查*"]

    for cat in ("company", "risk", "ipr", "operation", "executive", "history"):
        if cat in result:
            parts.append(_render_category(cat, result[cat]))

    return "\n".join(parts)
