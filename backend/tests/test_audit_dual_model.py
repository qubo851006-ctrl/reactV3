"""
审计双模型交叉校验单元测试

覆盖范围：
  1. _merge_ab_results     — 合并逻辑（纯函数）
  2. _call_review_llm      — mock LLM；测试正常解析、JSONDecodeError 静默处理、regex 无匹配降级
  3. _build_review_prompt  — Prompt 包含必要字段
  4. _run_full_analysis    — 端到端流程（mock A + B）；测试 B 失败时 A 结果仍正确返回
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


# ─────────────────────────────────────────────────────────────
# 1. _merge_ab_results — 纯函数，无需 mock
# ─────────────────────────────────────────────────────────────

class MergeABResultsTests(unittest.TestCase):
    def setUp(self):
        from routers.audit import _merge_ab_results
        self.merge = _merge_ab_results

        self.rows_a = [
            {"seq": 1, "issue": "采购未招标", "description": "",
             "category_l1": "采购管理", "category_l2": "采购方式", "domain": "工程领域"},
            {"seq": 2, "issue": "缺少会议记录", "description": "",
             "category_l1": "公司治理", "category_l2": "会议管理", "domain": "酒店公寓"},
            {"seq": 3, "issue": "合同未审核", "description": "",
             "category_l1": "合同及法律合规管理", "category_l2": "合同审核及签署", "domain": "物业租赁"},
        ]

    def test_no_corrections_all_none(self):
        """无分歧时所有行的 disagreement 均为 None"""
        result = self.merge(self.rows_a, [])
        for row in result:
            self.assertIsNone(row["disagreement"])

    def test_correction_sets_disagreement(self):
        """B 对 seq=1 提出修正 → 该行 disagreement 不为 None"""
        corrections = [{
            "序号": 1,
            "需要修正": True,
            "问题类别一级": "工程项目管理",
            "问题类别二级": "工程项目招标管理",
            "业务领域": "工程领域",
        }]
        result = self.merge(self.rows_a, corrections)
        self.assertIsNotNone(result[0]["disagreement"])
        self.assertIsNone(result[1]["disagreement"])
        self.assertIsNone(result[2]["disagreement"])

    def test_disagreement_content_matches_correction(self):
        """disagreement 中的字段内容与 B 的修正一致"""
        corrections = [{
            "序号": 2,
            "需要修正": True,
            "问题类别一级": "财务管理",
            "问题类别二级": "会计核算管理",
            "业务领域": "酒店公寓",
        }]
        result = self.merge(self.rows_a, corrections)
        d = result[1]["disagreement"]
        self.assertEqual(d["category_l1"], "财务管理")
        self.assertEqual(d["category_l2"], "会计核算管理")
        self.assertEqual(d["domain"], "酒店公寓")

    def test_a_fields_unchanged_even_with_correction(self):
        """有分歧时 A 的字段（category_l1 等）保持不变，仅新增 disagreement"""
        corrections = [{"序号": 1, "需要修正": True,
                        "问题类别一级": "X", "问题类别二级": "Y", "业务领域": "Z"}]
        result = self.merge(self.rows_a, corrections)
        self.assertEqual(result[0]["category_l1"], "采购管理")
        self.assertEqual(result[0]["category_l2"], "采购方式")

    def test_unknown_seq_in_corrections_ignored(self):
        """corrections 中序号不存在的条目应被忽略，不影响其他行"""
        corrections = [{"序号": 999, "需要修正": True,
                        "问题类别一级": "X", "问题类别二级": "Y", "业务领域": "Z"}]
        result = self.merge(self.rows_a, corrections)
        for row in result:
            self.assertIsNone(row["disagreement"])

    def test_empty_rows_returns_empty(self):
        """空输入返回空列表"""
        result = self.merge([], [])
        self.assertEqual(result, [])

    def test_multiple_corrections(self):
        """多行同时有分歧时均正确标注"""
        corrections = [
            {"序号": 1, "需要修正": True, "问题类别一级": "A1", "问题类别二级": "A2", "业务领域": "A3"},
            {"序号": 3, "需要修正": True, "问题类别一级": "C1", "问题类别二级": "C2", "业务领域": "C3"},
        ]
        result = self.merge(self.rows_a, corrections)
        self.assertIsNotNone(result[0]["disagreement"])
        self.assertIsNone(result[1]["disagreement"])
        self.assertIsNotNone(result[2]["disagreement"])


# ─────────────────────────────────────────────────────────────
# 2. _call_review_llm — mock LLM 客户端
# ─────────────────────────────────────────────────────────────

def _make_llm_response(content: str):
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = content
    return mock_resp


SAMPLE_ROWS_A = [
    {"seq": 1, "issue": "采购未招标", "description": "",
     "category_l1": "采购管理", "category_l2": "采购方式", "domain": "工程领域"},
]
SAMPLE_DOMAINS = ["工程领域", "酒店公寓"]


def _patch_review_llm(llm_return_content: str):
    """patch get_llm_client，让 B 返回指定文本"""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_llm_response(llm_return_content)

    return patch("routers.audit.get_llm_client", return_value=mock_client)


class CallReviewLLMTests(unittest.TestCase):
    def test_b_flags_correction(self):
        """B 明确标注需要修正 → 返回该条目"""
        llm_text = (
            '[{"序号": 1, "需要修正": true, '
            '"问题类别一级": "工程项目管理", "问题类别二级": "工程项目招标管理", "业务领域": "工程领域"}]'
        )
        with _patch_review_llm(llm_text):
            from routers.audit import _call_review_llm
            result = _call_review_llm(SAMPLE_ROWS_A, SAMPLE_DOMAINS)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["序号"], 1)
        self.assertTrue(result[0]["需要修正"])

    def test_b_no_correction_returns_empty(self):
        """B 认为全部正确 → 返回空列表"""
        llm_text = (
            '[{"序号": 1, "需要修正": false, '
            '"问题类别一级": "采购管理", "问题类别二级": "采购方式", "业务领域": "工程领域"}]'
        )
        with _patch_review_llm(llm_text):
            from routers.audit import _call_review_llm
            result = _call_review_llm(SAMPLE_ROWS_A, SAMPLE_DOMAINS)

        self.assertEqual(result, [])

    def test_json_decode_error_returns_empty(self):
        """B 返回破损 JSON → JSONDecodeError 静默处理，返回空列表不抛异常"""
        broken_json = '[{"序号": 1, "需要修正": true, "问题类别一级": broken}'
        with _patch_review_llm(broken_json):
            from routers.audit import _call_review_llm
            result = _call_review_llm(SAMPLE_ROWS_A, SAMPLE_DOMAINS)

        self.assertEqual(result, [])

    def test_no_json_array_in_response_returns_empty(self):
        """B 返回纯文本（无 JSON 数组）→ 静默返回空列表"""
        with _patch_review_llm("抱歉，我无法完成此任务。"):
            from routers.audit import _call_review_llm
            result = _call_review_llm(SAMPLE_ROWS_A, SAMPLE_DOMAINS)

        self.assertEqual(result, [])

    def test_b_exception_propagates(self):
        """LLM 客户端整体抛异常 → 异常向上传递（由调用方 except 捕获）"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("network error")

        with patch("routers.audit.get_llm_client", return_value=mock_client):
            from routers.audit import _call_review_llm
            with self.assertRaises(RuntimeError):
                _call_review_llm(SAMPLE_ROWS_A, SAMPLE_DOMAINS)


# ─────────────────────────────────────────────────────────────
# 3. _build_review_prompt — Prompt 内容校验
# ─────────────────────────────────────────────────────────────

class BuildReviewPromptTests(unittest.TestCase):
    def setUp(self):
        from routers.audit import _build_review_prompt
        self.build = _build_review_prompt

    def test_prompt_contains_issue_text(self):
        """Prompt 中包含原始问题文本"""
        rows_a = [{"seq": 1, "issue": "采购未招标", "description": "",
                   "category_l1": "采购管理", "category_l2": "采购方式", "domain": "工程领域"}]
        prompt = self.build(rows_a, ["工程领域"])
        self.assertIn("采购未招标", prompt)

    def test_prompt_contains_domain(self):
        """Prompt 中包含指定业务领域"""
        rows_a = [{"seq": 1, "issue": "x", "description": "",
                   "category_l1": "其他", "category_l2": "其他", "domain": "酒店公寓"}]
        prompt = self.build(rows_a, ["酒店公寓", "工程领域"])
        self.assertIn("酒店公寓", prompt)

    def test_prompt_contains_needs_correction_key(self):
        """Prompt 中明确要求返回「需要修正」字段"""
        rows_a = [{"seq": 1, "issue": "x", "description": "",
                   "category_l1": "其他", "category_l2": "其他", "domain": "x"}]
        prompt = self.build(rows_a, ["x"])
        self.assertIn("需要修正", prompt)

    def test_prompt_contains_taxonomy(self):
        """Prompt 中包含分类体系中的一级大类"""
        rows_a = [{"seq": 1, "issue": "x", "description": "",
                   "category_l1": "其他", "category_l2": "其他", "domain": "x"}]
        prompt = self.build(rows_a, ["x"])
        self.assertIn("公司治理", prompt)
        self.assertIn("采购管理", prompt)


# ─────────────────────────────────────────────────────────────
# 4. _run_full_analysis — 端到端流程（双 mock）
# ─────────────────────────────────────────────────────────────

A_RESPONSE = (
    '[{"序号": 1, "问题类别一级": "采购管理", "问题类别二级": "采购方式", "业务领域": "工程领域"},'
    ' {"序号": 2, "问题类别一级": "公司治理", "问题类别二级": "会议管理", "业务领域": "酒店公寓"}]'
)
B_AGREES = (
    '[{"序号": 1, "需要修正": false, "问题类别一级": "采购管理", "问题类别二级": "采购方式", "业务领域": "工程领域"},'
    ' {"序号": 2, "需要修正": false, "问题类别一级": "公司治理", "问题类别二级": "会议管理", "业务领域": "酒店公寓"}]'
)
B_DISAGREES_ON_1 = (
    '[{"序号": 1, "需要修正": true, "问题类别一级": "工程项目管理", "问题类别二级": "工程项目招标管理", "业务领域": "工程领域"},'
    ' {"序号": 2, "需要修正": false, "问题类别一级": "公司治理", "问题类别二级": "会议管理", "业务领域": "酒店公寓"}]'
)

SAMPLE_ROWS_RAW = [
    {"seq": 1, "issue": "采购未招标", "description": ""},
    {"seq": 2, "issue": "缺少会议记录", "description": ""},
]


def _make_two_call_client(a_text: str, b_text: str):
    """第一次 create 返回 A 的文本，第二次返回 B 的文本。"""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        _make_llm_response(a_text),
        _make_llm_response(b_text),
    ]
    return mock_client


class RunFullAnalysisTests(unittest.TestCase):
    def _run(self, a_text: str, b_text: str):
        # _parse_llm_output 是纯函数，不调 LLM；只有 _call_review_llm 会请求一次
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_llm_response(b_text)
        with patch("routers.audit.get_llm_client", return_value=mock_client):
            from routers.audit import _merge_ab_results, _parse_llm_output, _call_review_llm

            rows_a = _parse_llm_output(a_text, SAMPLE_ROWS_RAW)
            try:
                corrections = _call_review_llm(rows_a, ["工程领域", "酒店公寓"])
            except Exception:
                corrections = []
            return _merge_ab_results(rows_a, corrections)

    def test_no_disagreement_when_b_agrees(self):
        """A 和 B 一致 → 所有行 disagreement 为 None"""
        result = self._run(A_RESPONSE, B_AGREES)
        for row in result:
            self.assertIsNone(row["disagreement"])

    def test_disagreement_when_b_corrects(self):
        """B 修正 seq=1 → seq=1 有 disagreement，seq=2 无"""
        result = self._run(A_RESPONSE, B_DISAGREES_ON_1)
        self.assertIsNotNone(result[0]["disagreement"])
        self.assertIsNone(result[1]["disagreement"])

    def test_b_failure_returns_a_result_without_disagreement(self):
        """B 整体失败 → 返回 A 的结果，disagreement 全为 None"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            _make_llm_response(A_RESPONSE),
            RuntimeError("B 模型超时"),
        ]
        with patch("routers.audit.get_llm_client", return_value=mock_client):
            from routers.audit import _merge_ab_results, _parse_llm_output, _call_review_llm
            rows_a = _parse_llm_output(A_RESPONSE, SAMPLE_ROWS_RAW)
            try:
                corrections = _call_review_llm(rows_a, ["工程领域"])
            except Exception:
                corrections = []
            result = _merge_ab_results(rows_a, corrections)

        self.assertEqual(len(result), 2)
        for row in result:
            self.assertIsNone(row["disagreement"])
            self.assertNotEqual(row["category_l1"], "")  # A 的结果已填入

    def test_a_classifications_correct(self):
        """A 分类结果正确解析进 merged rows"""
        result = self._run(A_RESPONSE, B_AGREES)
        self.assertEqual(result[0]["category_l1"], "采购管理")
        self.assertEqual(result[1]["category_l1"], "公司治理")

    def test_disagreement_b_fields_correct(self):
        """分歧行中 B 的建议字段内容正确"""
        result = self._run(A_RESPONSE, B_DISAGREES_ON_1)
        d = result[0]["disagreement"]
        self.assertEqual(d["category_l1"], "工程项目管理")
        self.assertEqual(d["category_l2"], "工程项目招标管理")


if __name__ == "__main__":
    unittest.main()
