import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = BACKEND_DIR / "tests" / "tmp"
sys.path.insert(0, str(BACKEND_DIR))

from file_store import atomic_write_bytes, atomic_write_text, safe_child_path
from llm_client import build_ai_http_headers, format_llm_error
from model_routes import load_model_routes, public_model_routes, save_model_routes
# After P0-3 refactor these helpers moved out of routers.chat:
#   _chunk_delta_content → skills.implementations.general_chat._chunk_delta
#   _is_model_status_question → skills.implementations.model_status.SKILL.fast_match
#   _resolve_chat_model → config.resolve_model (the wrapper in chat.py was a thin shim)
from config import resolve_model as _resolve_chat_model
from skills.implementations.general_chat import _chunk_delta as _chunk_delta_content
from skills.implementations.model_status import SKILL as _MODEL_STATUS_SKILL
_is_model_status_question = _MODEL_STATUS_SKILL.fast_match
from upload_validation import (
    UploadValidationError,
    validate_excel_upload,
    validate_image_upload,
    validate_legal_upload,
    validate_pdf_upload,
)


class UploadValidationTests(unittest.TestCase):
    def test_pdf_upload_uses_safe_basename_and_checks_magic(self):
        safe_name = validate_pdf_upload(r"..\approval.pdf", "application/pdf", b"%PDF-1.7\n")

        self.assertEqual(safe_name, "approval.pdf")

        with self.assertRaises(UploadValidationError):
            validate_pdf_upload("approval.pdf", "application/pdf", b"not a pdf")

    def test_image_upload_rejects_bad_extension_even_with_image_content_type(self):
        with self.assertRaises(UploadValidationError):
            validate_image_upload("signin.exe", "image/png", b"\x89PNG\r\n\x1a\n")

    def test_excel_upload_rejects_content_type_mismatch(self):
        with self.assertRaises(UploadValidationError):
            validate_excel_upload(
                "ledger.xlsx",
                "text/plain",
                b"PK\x03\x04fake workbook",
            )

    def test_legal_upload_accepts_real_doc_magic_and_rejects_fake_doc(self):
        doc_bytes = bytes.fromhex("D0CF11E0A1B11AE1") + b"fake legacy word body"

        self.assertEqual(
            validate_legal_upload(r"..\authorization.doc", "application/msword", doc_bytes),
            "authorization.doc",
        )

        with self.assertRaises(UploadValidationError):
            validate_legal_upload("authorization.doc", "application/msword", b"not a legacy word doc")


class FileStoreTests(unittest.TestCase):
    def test_atomic_writes_create_parent_and_replace_file(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            target = Path(tmpdir) / "nested" / "data.json"

            atomic_write_text(target, json.dumps({"v": 1}), encoding="utf-8")
            atomic_write_text(target, json.dumps({"v": 2}), encoding="utf-8")

            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"v": 2})
            self.assertFalse(list(target.parent.glob("*.tmp")))

    def test_atomic_write_bytes_replaces_existing_file(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            target = Path(tmpdir) / "out.bin"
            target.write_bytes(b"old")

            atomic_write_bytes(target, b"new")

            self.assertEqual(target.read_bytes(), b"new")

    def test_safe_child_path_rejects_path_traversal(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            base = Path(tmpdir)

            self.assertEqual(safe_child_path(base, "sess_abc.json").parent, base.resolve())
            with self.assertRaises(ValueError):
                safe_child_path(base, "..", "escape.json")


class AuthSecurityTests(unittest.TestCase):
    def test_cookie_secure_flag_can_be_enabled_by_environment(self):
        from routers import auth

        with patch.dict("os.environ", {"SESSION_COOKIE_SECURE": "true"}):
            self.assertTrue(auth._cookie_secure_enabled())
        with patch.dict("os.environ", {"SESSION_COOKIE_SECURE": "false"}):
            self.assertFalse(auth._cookie_secure_enabled())

    def test_login_attempt_limiter_blocks_repeated_failures(self):
        from routers import auth

        auth._LOGIN_FAILURES.clear()
        now = datetime.now(timezone.utc)
        with patch("routers.auth._utcnow", return_value=now):
            for _ in range(auth.LOGIN_MAX_FAILURES):
                self.assertFalse(auth._login_is_limited(1, "127.0.0.1"))
                auth._record_login_failure(1, "127.0.0.1")
            self.assertTrue(auth._login_is_limited(1, "127.0.0.1"))

        later = now + timedelta(seconds=auth.LOGIN_WINDOW_SECONDS + 1)
        with patch("routers.auth._utcnow", return_value=later):
            self.assertFalse(auth._login_is_limited(1, "127.0.0.1"))


class LedgerMergeIsolationTests(unittest.TestCase):
    def test_user_merge_outputs_are_isolated_by_result_id(self):
        from routers import ledger_merge

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            with patch.object(ledger_merge, "MERGED_DIR", Path(tmpdir)):
                path_a = ledger_merge._result_file_for(1, "merge_aaaaaaaa")
                path_b = ledger_merge._result_file_for(2, "merge_aaaaaaaa")

            self.assertNotEqual(path_a, path_b)
            self.assertIn("user_1", str(path_a))
            self.assertIn("user_2", str(path_b))

    def test_merge_result_id_rejects_path_traversal(self):
        from routers import ledger_merge

        with self.assertRaises(ValueError):
            ledger_merge._validate_result_id("../escape")


class PendingArchiveTests(unittest.TestCase):
    def test_ledger_extract_only_commits_archive_after_confirmation(self):
        from routers import ledger

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            with patch.object(ledger, "_PENDING_UPLOAD_ROOT", Path(tmpdir)), \
                 patch("routers.ledger.archive_legal_docs", return_value="archive-dir") as archive_mock:
                pending_id = ledger._create_pending_upload(
                    7,
                    [{"name": "case.pdf", "bytes": b"%PDF"}],
                    [{"doc_type": "判决书"}],
                )
                pending_dir = ledger._pending_dir_for(7, pending_id)

                self.assertTrue(pending_dir.exists())
                archive_mock.assert_not_called()

                archive_dir = ledger._commit_pending_archive(7, pending_id, "测试案件")

            self.assertEqual(archive_dir, "archive-dir")
            self.assertFalse(pending_dir.exists())
            archive_mock.assert_called_once()

    def test_training_extract_only_commits_archive_after_confirmation(self):
        from routers import training

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            with patch.object(training, "_TRAINING_PENDING_ROOT", Path(tmpdir)), \
                 patch("utils.archiver.archive_files", return_value="training-archive") as archive_mock:
                pending_id = training._create_training_pending_upload(
                    "notice.pdf",
                    b"%PDF",
                    "signin.png",
                    b"\x89PNG\r\n\x1a\n",
                )
                pending_dir = training._training_pending_dir(pending_id)

                self.assertTrue(pending_dir.exists())
                archive_mock.assert_not_called()

                archive_dir = training._archive_pending_training_upload(
                    pending_id,
                    "合规培训",
                    "2026-05-12",
                    "测试培训",
                )

            self.assertEqual(archive_dir, "training-archive")
            self.assertFalse(pending_dir.exists())
            archive_mock.assert_called_once()


class PerformanceTraceTests(unittest.TestCase):
    def test_perf_trace_logs_step_and_total_duration(self):
        from perf_trace import PerfTrace

        with self.assertLogs("perf", level="INFO") as captured:
            trace = PerfTrace("unit_flow", user_id=3)
            with trace.step("parse_pdf"):
                pass
            trace.finish()

        output = "\n".join(captured.output)
        self.assertIn("perf.step flow=unit_flow step=parse_pdf user=3", output)
        self.assertIn("perf.total flow=unit_flow user=3", output)


class LlmClientTests(unittest.TestCase):
    def test_stream_chunk_without_choices_is_ignored(self):
        self.assertIsNone(_chunk_delta_content(SimpleNamespace(choices=[])))

    def test_stream_chunk_extracts_delta_content(self):
        chunk = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="你好"))]
        )

        self.assertEqual(_chunk_delta_content(chunk), "你好")

    def test_requested_chat_model_must_be_allowed(self):
        allowed = ["qwen2.5-72b", "DeepSeek-V3", "glm-5-outside"]

        self.assertEqual(_resolve_chat_model("DeepSeek-V3", allowed, "qwen2.5-72b"), "DeepSeek-V3")
        self.assertEqual(_resolve_chat_model("unknown-model", allowed, "qwen2.5-72b"), "qwen2.5-72b")

    def test_model_resolution_falls_back_to_first_allowed_when_default_is_missing(self):
        self.assertEqual(_resolve_chat_model("", ["DeepSeek-V3"], "qwen2.5-72b"), "DeepSeek-V3")

    def test_model_status_question_is_detected(self):
        self.assertTrue(_is_model_status_question("你是什么模型"))
        self.assertTrue(_is_model_status_question("当前模型是什么？"))
        self.assertFalse(_is_model_status_question("请帮我起草授权请示"))

    def test_compliance_ledger_download_intent_is_supported(self):
        # After P0-3 refactor: intent metadata lives on the skill itself.
        from skills.dispatcher import Dispatcher

        d = Dispatcher()
        skill = next(
            (s for s in d.skills if s.intent == "download_compliance_excel"),
            None,
        )
        self.assertIsNotNone(skill, "download_compliance_excel skill missing")
        self.assertEqual(skill.next_stage, "download_compliance_excel")
        self.assertTrue(skill.reply, "fixed reply must be non-empty")

    def test_runtime_model_routes_can_be_loaded_from_json(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            path = Path(tmpdir) / "model_routes.json"
            path.write_text(json.dumps({
                "default_chat_model": "DeepSeek-V3",
                "default_vision_model": "qwen2.5-vl-72b",
                "chat_models": ["qwen2.5-72b", "DeepSeek-V3"],
                "vision_models": ["qwen2.5-vl-72b"],
            }), encoding="utf-8")

            routes = load_model_routes(path)

            self.assertEqual(routes["default_chat_model"], "DeepSeek-V3")
            self.assertEqual(routes["chat_models"], ["qwen2.5-72b", "DeepSeek-V3"])

    def test_runtime_model_routes_public_shape_has_labels(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            path = Path(tmpdir) / "model_routes.json"
            save_model_routes({
                "default_chat_model": "deepseek-v4-flash",
                "chat_models": ["deepseek-v4-flash"],
                "vision_models": ["qwen2.5-vl-72b"],
            }, path)

            routes = public_model_routes(path)

            self.assertEqual(routes["default_chat_model"], "deepseek-v4-flash")
            self.assertEqual(routes["chat_models"][0]["value"], "deepseek-v4-flash")
            self.assertEqual(routes["chat_models"][0]["label"], "DeepSeek V4 Flash")

    def test_host_header_is_optional(self):
        self.assertEqual(build_ai_http_headers("aiplus.airchina.com.cn:18080"), {"Host": "aiplus.airchina.com.cn:18080"})
        self.assertEqual(build_ai_http_headers(""), {})

    def test_certificate_verify_failure_gets_actionable_message(self):
        message = format_llm_error(
            Exception(
                "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                "IP address mismatch, certificate is not valid for '10.150.224.182'"
            )
        )

        self.assertIn("AI 服务连接失败", message)
        self.assertIn("证书校验失败", message)
        self.assertIn("AI_HTTP_VERIFY_SSL=false", message)

    def test_audit_review_model_uses_deepseek_not_global_default(self):
        import llm_audit
        from skills.tracer import NoopTracer
        from routers.audit import _call_review_llm

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "[]"
        mock_client.chat.completions.create.return_value = mock_response

        original_tracer = llm_audit._tracer
        llm_audit.set_tracer(NoopTracer())
        try:
            with patch("routers.audit.get_llm_client", return_value=mock_client):
                _call_review_llm([{
                    "seq": 1,
                    "issue": "issue",
                    "description": "",
                    "category_l1": "其他",
                    "category_l2": "其他",
                    "domain": "工程领域",
                }], ["工程领域"])
        finally:
            llm_audit._tracer = original_tracer

        self.assertEqual(mock_client.chat.completions.create.call_args.kwargs["model"], "deepseek-v4-flash")

    def test_audit_cross_check_models_are_fixed_without_removing_glm_globally(self):
        from routers.audit import AUDIT_CLASSIFY_MODEL, AUDIT_REVIEW_MODEL
        from model_routes import load_model_routes

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            path = Path(tmpdir) / "model_routes.json"
            path.write_text(json.dumps({
                "default_chat_model": "glm-5-outside",
                "chat_models": ["qwen2.5-72b", "DeepSeek-V3", "glm-5-outside"],
                "vision_models": ["qwen2.5-vl-72b"],
            }), encoding="utf-8")

            routes = load_model_routes(path)

        self.assertEqual(AUDIT_CLASSIFY_MODEL, "qwen3.6")
        self.assertEqual(AUDIT_REVIEW_MODEL, "deepseek-v4-flash")
        self.assertIn("glm-5-outside", routes["chat_models"])


class LedgerOcrResponseTests(unittest.TestCase):
    def test_low_quality_pdf_text_needs_ocr(self):
        import ledger_helpers

        noisy_text = "4 4 4 4 2 2 2 2 8: 8: 8: 8: " * 20
        good_text = "四川省成都市中级人民法院民事判决书。上诉人因房屋租赁合同纠纷一案提起上诉。"

        self.assertTrue(ledger_helpers.needs_ocr_text(noisy_text))
        self.assertFalse(ledger_helpers.needs_ocr_text(good_text))

    def test_case_number_extraction_allows_ocr_spaces(self):
        import ledger_helpers

        text = "原审案号为（2022）川 0107 民初 20339 号，本案为二审。"

        self.assertEqual(
            ledger_helpers._extract_case_numbers_from_text(text),
            ["(2022)川 0107 民初 20339 号"],
        )

    def test_airchina_ocr_extracts_payload_markdown(self):
        import ledger_helpers

        result = {
            "header": {"code": 0},
            "payload": {"markdown": "```markdown\nOCR text\n```"},
        }

        self.assertEqual(ledger_helpers._extract_ocr_text_from_result(result), "OCR text")

    def test_airchina_ocr_extracts_document_markdown(self):
        import ledger_helpers

        result = {
            "header": {"code": 0},
            "payload": {
                "result": {
                    "document": [
                        {"name": "json", "value": "{}"},
                        {"name": "markdown", "value": "Court text"},
                    ]
                }
            },
        }

        self.assertEqual(ledger_helpers._extract_ocr_text_from_result(result), "Court text")

    def test_airchina_ocr_request_uses_shared_host_header(self):
        import ledger_helpers

        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"header": {"code": 0}, "payload": {"markdown": "ok"}}

        class FakeClient:
            def __init__(self, **kwargs):
                captured["client_kwargs"] = kwargs

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def post(self, url, headers, json):
                captured["url"] = url
                captured["headers"] = headers
                captured["json"] = json
                return FakeResponse()

        with patch.object(ledger_helpers, "AIRCHINA_API_KEY", "key"), \
             patch.object(ledger_helpers, "AIRCHINA_BASE_URL", "http://ai.local/v1"), \
             patch.object(ledger_helpers, "_AIRCHINA_OCR_CHANNEL", "25"), \
             patch.object(
                 ledger_helpers,
                 "build_ai_http_headers",
                 return_value={"Host": "aiplus.airchina.com.cn:18080"},
             ), \
             patch("httpx.Client", FakeClient):
            idx, text = ledger_helpers._ocr_page_with_airchina(3, "abc")

        self.assertEqual(idx, 3)
        self.assertEqual(text, "ok")
        self.assertEqual(captured["headers"]["Host"], "aiplus.airchina.com.cn:18080")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer key")
        self.assertEqual(captured["url"], "http://ai.local/v1/oneapi/proxy/25/")


class OllamaModelRoutingTests(unittest.TestCase):
    """视觉客户端路由：Ollama 本地模型 vs 云端 AI 平台"""

    def _make_mock_client(self):
        return MagicMock()

    def test_routes_to_ollama_when_url_configured(self):
        """qwen3-vl:8b + OLLAMA_BASE_URL 已设置 → 使用 Ollama 客户端"""
        import utils.image_analyzer as ia
        mock_ollama = self._make_mock_client()
        mock_regular = self._make_mock_client()
        with patch.object(ia, 'OLLAMA_BASE_URL', 'http://192.168.9.226:11434/v1'), \
             patch.object(ia, 'get_ollama_client', return_value=mock_ollama) as spy_ollama, \
             patch.object(ia, 'get_client', return_value=mock_regular) as spy_regular:
            ia.get_vision_client('qwen3-vl:8b')
            spy_ollama.assert_called_once()
            spy_regular.assert_not_called()

    def test_falls_back_to_cloud_for_non_ollama_model(self):
        """云端模型（qwen2.5-vl-72b）始终走 AI 平台客户端"""
        import utils.image_analyzer as ia
        mock_client = self._make_mock_client()
        with patch.object(ia, 'get_ollama_client', return_value=mock_client) as spy_ollama, \
             patch.object(ia, 'get_client', return_value=mock_client) as spy_regular:
            ia.get_vision_client('qwen2.5-vl-72b')
            spy_regular.assert_called_once()
            spy_ollama.assert_not_called()

    def test_falls_back_to_cloud_when_ollama_url_empty(self):
        """qwen3-vl:8b 但 OLLAMA_BASE_URL 为空 → 回退到 AI 平台客户端"""
        import utils.image_analyzer as ia
        mock_client = self._make_mock_client()
        with patch.object(ia, 'OLLAMA_BASE_URL', ''), \
             patch.object(ia, 'get_ollama_client', return_value=mock_client) as spy_ollama, \
             patch.object(ia, 'get_client', return_value=mock_client) as spy_regular:
            ia.get_vision_client('qwen3-vl:8b')
            spy_regular.assert_called_once()
            spy_ollama.assert_not_called()


class OllamaModelLabelTests(unittest.TestCase):
    """Ollama 模型在运行时路由中的标签与加载"""

    def test_ollama_model_label_in_public_routes(self):
        """public_model_routes 返回 qwen3-vl:8b 的中文标签"""
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            path = Path(tmpdir) / "model_routes.json"
            save_model_routes({
                "vision_models": ["qwen2.5-vl-72b", "qwen3-vl:8b"],
            }, path)
            routes = public_model_routes(path)
            labels = {m["value"]: m["label"] for m in routes["vision_models"]}
            self.assertEqual(labels.get("qwen3-vl:8b"), "Qwen3 VL 8B (本地)")

    def test_ollama_model_preserved_after_load(self):
        """model_routes.json 中包含 qwen3-vl:8b 时正确加载，不丢失"""
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            path = Path(tmpdir) / "model_routes.json"
            path.write_text(json.dumps({
                "vision_models": ["qwen2.5-vl-72b", "qwen3-vl:8b"],
            }), encoding="utf-8")
            routes = load_model_routes(path)
            self.assertIn("qwen3-vl:8b", routes["vision_models"])

    def test_ollama_model_is_valid_default_vision_model(self):
        """可以将 qwen3-vl:8b 设为默认视觉模型"""
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            path = Path(tmpdir) / "model_routes.json"
            save_model_routes({
                "default_vision_model": "qwen3-vl:8b",
                "vision_models": ["qwen2.5-vl-72b", "qwen3-vl:8b"],
            }, path)
            routes = load_model_routes(path)
            self.assertEqual(routes["default_vision_model"], "qwen3-vl:8b")


class LedgerArchiveSameCaseTests(unittest.TestCase):
    """同一案件的文书应归档到同一文件夹，不因案件名称差异产生多个文件夹。"""

    def test_matched_case_uses_existing_name_for_archive(self):
        """匹配到已有案件时，_commit_pending_archive 使用已有案件名称归档。"""
        from routers import ledger

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            archive_calls = []

            def fake_archive(files_data, docs, case_name):
                archive_calls.append(case_name)
                return str(Path(tmpdir) / case_name)

            with patch.object(ledger, "_PENDING_UPLOAD_ROOT", Path(tmpdir)), \
                 patch("routers.ledger.archive_legal_docs", side_effect=fake_archive):
                pending_id = ledger._create_pending_upload(
                    1,
                    [{"name": "二审判决书.pdf", "bytes": b"%PDF"}],
                    [{"doc_type": "二审判决书"}],
                )
                # 模拟：已有案件名称为"甲公司诉乙公司合同纠纷案"
                existing_name = "甲公司诉乙公司合同纠纷案"
                ledger._commit_pending_archive(1, pending_id, existing_name)

            self.assertEqual(archive_calls, [existing_name])

    def test_archive_reuses_existing_folder(self):
        """同一 case_name 多次调用 archive_legal_docs 应写入同一文件夹。"""
        import ledger_helpers

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            # archive_legal_docs moved to ledger_archive in commit 01b0955;
            # patch the new module so the tempdir override actually applies.
            import ledger_archive
            with patch.object(ledger_archive, "LEGAL_ARCHIVE_ROOT", tmpdir):
                dir1 = ledger_helpers.archive_legal_docs(
                    [{"name": "起诉状.pdf", "bytes": b"%PDF-1"}],
                    [{"doc_type": "起诉状"}],
                    "甲公司诉乙公司合同纠纷案",
                )
                dir2 = ledger_helpers.archive_legal_docs(
                    [{"name": "判决书.pdf", "bytes": b"%PDF-2"}],
                    [{"doc_type": "一审判决书"}],
                    "甲公司诉乙公司合同纠纷案",
                )

            self.assertEqual(dir1, dir2)
            files = list(Path(dir1).iterdir())
            self.assertEqual(len(files), 2)
            names = sorted(f.name for f in files)
            self.assertIn("起诉状_起诉状.pdf", names)
            self.assertIn("一审判决书_判决书.pdf", names)

    def test_different_case_names_create_separate_folders(self):
        """不同案件名称应产生不同文件夹。"""
        import ledger_helpers

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            # archive_legal_docs moved to ledger_archive in commit 01b0955;
            # patch the new module so the tempdir override actually applies.
            import ledger_archive
            with patch.object(ledger_archive, "LEGAL_ARCHIVE_ROOT", tmpdir):
                dir1 = ledger_helpers.archive_legal_docs(
                    [{"name": "a.pdf", "bytes": b"%PDF"}],
                    [{"doc_type": "起诉状"}],
                    "案件A",
                )
                dir2 = ledger_helpers.archive_legal_docs(
                    [{"name": "b.pdf", "bytes": b"%PDF"}],
                    [{"doc_type": "起诉状"}],
                    "案件B",
                )

            self.assertNotEqual(dir1, dir2)

    def test_empty_case_name_falls_back_to_unknown(self):
        """案件名称为空时，归档目录应为'未知案件'，不应使用文件名。"""
        import ledger_helpers

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT) as tmpdir:
            # archive_legal_docs moved to ledger_archive in commit 01b0955;
            # patch the new module so the tempdir override actually applies.
            import ledger_archive
            with patch.object(ledger_archive, "LEGAL_ARCHIVE_ROOT", tmpdir):
                dir_path = ledger_helpers.archive_legal_docs(
                    [{"name": "起诉状.pdf", "bytes": b"%PDF"}],
                    [{"doc_type": "起诉状"}],
                    "",
                )

            self.assertIn("未知案件", dir_path)
            self.assertNotIn("起诉状.pdf", dir_path)


class SignInParseTests(unittest.TestCase):
    """parse_sign_in_result：AI 返回文本解析"""

    def setUp(self):
        from utils.image_analyzer import parse_sign_in_result
        self.parse = parse_sign_in_result

    def test_parses_full_result(self):
        text = "主题：安全培训\n地点：会议室A\n时间：2026-05-08\n人数：23"
        result = self.parse(text)
        self.assertEqual(result["topic"], "安全培训")
        self.assertEqual(result["location"], "会议室A")
        self.assertEqual(result["date"], "2026-05-08")
        self.assertEqual(result["count"], 23)

    def test_count_extracts_digits_only(self):
        """人数字段含多余文字时只取数字"""
        result = self.parse("人数：共 12 人")
        self.assertEqual(result["count"], 12)

    def test_missing_fields_default_to_empty(self):
        """缺失字段返回默认空值，不报错"""
        result = self.parse("人数：5")
        self.assertEqual(result["topic"], "")
        self.assertEqual(result["count"], 5)

    def test_invalid_count_defaults_to_zero(self):
        """人数无法解析时返回 0"""
        result = self.parse("人数：不详")
        self.assertEqual(result["count"], 0)


if __name__ == "__main__":
    unittest.main()
