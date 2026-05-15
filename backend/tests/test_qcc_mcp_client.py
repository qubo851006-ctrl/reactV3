"""
单元测试：utils/qcc_mcp_client.py 中的纯函数与格式化逻辑
覆盖：_parse_mcp_response, _extract_content, _format_value, format_company_markdown
"""
import json
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


class _MockResponse:
    """最小化 httpx.Response 替代。"""

    def __init__(self, text: str, content_type: str = "application/json", json_data: dict | None = None):
        self.text = text
        self.headers = {"content-type": content_type}
        self._json_data = json_data or {}

    def json(self) -> dict:
        return self._json_data


# ── _parse_mcp_response ────────────────────────────────────────────────────


class ParseMcpResponseTests(unittest.TestCase):
    def _fn(self):
        from utils.qcc_mcp_client import _parse_mcp_response
        return _parse_mcp_response

    def test_sse_stream_extracts_result(self):
        fn = self._fn()
        text = 'data: {"jsonrpc":"2.0","result":{"tools":[{"name":"t1"}]}}\n'
        resp = _MockResponse(text, "text/event-stream")
        self.assertEqual(fn(resp), {"tools": [{"name": "t1"}]})

    def test_json_response_extracts_result(self):
        fn = self._fn()
        payload = {"result": {"content": [{"text": "hello"}]}}
        resp = _MockResponse(json.dumps(payload), "application/json", payload)
        self.assertEqual(fn(resp), {"content": [{"text": "hello"}]})

    def test_sse_detected_by_data_prefix(self):
        """content-type 不是 event-stream，但 body 以 data: 开头时也按 SSE 解析。"""
        fn = self._fn()
        text = 'data: {"result": {"ok": true}}\n'
        resp = _MockResponse(text, "application/json")
        self.assertEqual(fn(resp), {"ok": True})

    def test_returns_empty_dict_when_no_result_key(self):
        fn = self._fn()
        resp = _MockResponse('data: {"id": 1}\n', "text/event-stream")
        self.assertEqual(fn(resp), {})

    def test_returns_empty_dict_on_bad_json(self):
        fn = self._fn()
        resp = _MockResponse("data: not-json\n", "text/event-stream")
        self.assertEqual(fn(resp), {})


# ── _extract_content ──────────────────────────────────────────────────────


class ExtractContentTests(unittest.TestCase):
    def _fn(self):
        from utils.qcc_mcp_client import _extract_content
        return _extract_content

    def test_json_text_decoded(self):
        fn = self._fn()
        result = {"content": [{"text": '{"name": "华为"}'}]}
        self.assertEqual(fn(result), {"name": "华为"})

    def test_plain_text_returned_as_str(self):
        fn = self._fn()
        result = {"content": [{"text": "无结构文本"}]}
        self.assertEqual(fn(result), "无结构文本")

    def test_empty_content_list_returns_none(self):
        fn = self._fn()
        self.assertIsNone(fn({"content": []}))

    def test_missing_content_key_returns_none(self):
        fn = self._fn()
        self.assertIsNone(fn({}))

    def test_empty_text_returns_none(self):
        fn = self._fn()
        self.assertIsNone(fn({"content": [{"text": ""}]}))


# ── _format_value ─────────────────────────────────────────────────────────


class FormatValueTests(unittest.TestCase):
    def _fn(self):
        from utils.qcc_mcp_client import _format_value
        return _format_value

    def test_none_and_empty_yield_dash(self):
        fn = self._fn()
        for v in (None, "", [], {}):
            self.assertEqual(fn(v), "—", f"期望 — 但得到 {fn(v)!r}，输入：{v!r}")

    def test_bool_values(self):
        fn = self._fn()
        self.assertEqual(fn(True), "是")
        self.assertEqual(fn(False), "否")

    def test_numbers(self):
        fn = self._fn()
        self.assertEqual(fn(42), "42")
        self.assertEqual(fn(3.14), "3.14")

    def test_string_passthrough(self):
        fn = self._fn()
        self.assertEqual(fn("测试字符串"), "测试字符串")

    def test_list_preview_with_count(self):
        fn = self._fn()
        result = fn(["a", "b", "c", "d"])
        self.assertIn("a", result)
        self.assertIn("共 4 条", result)

    def test_list_short_no_suffix(self):
        fn = self._fn()
        result = fn(["a", "b"])
        self.assertNotIn("共", result)

    def test_dict_expansion(self):
        fn = self._fn()
        result = fn({"name": "华为", "status": "正常"})
        self.assertIn("name：华为", result)
        self.assertIn("status：正常", result)


# ── format_company_markdown ──────────────────────────────────────────────


class FormatCompanyMarkdownTests(unittest.TestCase):
    def test_renders_all_sections(self):
        from utils.qcc_mcp_client import format_company_markdown
        result = {
            "precise_name": "测试科技有限公司",
            "company": {
                "工商登记信息": {"name": "测试科技有限公司", "status": "存续"},
                "主要人员": [{"name": "张三", "position": "法定代表人"}],
                "股东结构": [{"name": "股东甲", "ratio": "60%"}],
            },
            "risk": {
                "失信被执行": [],
                "被执行信息": [],
                "行政处罚": [],
            },
        }
        md = format_company_markdown(result)
        self.assertIn("测试科技有限公司", md)
        self.assertIn("企查查", md)
        self.assertIn("基本信息", md)
        self.assertIn("风险信息", md)

    def test_renders_with_minimal_data(self):
        from utils.qcc_mcp_client import format_company_markdown
        result = {"precise_name": "极简企业", "company": {}, "risk": {}}
        md = format_company_markdown(result)
        self.assertIn("极简企业", md)

    def test_unknown_company_fallback(self):
        from utils.qcc_mcp_client import format_company_markdown
        result = {}
        md = format_company_markdown(result)
        self.assertIn("未知企业", md)


if __name__ == "__main__":
    unittest.main()
