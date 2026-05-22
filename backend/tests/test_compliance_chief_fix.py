# -*- coding: utf-8 -*-
"""
回归测试：首席合规官（胡鹏斌）意见的提取与去污。

固化两个真实生产 bug：

Bug A — 执行链路漏挂
    _fix_chief_opinion_from_text 已经修正了 chief.opinion_text，但
    normalize_extracted_item → _apply_approval_entries 又用未修正的
    approval_entries[胡鹏斌] 覆盖了一次，让 fix 失效。

Bug B — 业务规则缺失
    "拟同意，建议提交总经理办公会议审议。" 是纯程序性同意意见，按业务
    规则台账 "具体意见描述" 列应为 "/"，但旧逻辑因为长度 > 20 把整段
    回填到了 detail。
"""
import pytest

from utils.compliance_ledger import (
    _detail_for_opinion,
    _fix_chief_opinion_from_text,
    _is_pure_procedural_agreement,
    build_review_rows,
    normalize_extracted_item,
    normalize_review_opinion,
)


# ── 真实生产 PDF 的 OCR 输出（关键片段，已脱敏到必要的胡鹏斌附近） ──
REAL_OCR_TEXT = """# 中国航空集团建设开发有限公司呈批件

**签批意见**

||已阅。||
|--|--|--|
|||中航建设直属 杜方 2026-05-12 12:47:20|
|签发|已阅|中航建设直属 刘玉清 2026-05-11 17:02:41|
|签发|已阅。|中航建设直属 唐中华 2026-05-11 16:13:23|
|签发|已阅|中航建设直属 王文同 2026-05-11 15:12:27|
|签发|已阅|中航建设直属 于蒙 2026-05-11 13:44:06|
|签发|已阅|中航建设直属 布赫 2026-05-11 13:27:31|
|签发|同意提交总办会审议。请履行会前传签程序。拟同意，建议提交总经理办公会议审议。|中航建设直属 徐勤 2026-05-11 10:40:42 中航建设直属 胡鹏斌 2026-05-11 10:40:42|
"""


class TestProceduralAgreementDetection:
    """业务规则：纯程序性同意意见的识别"""

    def test_recognizes_chief_procedural_agreement(self):
        assert _is_pure_procedural_agreement("拟同意，建议提交总经理办公会议审议。")

    def test_recognizes_with_period_at_start(self):
        assert _is_pure_procedural_agreement("同意，建议提交董事会会议审议。")

    def test_recognizes_with_ti_qing(self):
        assert _is_pure_procedural_agreement("拟同意，建议提请总办会审议。")

    def test_rejects_substantive_agreement(self):
        """财务部那种含实质性合规审查描述的，不是纯程序性"""
        text = (
            "已阅核。已要求承办单位出具经本单位合规管理员签署的合规审查意见（后附）。"
            "经合规审查复核，本事项属于需经公司总经理办公会决策的重大经营事项。"
        )
        assert not _is_pure_procedural_agreement(text)

    def test_rejects_supplement_required(self):
        assert not _is_pure_procedural_agreement("建议补充完善相关材料后再提交")

    def test_rejects_pure_yi_yue(self):
        # "已阅" 不算"同意+建议提交会议审议"，不命中
        assert not _is_pure_procedural_agreement("已阅。")


class TestDetailForOpinionRule:
    """detail 字段的业务规则"""

    def test_procedural_agreement_clears_detail_even_with_long_text(self):
        """核心修复点：拟同意+建议提交会议审议，即使长度>20也应清空"""
        item = {
            "opinion_text": "拟同意，建议提交总经理办公会议审议。",
            "detail": "",
        }
        assert _detail_for_opinion(item) == "/"

    def test_procedural_agreement_clears_detail_even_when_llm_filled_detail(self):
        """即使 LLM 错抽出 detail，也应清空"""
        item = {
            "opinion_text": "拟同意，建议提交总经理办公会议审议。",
            "detail": "脏数据：误抽的别人意见",
        }
        assert _detail_for_opinion(item) == "/"

    def test_substantive_agreement_keeps_detail(self):
        """实质性同意意见（财务部那种）应保留 detail"""
        text = (
            "已阅核。已要求承办单位出具经本单位合规管理员签署的合规审查意见（后附）。"
            "经合规审查复核，本事项属于需经公司总经理办公会决策的重大经营事项。"
        )
        item = {"opinion_text": text, "detail": ""}
        assert _detail_for_opinion(item) == text

    def test_short_agreement_returns_slash(self):
        item = {"opinion_text": "同意", "detail": ""}
        assert _detail_for_opinion(item) == "/"


class TestFixChiefSyncsApprovalEntries:
    """Bug A 回归：fix 同时同步 approval_entries 里胡鹏斌那条"""

    def test_fix_updates_both_chief_and_approval_entry(self):
        # 模拟：Qwen 把徐勤+胡鹏斌两段合并塞给胡鹏斌
        bad_chief_text = "同意提交总办会审议。请履行会前传签程序。拟同意，建议提交总经理办公会议审议。"
        raw = {
            "chief": {
                "person": "胡鹏斌",
                "time": "2026-05-11 10:40:42",
                "opinion_text": bad_chief_text,
                "detail": "",
                "implementation": "/",
            },
            "approval_entries": [
                {
                    "department": "中航建设直属",
                    "person": "胡鹏斌",
                    "time": "2026-05-11 10:40:42",
                    "opinion_text": bad_chief_text,
                    "detail": "",
                    "implementation": "/",
                },
                {
                    "department": "中航建设直属",
                    "person": "徐勤",
                    "time": "2026-05-11 10:40:42",
                    "opinion_text": "同意提交总办会审议。请履行会前传签程序。",
                    "detail": "",
                    "implementation": "/",
                },
            ],
        }
        fixed = _fix_chief_opinion_from_text(raw, REAL_OCR_TEXT)

        # chief 被修正
        assert fixed["chief"]["opinion_text"] == "拟同意，建议提交总经理办公会议审议。"

        # 关键：approval_entries 里胡鹏斌那条也被同步修正
        chief_entry = next(
            e for e in fixed["approval_entries"] if e.get("person") == "胡鹏斌"
        )
        assert chief_entry["opinion_text"] == "拟同意，建议提交总经理办公会议审议。"

        # 其他人的 entries 不动
        xuqin_entry = next(
            e for e in fixed["approval_entries"] if e.get("person") == "徐勤"
        )
        assert xuqin_entry["opinion_text"] == "同意提交总办会审议。请履行会前传签程序。"


class TestEndToEndChiefDetailIsClean:
    """Bug A + Bug B 的端到端回归：复现 debug-last.json 输入，
    验证 final_review_rows[0].detail 不再是两段合并的脏数据。
    """

    def test_chief_row_detail_is_slash_after_full_pipeline(self):
        bad_chief_text = "同意提交总办会审议。请履行会前传签程序。拟同意，建议提交总经理办公会议审议。"
        raw = {
            "title": "关于股东会表决意见的请示",
            "procedure": "总办会审议",
            "chief": {
                "person": "胡鹏斌",
                "time": "2026-05-11 10:40:42",
                "opinion_text": bad_chief_text,
                "detail": "",
                "implementation": "/",
            },
            "approval_entries": [
                {
                    "department": "中航建设直属",
                    "person": "胡鹏斌",
                    "time": "2026-05-11 10:40:42",
                    "opinion_text": bad_chief_text,
                    "detail": "",
                    "implementation": "/",
                },
            ],
        }
        # 模拟生产路径：fix → normalize
        fixed = _fix_chief_opinion_from_text(raw, REAL_OCR_TEXT)
        final = normalize_extracted_item(fixed, {"审计部/法务合规部": "李莹"})

        # 找到首席合规官那一行
        chief_row = next(
            r for r in final["review_rows"] if r["review_unit"] == "首席合规官"
        )

        # 期望：detail 为 "/"，不再是两段合并的脏数据
        assert chief_row["detail"] == "/", (
            f"chief row detail should be cleaned, got: {chief_row['detail']!r}"
        )
        assert chief_row["review_opinion"] == "同意"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
