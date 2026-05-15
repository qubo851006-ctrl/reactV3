import json
import httpx
from config import AI_HTTP_VERIFY_SSL

MCP_ENDPOINT = "https://mcpmarket.cn/mcp/60c5fa4bd605ddc1ba37fb5c"
_BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

TOOL_MAP = {
    "basic": "get_company_basic_info",
    "judicial": "get_company_judical_info",
    "risk": "get_company_risk_info",
    "shareholder": "get_company_shareholder_info",
}

CATEGORY_LABELS = {
    "basic": ("📋", "基本信息"),
    "judicial": ("⚖️", "司法风险"),
    "risk": ("⚠️", "经营风险"),
    "shareholder": ("👥", "股东信息"),
}

# 要在 Markdown 表格中展示的字段白名单（中文键名）
_DISPLAY_KEYS = {
    "basic": [
        "企业名称", "统一社会信用代码", "法定代表人", "注册资本", "实缴资本",
        "成立日期", "经营状态", "所属行业", "企业类型", "注册地址", "经营范围",
    ],
    "judicial": [
        "立案信息数量", "法院公告数量", "被执行人信息数量", "司法拍卖数量",
        "破产重整数量", "近期立案", "近期执行",
    ],
    "risk": [
        "经营异常数量", "失信被执行人数量", "严重违法数量", "重大税收违法数量",
        "欠税公告数量", "限制消费令数量",
    ],
    "shareholder": [
        "股东总数", "股东列表",
    ],
}


def _parse_mcp_response(resp: httpx.Response) -> dict:
    """解析 MCP 响应，兼容 application/json 和 text/event-stream。"""
    text = resp.text
    content_type = resp.headers.get("content-type", "")

    if "text/event-stream" in content_type or text.strip().startswith("data:"):
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
        data = resp.json()
        return data.get("result", {})
    except Exception:
        return {}


def _extract_tool_content(result: dict):
    """从 MCP tool result 中提取 content[0].text，并尝试 JSON 解析。"""
    content_list = result.get("content", [])
    if not content_list:
        return {}
    text = content_list[0].get("text", "") if isinstance(content_list[0], dict) else ""
    if not text:
        return {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def _call_tool(client: httpx.Client, headers: dict, tool_name: str, arguments: dict, req_id: int):
    resp = client.post(MCP_ENDPOINT, headers=headers, json={
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }, timeout=30)
    result = _parse_mcp_response(resp)
    return _extract_tool_content(result)


def query_company(company_name: str, categories: list[str] = None) -> dict:
    """
    完整 MCP 查询流程。返回:
    {
      "precise_name": "XX股份有限公司",
      "basic": {...} | {"error": "..."},
      "judicial": {...} | {"error": "..."},
      ...
    }
    抛出 ValueError（未找到企业）或 RuntimeError（连接失败）。
    """
    if categories is None:
        categories = ["basic", "judicial"]

    headers = dict(_BASE_HEADERS)

    try:
        with httpx.Client(timeout=30, verify=AI_HTTP_VERIFY_SSL) as client:
            # 1. Initialize session
            init_resp = client.post(MCP_ENDPOINT, headers=headers, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "legal-app", "version": "1.0"},
                },
            }, timeout=15)
            session_id = init_resp.headers.get("mcp-session-id", "")
            if session_id:
                headers["mcp-session-id"] = session_id

            # 2. Notify initialized
            client.post(MCP_ENDPOINT, headers=headers, json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }, timeout=10)

            # 3. Get precise company name (parameter is blur_name, not company_name)
            precise_result = _call_tool(
                client, headers,
                "get_company_percise_name",
                {"blur_name": company_name},
                req_id=2,
            )
            matches = precise_result if isinstance(precise_result, list) else []
            if not matches:
                raise ValueError(f"未找到与「{company_name}」匹配的企业")

            precise_name = matches[0].get("name", company_name) if isinstance(matches[0], dict) else str(matches[0])

            # 4. Query selected categories sequentially
            output = {"precise_name": precise_name}
            for i, cat in enumerate(categories):
                tool_name = TOOL_MAP.get(cat)
                if not tool_name:
                    continue
                try:
                    data = _call_tool(
                        client, headers,
                        tool_name,
                        {"company_name": precise_name},
                        req_id=3 + i,
                    )
                    output[cat] = data
                except Exception as e:
                    output[cat] = {"error": str(e)}

            return output

    except ValueError:
        raise
    except Exception as e:
        raise RuntimeError(f"MCP 连接失败：{e}") from e


def _format_count_block(d: dict) -> str:
    """格式化 {"数量": N, "最新信息": [...]} 结构。"""
    count = d.get("数量", 0)
    if count == 0:
        return "0 条"
    recent = d.get("最新信息", [])
    if not recent or not isinstance(recent, list):
        return f"{count} 条"
    first = recent[0] if recent else {}
    if not isinstance(first, dict):
        return f"{count} 条"
    key_fields = ["案号", "案由", "立案日期", "裁判日期", "法院名称", "当事人名称"]
    parts = [f"{k}：{first[k]}" for k in key_fields if first.get(k)]
    summary = "；".join(parts[:3])
    return f"{count} 条（最新：{summary}）" if summary else f"{count} 条"


def _format_value(v) -> str:
    """将任意值转为可读字符串。"""
    if v is None or v == "" or v == [] or v == {}:
        return "—"
    if isinstance(v, dict):
        if "数量" in v:
            return _format_count_block(v)
        parts = [f"{k}：{v2}" for k, v2 in v.items() if v2 not in (None, "", [], {})]
        return "；".join(parts[:5]) if parts else "—"
    if isinstance(v, list):
        items = []
        for item in v[:3]:
            if isinstance(item, dict):
                parts = [f"{k2}：{v2}" for k2, v2 in item.items() if v2 not in (None, "", [], {})]
                items.append("；".join(parts[:4]) if parts else str(item))
            else:
                items.append(str(item))
        suffix = f"…（共{len(v)}条）" if len(v) > 3 else ""
        return "、".join(items) + suffix
    return str(v)


def _render_category(cat: str, data) -> str:
    """渲染单个类别为 Markdown 表格。"""
    icon, label = CATEGORY_LABELS.get(cat, ("", cat))
    header = f"\n**{icon} {label}**\n"

    if isinstance(data, dict) and "error" in data:
        return header + f"> ⚠️ 查询失败：{data['error']}\n"

    if not isinstance(data, dict) or not data:
        return header + "> 暂无数据\n"

    # 优先显示白名单字段，剩余字段补充
    priority = _DISPLAY_KEYS.get(cat, [])
    rows = []
    shown = set()
    for key in priority:
        if key in data:
            rows.append((key, _format_value(data[key])))
            shown.add(key)
    for key, val in data.items():
        if key not in shown and val not in (None, "", [], {}):
            rows.append((key, _format_value(val)))

    if not rows:
        return header + "> 暂无数据\n"

    lines = ["| 字段 | 内容 |", "|------|------|"]
    for k, v in rows:
        # 换行替换为 <br>，防止破坏 Markdown 表格
        v_clean = v.replace("\n", "<br>") if "\n" in v else v
        lines.append(f"| {k} | {v_clean} |")

    return header + "\n".join(lines) + "\n"


def format_company_markdown(result: dict) -> str:
    """将 query_company 结果格式化为 Markdown，直接用于聊天显示。"""
    precise_name = result.get("precise_name", "未知企业")
    parts = [f"🏢 **{precise_name}**"]

    for cat in ("basic", "judicial", "risk", "shareholder"):
        if cat in result:
            parts.append(_render_category(cat, result[cat]))

    return "\n".join(parts)
