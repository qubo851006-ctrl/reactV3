"""Safety-net tests for ledger_helpers pure functions before the #5 refactor.

These functions (OCR text extraction, doc-type detection, case-number
normalization) sit in the low-coverage region of ledger_helpers and are
exactly what will be moved out into an ocr_helpers module. Locking their
behavior here means the refactor can't silently change it.
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import ledger_helpers as lh


# ── _strip_ocr_text ──────────────────────────────────────────────────────────

class TestStripOcrText:
    def test_plain_text_unchanged(self):
        assert lh._strip_ocr_text("  hello  ") == "hello"

    def test_strips_json_code_fence(self):
        assert lh._strip_ocr_text("```json\n{\"a\":1}\n```") == '{"a":1}'

    def test_strips_bare_fence(self):
        assert lh._strip_ocr_text("```\ncontent\n```") == "content"


# ── _collect_ocr_texts ───────────────────────────────────────────────────────

class TestCollectOcrTexts:
    def test_plain_string(self):
        assert lh._collect_ocr_texts("text") == ["text"]

    def test_empty_string_skipped(self):
        assert lh._collect_ocr_texts("   ") == []

    def test_list_flattened(self):
        assert lh._collect_ocr_texts(["a", "b"]) == ["a", "b"]

    def test_dict_picks_known_keys(self):
        out = lh._collect_ocr_texts({"markdown": "m", "text": "t", "other": "ignored"})
        assert "m" in out and "t" in out
        assert "ignored" not in out

    def test_nested_dict_recurses(self):
        out = lh._collect_ocr_texts({"wrap": {"content": "deep"}})
        assert out == ["deep"]


# ── _extract_ocr_text_from_result ────────────────────────────────────────────

class TestExtractOcrTextFromResult:
    def test_payload_markdown_wins(self):
        result = {"payload": {"markdown": "# title"}}
        assert lh._extract_ocr_text_from_result(result) == "# title"

    def test_payload_result_markdown(self):
        result = {"payload": {"result": {"markdown": "body"}}}
        assert lh._extract_ocr_text_from_result(result) == "body"

    def test_document_named_markdown(self):
        result = {"payload": {"result": {"document": [
            {"name": "markdown", "value": "doc text"},
        ]}}}
        assert lh._extract_ocr_text_from_result(result) == "doc text"

    def test_empty_result(self):
        assert lh._extract_ocr_text_from_result({}) == ""


# ── detect_doc_type_by_content ───────────────────────────────────────────────

class TestDetectDocType:
    def test_empty_returns_other(self):
        assert lh.detect_doc_type_by_content("") == "其他"

    @pytest.mark.parametrize("text,expected", [
        ("强制执行申请书\n申请人...", "强制执行申请书"),
        ("再审申请书\n申请人...", "再审申请书"),
        ("民事上诉状\n上诉人...", "上诉状"),
        ("民事起诉状\n原告...", "起诉状"),
    ])
    def test_keyword_match(self, text, expected):
        assert lh.detect_doc_type_by_content(text) == expected

    def test_appeal_before_complaint(self):
        # "上诉状" must win over "起诉状" when both substrings could appear
        assert lh.detect_doc_type_by_content("民事上诉状") == "上诉状"


# ── needs_ocr_text ───────────────────────────────────────────────────────────

class TestNeedsOcrText:
    def test_empty_needs_ocr(self):
        assert lh.needs_ocr_text("") is True
        assert lh.needs_ocr_text("   ") is True

    def test_rich_chinese_no_ocr(self):
        assert lh.needs_ocr_text("这是一份内容相当充实的法律文书正文足够长超过二十个汉字了的确如此") is False

    def test_too_few_chinese_needs_ocr(self):
        assert lh.needs_ocr_text("abc 123") is True


# ── case-number normalization ────────────────────────────────────────────────

class TestCaseNumber:
    def test_normalize_fullwidth_parens(self):
        assert lh._normalize_case_no("（2024）京01民初123號") == "(2024)京01民初123号"

    def test_case_no_key_strips_spaces(self):
        assert lh._case_no_key(" (2024) 京01 民初 123号 ") == "(2024)京01民初123号"

    def test_dedupe_keeps_first_form(self):
        out = lh._dedupe_case_numbers(["（2024）京01民初1号", "(2024)京01民初1号", "（2024）京01民初2号"])
        # first two normalize to the same key -> deduped to one
        assert len(out) == 2

    def test_dedupe_drops_empty(self):
        assert lh._dedupe_case_numbers(["", "  "]) == []


if __name__ == "__main__":
    import unittest
    unittest.main()
