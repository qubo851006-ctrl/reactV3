# -*- coding: utf-8 -*-
"""台账字段抽取强 schema 测试 (v3.6.16).

验证 ledger_schemas.parse_ledger_fields + 四类 Pydantic schema：
  * 合法 JSON → 干净 dict（仅 schema 字段）
  * 标的金额：数字 / 数字字符串 → float，纯叙述 → None
  * 多余污染字段 → 丢弃
  * markdown 代码块包裹 → 仍能解析（extract_structured 剥壳）
  * 解释性前缀 + JSON → 仍能解析
  * 漏字段 → 该字段为 None，整条不作废
  * 非 JSON / 非对象 / 空 → 抛 ValueError（保留"字段提取失败"可见行为）
  * 字符串字段收到数字 → 强转为字符串（coerce_numbers_to_str）而非作废
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from ledger_schemas import (  # noqa: E402
    BusinessFields,
    ExecutionFields,
    JudgmentFields,
    LitigationFields,
    parse_ledger_fields,
)


class ParseLedgerFieldsTests(unittest.TestCase):
    # ── 起诉状 / 上诉状 ──────────────────────────────────────────────────────
    def test_litigation_full_clean(self):
        raw = (
            '{"案号":"(2022)川01民初1234号","案件名称":"甲与乙合同纠纷案",'
            '"案件发生时间":"2022-03-01","案由":"合同纠纷","诉讼主体":"原告：甲\\n被告：乙",'
            '"主诉被诉":"诉讼-主诉","标的金额":12.5,"基本情况":"请求支付货款"}'
        )
        out = parse_ledger_fields(raw, LitigationFields, "extract_litigation_fields")
        self.assertEqual(out["案号"], "(2022)川01民初1234号")
        self.assertEqual(out["标的金额"], 12.5)
        self.assertEqual(out["主诉被诉"], "诉讼-主诉")
        # 仅含 schema 定义的 8 个字段
        self.assertEqual(set(out.keys()), {
            "案号", "案件名称", "案件发生时间", "案由",
            "诉讼主体", "主诉被诉", "标的金额", "基本情况",
        })

    def test_amount_numeric_string_coerced(self):
        out = parse_ledger_fields('{"标的金额":"约100.50万元"}', LitigationFields, "s")
        self.assertEqual(out["标的金额"], 100.5)

    def test_amount_narrative_becomes_none(self):
        out = parse_ledger_fields('{"标的金额":"一百万左右"}', LitigationFields, "s")
        self.assertIsNone(out["标的金额"])

    def test_amount_null_stays_none(self):
        out = parse_ledger_fields('{"标的金额":null,"案由":"劳动争议"}', LitigationFields, "s")
        self.assertIsNone(out["标的金额"])
        self.assertEqual(out["案由"], "劳动争议")

    def test_pollution_extra_fields_dropped(self):
        raw = '{"案由":"侵权","恶意注入":"DROP TABLE","额外解释":"这是我的分析"}'
        out = parse_ledger_fields(raw, LitigationFields, "s")
        self.assertEqual(out["案由"], "侵权")
        self.assertNotIn("恶意注入", out)
        self.assertNotIn("额外解释", out)

    def test_markdown_fenced_json(self):
        raw = '```json\n{"案由":"借款合同纠纷"}\n```'
        out = parse_ledger_fields(raw, LitigationFields, "s")
        self.assertEqual(out["案由"], "借款合同纠纷")

    def test_explanatory_prefix_then_json(self):
        raw = '结果：{"案由":"租赁合同纠纷"}'
        out = parse_ledger_fields(raw, LitigationFields, "s")
        self.assertEqual(out["案由"], "租赁合同纠纷")

    def test_missing_fields_default_none(self):
        out = parse_ledger_fields('{"案由":"买卖合同"}', LitigationFields, "s")
        self.assertEqual(out["案由"], "买卖合同")
        self.assertIsNone(out["案号"])
        self.assertIsNone(out["标的金额"])

    def test_string_field_number_coerced(self):
        # 案号 收到数字 → 强转字符串而非整条作废
        out = parse_ledger_fields('{"案号":2022}', LitigationFields, "s")
        self.assertEqual(out["案号"], "2022")

    # ── 失败路径：抛 ValueError ───────────────────────────────────────────────
    def test_non_json_raises(self):
        with self.assertRaises(ValueError):
            parse_ledger_fields("这是一段纯叙述，没有任何 JSON", LitigationFields, "s")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            parse_ledger_fields("", LitigationFields, "s")
        with self.assertRaises(ValueError):
            parse_ledger_fields(None, LitigationFields, "s")

    def test_json_array_not_object_raises(self):
        with self.assertRaises(ValueError):
            parse_ledger_fields('["a","b"]', LitigationFields, "s")

    # ── 判决 / 执行 / 业务 ────────────────────────────────────────────────────
    def test_judgment_fields(self):
        raw = (
            '{"本案案号":"(2023)川01民终24491号","法院名称":"成都中院","审级":"二审",'
            '"处理结果":"驳回上诉，维持原判","服务律所":null}'
        )
        out = parse_ledger_fields(raw, JudgmentFields, "extract_judgment_fields")
        self.assertEqual(out["审级"], "二审")
        self.assertEqual(out["处理结果"], "驳回上诉，维持原判")
        self.assertIsNone(out["服务律所"])
        self.assertEqual(len(out), 10)

    def test_execution_fields(self):
        out = parse_ledger_fields('{"强制执行时间":"2024-01-15"}', ExecutionFields, "s")
        self.assertEqual(out["强制执行时间"], "2024-01-15")

    def test_business_fields(self):
        out = parse_ledger_fields('{"业务背景":"双方签订采购合同后发生货款争议"}', BusinessFields, "s")
        self.assertIn("采购合同", out["业务背景"])


if __name__ == "__main__":
    unittest.main()
