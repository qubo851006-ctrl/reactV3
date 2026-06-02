"""
债务清偿能力评估 — 基于企查查 MCP

对被告方执行五维度穿透扫描：
  维度1  企业基础 + 真实财务底盘
  维度2  可执行资产识别
  维度3  当前债务压力
  维度4  历史偿债模式（history 端点当前无工具，跳过）
  维度5  法代/实控人个人司法状态

入口：assess_debt_recovery(company_name, claim_amount) -> dict
渲染：format_assessment_markdown(result) -> str
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from config import AI_HTTP_VERIFY_SSL

logger = logging.getLogger(__name__)
from utils.qcc_mcp_client import (
    _ENDPOINT_URLS,
    _Session,
    _parse_mcp_response,
    _extract_content,
)

# ── 工具清单 ─────────────────────────────────────────────────────────────────

_DIM1_COMPANY = [
    ("get_company_registration_info", "工商登记"),
    ("get_financial_data",            "财务数据"),
    ("get_actual_controller",         "实际控制人"),
    ("get_key_personnel",             "主要人员"),
    ("get_shareholder_info",          "股东结构"),
    ("get_external_investments",      "对外投资"),
]

_DIM1_RISK = [
    ("get_cancellation_record_info",  "注销备案"),
    ("get_bankruptcy_reorganization", "破产重整"),
]

_DIM2_RISK = [
    ("get_chattel_mortgage_info",  "动产抵押"),
    ("get_equity_pledge_info",     "股权出质"),
    ("get_land_mortgage_info",     "土地抵押"),
    ("get_stock_pledge_info",      "股权质押"),
    ("get_equity_freeze",          "股权冻结"),
]

_DIM3_RISK = [
    ("get_dishonest_info",               "失信被执行"),
    ("get_judgment_debtor_info",         "被执行信息"),
    ("get_high_consumption_restriction", "限制高消费"),
    ("get_terminated_cases",             "终结执行"),
    ("get_default_info",                 "债券违约"),
    ("get_guarantee_info",               "对外担保"),
    ("get_tax_arrears_notice",           "欠税公告"),
]

# executive 端点工具 — 同时需要 searchKey(企业名) + personName(人名)
_DIM5_EXEC = [
    ("get_executive_dishonest",              "个人失信"),
    ("get_executive_judgment_debtor",        "个人被执行"),
    ("get_executive_high_consumption_ban",   "个人限高"),
    ("get_executive_exit_restriction",       "限制出境"),
    ("get_executive_equity_freeze",          "个人股权冻结"),
    ("get_executive_controlled_companies",   "实控企业"),
    ("get_executive_investments",            "个人投资"),
]


# ── 工具调用辅助 ─────────────────────────────────────────────────────────────

def _safe_call(sess: _Session, tool_name: str, arguments: dict, req_id: int = 3) -> Any:
    """调用工具，出错时返回 {"_error": "..."}。"""
    try:
        resp = sess._client.post(sess._url, headers=sess._headers, json={
            "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }, timeout=30)
        return _extract_content(_parse_mcp_response(resp))
    except Exception as e:
        return {"_error": str(e)}


def _open_session(client: httpx.Client, endpoint: str) -> _Session:
    sess = _Session(client, _ENDPOINT_URLS[endpoint])
    sess.initialize()
    return sess


# ── 人名提取 ─────────────────────────────────────────────────────────────────

def _extract_key_persons(
    key_personnel_data: Any,
    actual_controller_data: Any,
) -> list[str]:
    """
    从 get_key_personnel / get_actual_controller 结果中提取人名列表
    （法代优先，至多返回 3 人）。
    """
    persons: list[str] = []

    def _pick_name(item: Any) -> str | None:
        if not isinstance(item, dict):
            return str(item)[:20] if item else None
        for k in ("name", "姓名", "personName", "legalPerson", "legalRepresentative"):
            if item.get(k):
                return str(item[k])
        return None

    # 从 key_personnel 提取法代（position 含"法定代表人"的排最前）
    items = key_personnel_data if isinstance(key_personnel_data, list) else []
    legal_reps = [i for i in items if "法定代表人" in str(i.get("position", ""))]
    others = [i for i in items if i not in legal_reps]
    for item in legal_reps + others:
        name = _pick_name(item)
        if name and name not in persons:
            persons.append(name)
        if len(persons) >= 3:
            break

    # 从 actual_controller 补充实控人
    if isinstance(actual_controller_data, list):
        for item in actual_controller_data[:2]:
            name = _pick_name(item)
            if name and name not in persons:
                persons.append(name)
    elif isinstance(actual_controller_data, dict):
        name = _pick_name(actual_controller_data)
        if name and name not in persons:
            persons.append(name)

    return persons[:3]


# ── 风险信号计数 ─────────────────────────────────────────────────────────────

def _count_risk(data: Any) -> int:
    """从工具返回值中粗略统计风险条目数量。"""
    if not data or data == {} or isinstance(data, dict) and "_error" in data:
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for k in ("total", "count", "totalCount", "总数量", "数量"):
            if isinstance(data.get(k), (int, float)) and data[k] > 0:
                return int(data[k])
        # 如果是含 list 的 dict，数列表长度
        for k in ("list", "data", "items", "records"):
            if isinstance(data.get(k), list):
                return len(data[k])
        # 如果 dict 有实质内容，算作 1 条
        return 1 if any(v for v in data.values() if v) else 0
    return 0


def _is_cancelled_or_bankrupt(dim1: dict) -> bool:
    reg = dim1.get("工商登记") or {}
    status_str = json.dumps(reg, ensure_ascii=False)
    cancel = dim1.get("注销备案") or {}
    bankrupt = dim1.get("破产重整") or {}
    return (
        "注销" in status_str
        or "吊销" in status_str
        or bool(cancel and not isinstance(cancel, dict) and "error" not in str(cancel).lower())
        or _count_risk(bankrupt) > 0
    )


# ── 评级计算 ─────────────────────────────────────────────────────────────────

def _calculate_rating(
    dim1: dict,
    dim2: dict,
    dim3: dict,
    claim_amount: float,
) -> tuple[str, tuple[int, int], str]:
    """
    返回 (评级, 回收率区间%, 评级说明)。
    """
    if _is_cancelled_or_bankrupt(dim1):
        return "D", (0, 10), "企业已注销/破产，追偿路径极窄，建议评估走债权申报程序。"

    # 风险信号汇总
    dishonest_n   = _count_risk(dim3.get("失信被执行"))
    judgment_n    = _count_risk(dim3.get("被执行信息"))
    terminated_n  = _count_risk(dim3.get("终结执行"))
    high_cons_n   = _count_risk(dim3.get("限制高消费"))
    total_risk = dishonest_n + terminated_n + (1 if high_cons_n > 0 else 0)

    # 财务数据修正
    fin = dim1.get("财务数据")
    has_finance = bool(fin and isinstance(fin, dict) and not fin.get("_error"))
    liability_ratio = None
    if has_finance:
        for k in ("资产负债率", "liabilityRatio", "asset_liability_ratio"):
            v = fin.get(k)
            if v is not None:
                try:
                    liability_ratio = float(str(v).replace("%", "")) / 100 if "%" in str(v) else float(v)
                    break
                except Exception:
                    logger.debug("资产负债率字段 %r 解析失败,值=%r", k, v, exc_info=True)

    # 可执行资产信号
    asset_signals = sum(
        1 for v in dim2.values()
        if isinstance(v, (list, dict)) and _count_risk(v) > 0
    )

    if total_risk == 0 and judgment_n == 0:
        if liability_ratio is not None and liability_ratio > 0.9:
            rating, rng, note = "B", (25, 45), "财务数据显示高负债，建议激进保全。"
        else:
            rating, rng, note = "S", (65, 85), "无重大司法风险信号，正常追偿。"
    elif total_risk <= 2 and judgment_n <= 3:
        rating, rng, note = "A", (45, 65), "存在少量司法事件，建议激进保全策略。"
    elif total_risk <= 5 or judgment_n <= 8:
        rating, rng, note = "B", (25, 45), "债务压力较大，需快速抢占保全优先顺位。"
    elif total_risk <= 10:
        rating, rng, note = "C", (10, 25), "连续失信/被执行，追偿难度高，优先评估刺破面纱路径。"
    else:
        rating, rng, note = "D", (0, 10), "极度失信主体，不建议单独诉讼，建议集体追偿或放弃。"

    # 资产被设定他项权利较多时下调
    if asset_signals >= 3 and rating in ("S", "A"):
        rating_map = {"S": "A", "A": "B"}
        rating = rating_map.get(rating, rating)
        rng = (rng[0] - 15, rng[1] - 15)
        note += " 可执行资产多已被抵押/质押，净值有限。"

    rng = (max(0, rng[0]), max(0, rng[1]))
    return rating, rng, note


# ── 主入口 ───────────────────────────────────────────────────────────────────

def assess_debt_recovery(
    company_name: str,
    claim_amount: float = 0,
) -> dict:
    """
    对目标企业执行债务清偿能力评估。

    Returns:
        {
            "company_name": str,
            "claim_amount": float,
            "rating": "S"|"A"|"B"|"C"|"D",
            "recovery_range": (low%, high%),
            "rating_note": str,
            "dim1": {...},   # 企业基础 + 财务
            "dim2": {...},   # 可执行资产
            "dim3": {...},   # 债务压力
            "dim5": {...},   # 法代/实控人
        }
    """
    try:
        with httpx.Client(timeout=30, verify=AI_HTTP_VERIFY_SSL) as client:
            dim1: dict[str, Any] = {}
            dim2: dict[str, Any] = {}
            dim3: dict[str, Any] = {}
            dim5: dict[str, Any] = {}

            # ── 维度1：企业基础（company + risk）───────────────────
            company_sess = _open_session(client, "company")
            for i, (tool, label) in enumerate(_DIM1_COMPANY):
                dim1[label] = _safe_call(
                    company_sess, tool, {"searchKey": company_name}, req_id=10 + i
                )

            risk_sess = _open_session(client, "risk")
            for i, (tool, label) in enumerate(_DIM1_RISK):
                dim1[label] = _safe_call(
                    risk_sess, tool, {"searchKey": company_name}, req_id=20 + i
                )

            # ── 维度2：可执行资产（risk）──────────────────────────
            for i, (tool, label) in enumerate(_DIM2_RISK):
                dim2[label] = _safe_call(
                    risk_sess, tool, {"searchKey": company_name}, req_id=30 + i
                )

            # ── 维度3：债务压力（risk）───────────────────────────
            for i, (tool, label) in enumerate(_DIM3_RISK):
                dim3[label] = _safe_call(
                    risk_sess, tool, {"searchKey": company_name}, req_id=40 + i
                )

            # ── 维度5：法代/实控人（executive）──────────────────
            key_persons = _extract_key_persons(
                dim1.get("主要人员"), dim1.get("实际控制人")
            )
            if key_persons:
                exec_sess = _open_session(client, "executive")
                for person in key_persons:
                    person_data: dict[str, Any] = {}
                    for i, (tool, label) in enumerate(_DIM5_EXEC):
                        person_data[label] = _safe_call(
                            exec_sess, tool,
                            {"searchKey": company_name, "personName": person},
                            req_id=50 + i,
                        )
                    dim5[person] = person_data

            # ── 综合评级 ──────────────────────────────────────────
            rating, recovery_range, rating_note = _calculate_rating(
                dim1, dim2, dim3, claim_amount
            )

            return {
                "company_name": company_name,
                "claim_amount": claim_amount,
                "rating": rating,
                "recovery_range": recovery_range,
                "rating_note": rating_note,
                "dim1": dim1,
                "dim2": dim2,
                "dim3": dim3,
                "dim5": dim5,
            }

    except Exception as e:
        raise RuntimeError(f"债务清偿评估失败：{e}") from e


# ── Markdown 渲染 ────────────────────────────────────────────────────────────

_RATING_EMOJI = {"S": "🟢", "A": "🔵", "B": "🟡", "C": "🟠", "D": "🔴"}
_RATING_LABEL = {
    "S": "强烈追偿",
    "A": "积极追偿",
    "B": "有限追偿",
    "C": "困难追偿",
    "D": "不建议追偿",
}

_ACTIONS = {
    "S": [
        ("T+0", "启动标准诉前保全"),
        ("T+3", "提交诉讼状"),
        ("T+14", "准备一审材料"),
        ("T+30", "评估和解可能性"),
    ],
    "A": [
        ("T+0", "立即启动激进保全，锁定 Tier1-2 资产"),
        ("T+3", "提交诉讼状 + 保全申请"),
        ("T+7", "监控资产异动，必要时申请撤销权之诉"),
        ("T+14", "全额诉讼请求，不接受低于 70% 和解方案"),
    ],
    "B": [
        ("T+0", "抢先保全，优先锁定未被设定他项权利的资产"),
        ("T+3", "提交诉状同时申请财产线索调查令"),
        ("T+7", "评估是否追加实控人为共同被告"),
        ("T+14", "准备接受 40-60% 的和解"),
        ("T+30", "若保全到位，推进快速调解"),
    ],
    "C": [
        ("T+0", "优先评估刺破公司面纱可行性"),
        ("T+3", "查询实控人名下资产，决定是否追加被告"),
        ("T+7", "申请历史转让撤销权之诉（如有资产异动）"),
        ("T+14", "降低追偿预期，接受 20-35% 和解"),
        ("T+30", "评估加入其他债权人集体追偿"),
    ],
    "D": [
        ("T+0", "确认企业存续状态 / 债权申报期限"),
        ("T+3", "如已进入破产：立即申报债权"),
        ("T+7", "评估放弃诉讼或最低成本走完程序保留债权凭证"),
    ],
}


def _fmt(v: Any, depth: int = 0) -> str:
    if v is None or v == "" or v == [] or v == {}:
        return "—"
    if isinstance(v, dict) and "_error" in v:
        return "*查询异常*"
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v[:100] or "—"
    if isinstance(v, list):
        if not v:
            return "—"
        count = len(v)
        preview = []
        for item in v[:2]:
            if isinstance(item, dict):
                parts = [f"{k}：{_fmt(vv, 1)}" for k, vv in list(item.items())[:3] if vv not in (None, "", [], {})]
                preview.append("；".join(parts) if parts else str(item)[:60])
            else:
                preview.append(str(item)[:60])
        suffix = f"（共 {count} 条）" if count > 2 else ""
        return "、".join(preview) + suffix
    if isinstance(v, dict):
        if depth >= 1:
            parts = [f"{k}：{_fmt(vv, 2)}" for k, vv in list(v.items())[:3] if vv not in (None, "", [], {})]
            return "；".join(parts) or "—"
        parts = [f"{k}：{_fmt(vv, 1)}" for k, vv in v.items() if vv not in (None, "", [], {})]
        return "；".join(parts[:6]) or "—"
    return str(v)[:100]


def _render_section(title: str, data: dict[str, Any]) -> str:
    lines = [f"\n#### {title}\n", "| 维度 | 内容 |", "|------|------|"]
    has_content = False
    for label, val in data.items():
        if isinstance(val, dict) and "_error" in val and len(val) == 1:
            continue  # 跳过纯错误项
        v_str = _fmt(val).replace("\n", " ")
        if v_str != "—":
            lines.append(f"| {label} | {v_str} |")
            has_content = True
    if not has_content:
        return ""
    return "\n".join(lines) + "\n"


def format_assessment_markdown(result: dict) -> str:
    """将 assess_debt_recovery 结果渲染为 Markdown 报告。"""
    name = result["company_name"]
    amount = result["claim_amount"]
    rating = result["rating"]
    low, high = result["recovery_range"]
    note = result["rating_note"]

    emoji = _RATING_EMOJI.get(rating, "⚪")
    label = _RATING_LABEL.get(rating, rating)
    amount_str = f"{amount:,.0f} 元" if amount > 0 else "未指定"

    parts = [
        "## 债务清偿能力评估报告",
        f"> **被评估方**：{name}　**债权金额**：{amount_str}",
        "",
        f"### {emoji} 综合评级：{rating} 级 · {label}",
        "",
        "| 项目 | 结论 |",
        "|------|------|",
        f"| 追偿评级 | **{rating} 级 — {label}** |",
        f"| 预期回收率 | **{low}% — {high}%** |",
        f"| 建议保全金额 | 约 {amount * (low + high) / 200:,.0f} 元（债权金额 × 回收率中位数）|" if amount > 0 else "| 建议保全金额 | 请提供债权金额 |",
        f"| 评级依据 | {note} |",
    ]

    # 推荐 Action
    parts += ["", "### 📋 推荐 Action", ""]
    for timing, action in _ACTIONS.get(rating, []):
        parts.append(f"- **{timing}**：{action}")

    # 维度一：企业基础
    sec = _render_section("🏢 维度一：企业基础 + 财务底盘", result["dim1"])
    if sec:
        parts += ["", "---", sec]

    # 维度二：可执行资产
    sec = _render_section("💼 维度二：可执行资产", result["dim2"])
    if sec:
        parts += [sec]

    # 维度三：债务压力
    sec = _render_section("⚠️ 维度三：当前债务压力", result["dim3"])
    if sec:
        parts += [sec]

    # 维度五：法代/实控人
    if result["dim5"]:
        parts += ["", "---", "\n#### 👔 维度五：法代 / 实控人个人司法状态\n"]
        for person, pdata in result["dim5"].items():
            sec = _render_section(f"**{person}**", pdata)
            if sec:
                parts.append(sec)

    parts += [
        "",
        "---",
        "*数据来源：企查查 MCP · 仅供参考，不构成法律意见*",
    ]

    return "\n".join(parts)
