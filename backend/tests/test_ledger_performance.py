import base64
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


class _TrackedClient:
    def __init__(self, responder, delay=0.03):
        self._responder = responder
        self._delay = delay
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self._delay)
            content = self._responder(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )
        finally:
            with self._lock:
                self.active -= 1


class LedgerPerformanceTests(unittest.TestCase):
    def test_ledger_extract_docs_processes_uploaded_files_concurrently(self):
        from routers import ledger

        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_extract(_bytes, filename):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.06)
                return f"text for {filename}"
            finally:
                with lock:
                    active -= 1

        files_data = [
            {"name": "a.pdf", "bytes": b"%PDF-a"},
            {"name": "b.pdf", "bytes": b"%PDF-b"},
            {"name": "c.pdf", "bytes": b"%PDF-c"},
        ]

        with patch.object(ledger, "LEDGER_DOC_CONCURRENCY", 3), \
             patch("routers.ledger.extract_file_text", side_effect=fake_extract), \
             patch("routers.ledger.needs_ocr_text", return_value=False), \
             patch("routers.ledger.detect_doc_type_by_content", return_value="起诉状"):
            docs = ledger._extract_ledger_docs(files_data, "vision-model", lambda _msg: None)

        self.assertEqual([doc["filename"] for doc in docs], ["a.pdf", "b.pdf", "c.pdf"])
        self.assertGreaterEqual(max_active, 2)

    def test_ocr_single_page_skips_airchina_after_circuit_breaker_opens(self):
        import ledger_helpers

        fake_client = _TrackedClient(lambda _kwargs: "vision fallback", delay=0.01)
        with patch.object(ledger_helpers, "AIRCHINA_API_KEY", "key"), \
             patch.object(ledger_helpers, "AIRCHINA_OCR_FAILURE_THRESHOLD", 1), \
             patch.object(ledger_helpers, "AIRCHINA_OCR_BREAKER_SECONDS", 60), \
             patch.object(ledger_helpers, "_ocr_page_with_airchina", side_effect=RuntimeError("down")) as airchina_mock, \
             patch("ledger_helpers.get_llm_client", return_value=fake_client), \
             patch("ledger_helpers.resolve_vision_model", return_value="vision-model"):
            ledger_helpers.reset_airchina_ocr_breaker()
            first = ledger_helpers.ocr_single_page("abc", "vision-model")
            second = ledger_helpers.ocr_single_page("abc", "vision-model")
            ledger_helpers.reset_airchina_ocr_breaker()

        self.assertEqual(first, "vision fallback")
        self.assertEqual(second, "vision fallback")
        self.assertEqual(airchina_mock.call_count, 1)

    def test_auth_request_documents_are_generated_in_parallel(self):
        from utils import auth_request_drafter

        active = 0
        max_active = 0
        lock = threading.Lock()

        def tracked_result(name):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.06)
                return name
            finally:
                with lock:
                    active -= 1

        with patch.object(auth_request_drafter, "draft_auth_request", side_effect=lambda info: tracked_result("request")), \
             patch.object(auth_request_drafter, "draft_auth_letter", side_effect=lambda info: tracked_result("letter")):
            docs = auth_request_drafter.draft_auth_documents({"项目名称": "测试项目"})

        self.assertEqual(docs, {"auth_content": "request", "letter_content": "letter"})
        # 并发性由 max_active >= 2 确凿证明(两个任务曾同时活跃)。
        # 原 assertLess(elapsed, 0.11) 是基于 wall-clock 的脆弱断言:机器负载高时
        # (如 pre-push 钩子里 pytest 跑)线程调度开销会让并发耗时也偶发 >0.11s,
        # 造成无关 commit 被钩子误拦,已移除。
        self.assertGreaterEqual(max_active, 2)

    def test_ocr_pdf_with_vision_processes_pages_concurrently_and_preserves_order(self):
        import ledger_helpers

        class FakePixmap:
            def __init__(self, text):
                self.text = text

            def tobytes(self, *_args, **_kwargs):
                return self.text.encode("utf-8")

        class FakePage:
            def __init__(self, idx):
                self.idx = idx

            def get_pixmap(self, dpi):
                self.assert_dpi = dpi
                return FakePixmap(f"page-{self.idx}")

        class FakeDoc:
            def __iter__(self):
                return iter([FakePage(1), FakePage(2), FakePage(3)])

            def close(self):
                pass

        def fake_open(**_kwargs):
            return FakeDoc()

        def responder(kwargs):
            image_url = kwargs["messages"][0]["content"][0]["image_url"]["url"]
            payload = image_url.rsplit(",", 1)[1]
            page_marker = base64.b64decode(payload).decode("utf-8")
            if page_marker == "page-1":
                time.sleep(0.08)
            return f"text-{page_marker}"

        fake_client = _TrackedClient(responder, delay=0.01)

        with patch.dict(sys.modules, {"fitz": SimpleNamespace(open=fake_open)}), \
             patch("ledger_helpers.get_llm_client", return_value=fake_client), \
             patch("ledger_helpers.resolve_vision_model", return_value="vision-model"), \
             patch.object(ledger_helpers, "LEDGER_OCR_CONCURRENCY", 3):
            text = ledger_helpers.ocr_pdf_with_vision(b"%PDF")

        self.assertEqual(text, "text-page-1\ntext-page-2\ntext-page-3")
        self.assertGreaterEqual(fake_client.max_active, 2)

    def test_extract_case_fields_extracts_multiple_documents_concurrently(self):
        import ledger_helpers

        def responder(kwargs):
            prompt = kwargs["messages"][0]["content"]
            if "强制执行时间" in prompt:
                return json.dumps({"强制执行时间": "2024-03-01"}, ensure_ascii=False)
            if "处理结果" in prompt and "本案案号" in prompt:
                return json.dumps({
                    "本案案号": "(2024)京01民初1号",
                    "关联案号": "(2023)京01民初9号",
                    "审级": "一审",
                    "生效判决日期": "2024-02-01",
                    "处理结果": "支持主要诉请",
                    "服务律所": "测试律所",
                }, ensure_ascii=False)
            return json.dumps({
                "案号": "(2023)京01民初9号",
                "案件名称": "甲公司与乙公司合同纠纷案",
                "案件发生时间": "2023-12-01",
                "案由": "合同纠纷",
                "诉讼主体": "原告：甲公司\n被告：乙公司",
                "主诉被诉": "诉讼-主诉",
                "标的金额": 12.34,
                "基本情况": "请求支付合同款。",
            }, ensure_ascii=False)

        fake_client = _TrackedClient(responder, delay=0.04)
        docs = [
            {"filename": "起诉状.pdf", "text": "起诉状正文", "doc_type": "起诉状"},
            {"filename": "判决书.pdf", "text": "判决书正文", "doc_type": "一审判决书"},
            {"filename": "执行申请.pdf", "text": "执行申请正文", "doc_type": "强制执行申请书"},
        ]

        with patch("ledger_helpers.get_llm_client", return_value=fake_client), \
             patch.object(ledger_helpers, "LEDGER_LLM_CONCURRENCY", 3):
            case = ledger_helpers.extract_case_fields(docs)

        self.assertEqual(case["案件名称"], "甲公司与乙公司合同纠纷案")
        self.assertEqual(case["强制执行时间"], "2024-03-01")
        self.assertEqual(case["生效判决日期"], "2024-02-01")
        self.assertEqual(case["服务律所"], "测试律所")
        self.assertEqual(case["stages"], [{
            "审级": "一审",
            "处理结果": "2024年2月1日作出（2024）京01民初1号一审判决：支持主要诉请。",
        }])
        self.assertIn("(2023)京01民初9号", case["案号列表"])
        self.assertIn("(2024)京01民初1号", case["案号列表"])
        self.assertGreaterEqual(fake_client.max_active, 2)

    def test_extract_case_fields_keeps_other_documents_when_one_document_fails(self):
        import ledger_helpers

        def responder(kwargs):
            prompt = kwargs["messages"][0]["content"]
            if "处理结果" in prompt and "本案案号" in prompt:
                raise RuntimeError("model failed")
            return json.dumps({
                "案号": "(2023)京01民初9号",
                "案件名称": "甲公司与乙公司合同纠纷案",
                "案件发生时间": "2023-12-01",
                "案由": "合同纠纷",
                "诉讼主体": "原告：甲公司\n被告：乙公司",
                "主诉被诉": "诉讼-主诉",
                "标的金额": 12.34,
                "基本情况": "请求支付合同款。",
            }, ensure_ascii=False)

        docs = [
            {"filename": "起诉状.pdf", "text": "起诉状正文", "doc_type": "起诉状"},
            {"filename": "判决书.pdf", "text": "判决书正文", "doc_type": "一审判决书"},
        ]

        with patch("ledger_helpers.get_llm_client", return_value=_TrackedClient(responder)):
            case = ledger_helpers.extract_case_fields(docs)

        self.assertEqual(case["案件名称"], "甲公司与乙公司合同纠纷案")
        self.assertEqual(case["案号列表"], ["(2023)京01民初9号"])
        self.assertEqual(case["stages"], [])

    def test_extract_case_fields_formats_judgment_result_for_management_ledger(self):
        import ledger_helpers

        def responder(kwargs):
            prompt = kwargs["messages"][0]["content"]
            if "处理结果" in prompt and "本案案号" in prompt:
                return json.dumps({
                    "本案案号": "(2025)京0105民初48286号",
                    "关联案号": None,
                    "法院名称": "北京朝阳法院",
                    "审级": "一审",
                    "生效判决日期": "2026-02-28",
                    "处理结果": "确认原租赁合同解除、保证金归国航物业所有，深通工程公司支付免租期租金、律师费共30.38万元。",
                    "后续程序": "辰州公司、马高峰及高度投资公司支付房屋占用费5万元且深通工程公司对此承担连带责任。",
                    "公司经济影响": "本案为公司挽回损失139.34万元",
                    "服务律所": None,
                }, ensure_ascii=False)
            return json.dumps({
                "案号": "(2025)京0105民初48286号",
                "案件名称": "国航物业与深通工程公司房屋租赁合同纠纷案",
                "案件发生时间": "2025-08-01",
                "案由": "房屋租赁合同纠纷",
                "诉讼主体": "原告：国航物业酒店管理有限公司\n被告一：深通工程公司",
                "主诉被诉": "诉讼-主诉",
                "标的金额": 139.34,
                "基本情况": "请求确认合同解除并支付相关费用。",
            }, ensure_ascii=False)

        docs = [
            {"filename": "起诉状.pdf", "text": "起诉状正文", "doc_type": "起诉状"},
            {"filename": "一审判决书.pdf", "text": "判决书正文", "doc_type": "一审判决书"},
        ]

        with patch("ledger_helpers.get_llm_client", return_value=_TrackedClient(responder)):
            case = ledger_helpers.extract_case_fields(docs)

        result = case["stages"][0]["处理结果"]
        self.assertIn("北京朝阳法院于2026年2月28日作出（2025）京0105民初48286号一审判决", result)
        self.assertIn("深通工程公司支付免租期租金、律师费共30.38万元", result)
        self.assertIn("辰州公司、马高峰及高度投资公司支付房屋占用费5万元", result)
        self.assertIn("本案为公司挽回损失139.34万元", result)

    def test_find_matching_case_idx_uses_case_numbers_from_judgment_text(self):
        import ledger_helpers

        existing_cases = [
            {
                "案件名称": "甲公司与乙公司租赁合同纠纷案",
                "案由": "租赁合同纠纷",
                "诉讼主体": "原告：甲公司\n被告：乙公司",
                "案号列表": ["(2022)川0107民初12345号"],
            }
        ]
        new_case = {
            "案件名称": "附件1.成都市中级人民法院民事判决书（(2023)川01民终24491号）.pdf",
            "案号列表": ["(2023)川01民终24491号"],
        }
        docs = [
            {
                "filename": "附件1.成都市中级人民法院民事判决书（(2023)川01民终24491号）.pdf",
                "doc_type": "二审判决书",
                "text": "上诉人甲公司因与被上诉人乙公司租赁合同纠纷一案，不服成都市武侯区人民法院（2022）川0107民初12345号民事判决，向本院提起上诉。",
            }
        ]

        with patch("ledger_helpers.get_llm_client") as fake_get_client:
            idx = ledger_helpers.find_matching_case_idx(new_case, existing_cases, docs)

        self.assertEqual(idx, 0)
        fake_get_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
