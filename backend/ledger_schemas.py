# -*- coding: utf-8 -*-
"""台账字段抽取的强 schema (v3.6.16)。

四类文书（起诉状/上诉状、判决/裁定、强制执行申请书、业务情况说明）抽取出的
业务字段，在写入案件台账前先经 Pydantic 严格校验，堵死"LLM 吐脏 JSON 污染
业务字段"这一真实出过的风险（N2）。

设计要点：
  * 字段与各 PROMPT 要求的 JSON 形状一一对应（中文字段名是 Python 3 合法标识符）。
  * 全部 Optional 带默认 None —— LLM 漏字段不算污染，只是缺值，不应整条作废。
  * extra="ignore" —— LLM 多吐的字段直接丢弃，不写进台账。
  * coerce_numbers_to_str=True —— 字符串字段收到数字时强转而非整条作废，降回归风险。
  * 标的金额 用宽松前置校验：数字 / 数字字符串 → float，纯叙述文本 → None。
    （财务字段的规范类型是 float，见 write_excel / 台账下游），叙述污染被挡下。
  * parse_ledger_fields 在校验彻底失败时抛 ValueError —— 保留原 _parse_json
    抛错被上层线程池捕获并提示"字段提取失败"的用户可见行为，不静默吞掉。
"""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator

_AMOUNT_RE = re.compile(r"-?\d+(?:\.\d+)?")

_LEDGER_CONFIG = ConfigDict(extra="ignore", coerce_numbers_to_str=True)


def _coerce_amount(v: Any) -> Optional[float]:
    """数字 / 数字字符串 → float；纯叙述或无数字 → None。"""
    if v is None:
        return None
    if isinstance(v, bool):  # bool 是 int 子类，显式排除
        return None
    if isinstance(v, (int, float)):
        return float(v)
    text = str(v).strip()
    if not text:
        return None
    match = _AMOUNT_RE.search(text.replace(",", "").replace("，", ""))
    return float(match.group()) if match else None


class LitigationFields(BaseModel):
    """起诉状 / 上诉状抽取字段（scene=extract_litigation_fields）。"""

    model_config = _LEDGER_CONFIG

    案号: Optional[str] = None
    案件名称: Optional[str] = None
    案件发生时间: Optional[str] = None
    案由: Optional[str] = None
    诉讼主体: Optional[str] = None
    主诉被诉: Optional[str] = None
    标的金额: Optional[float] = None
    基本情况: Optional[str] = None

    @field_validator("标的金额", mode="before")
    @classmethod
    def _validate_amount(cls, v: Any) -> Optional[float]:
        return _coerce_amount(v)


class JudgmentFields(BaseModel):
    """判决书 / 裁定书 / 再审申请书抽取字段（scene=extract_judgment_fields）。"""

    model_config = _LEDGER_CONFIG

    本案案号: Optional[str] = None
    关联案号: Optional[str] = None
    法院名称: Optional[str] = None
    审级: Optional[str] = None
    文书性质: Optional[str] = None
    生效判决日期: Optional[str] = None
    处理结果: Optional[str] = None
    后续程序: Optional[str] = None
    公司经济影响: Optional[str] = None
    服务律所: Optional[str] = None


class ExecutionFields(BaseModel):
    """强制执行申请书抽取字段（scene=extract_execution_fields）。"""

    model_config = _LEDGER_CONFIG

    强制执行时间: Optional[str] = None


class BusinessFields(BaseModel):
    """业务情况说明抽取字段（scene=extract_business_fields）。"""

    model_config = _LEDGER_CONFIG

    业务背景: Optional[str] = None


def parse_ledger_fields(
    raw: str | None, schema: type[BaseModel], scene: str
) -> dict[str, Any]:
    """用强 schema 解析台账抽取结果，返回干净 dict。

    成功 → 仅含 schema 定义字段的 dict（多余字段已丢弃、标的金额已规整）。
    彻底失败（空 / 非 JSON / 非对象 / 校验不过）→ 抛 ValueError，交由上层
    线程池 except 捕获并向用户提示"字段提取失败"，与原 _parse_json 抛
    JSONDecodeError 的行为一致（不静默吞掉，不把脏数据写进台账）。
    """
    from utils.llm_extract import extract_structured

    obj = extract_structured(raw, schema, fallback=None, scene=scene)
    if obj is None:
        raise ValueError(f"{scene}：LLM 输出非预期结构，已跳过该文书字段")
    return obj.model_dump()
