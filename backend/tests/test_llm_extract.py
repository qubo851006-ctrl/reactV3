# -*- coding: utf-8 -*-
"""utils/llm_extract.py 的回归测试。

覆盖真实生产 bug：LLM 把整段 JSON 当作短类别字段返回时，
必须能正确提取出 category 字段值，而不是把整段 JSON 当作类别名。
"""
import pytest

from utils.llm_extract import extract_short_text


class TestExtractShortText:
    # ── 真实生产 bug（培训类别字段被填充了整段 JSON）─────────────
    def test_real_bug_full_json_returned_by_llm(self):
        raw = (
            '{ "topic": "AI+平台第三次培训", "location": "1720", '
            '"date": "2026.4.10", "count": 18, "category": "技术培训", '
            '"start_time": "1400", "end_time": "1530" }'
        )
        assert extract_short_text(raw, fallback="其他") == "技术培训"

    # ── 各种 LLM 跑偏的输出 ─────────────────────────────────────
    def test_markdown_code_fence_json(self):
        assert extract_short_text('```json\n{"category": "合规培训"}\n```') == "合规培训"

    def test_plain_markdown_fence(self):
        assert extract_short_text('```\n合规培训\n```') == "合规培训"

    def test_chinese_colon_prefix(self):
        assert extract_short_text("类别：合规培训") == "合规培训"

    def test_ascii_colon_prefix(self):
        assert extract_short_text("类别: 合规培训") == "合规培训"

    def test_ascii_quotes(self):
        assert extract_short_text('"合规培训"') == "合规培训"

    def test_chinese_quotes(self):
        assert extract_short_text("“合规培训”") == "合规培训"

    def test_corner_brackets(self):
        assert extract_short_text("「合规培训」") == "合规培训"

    def test_normal_input(self):
        assert extract_short_text("合规培训") == "合规培训"

    def test_extra_whitespace(self):
        assert extract_short_text("   合规培训   ") == "合规培训"

    # ── 边界 / 兜底 ──────────────────────────────────────────────
    def test_empty_string_falls_back(self):
        assert extract_short_text("", fallback="其他") == "其他"

    def test_whitespace_only_falls_back(self):
        assert extract_short_text("   ", fallback="其他") == "其他"

    def test_none_falls_back(self):
        assert extract_short_text(None, fallback="其他") == "其他"

    def test_too_long_falls_back(self):
        """LLM 跑偏返回整段乱说时，长度超过 max_len 必须兜底。"""
        raw = "这是一次关于合规和法律的培训，对象是法务部全体员工"
        assert extract_short_text(raw, max_len=12, fallback="其他") == "其他"

    def test_json_without_target_key_falls_back(self):
        raw = '{"unrelated_field": "some value"}'
        # JSON 里没 category 字段，整段 JSON 长度也超过 max_len → 兜底
        assert extract_short_text(raw, max_len=12, fallback="其他") == "其他"

    def test_invalid_json_falls_back_to_raw_processing(self):
        """看起来像 JSON 但不能 parse → 按普通字符串处理（长度兜底）。"""
        raw = '{ category: 合规培训 }'  # 非法 JSON（key 没引号）
        assert extract_short_text(raw, max_len=12, fallback="其他") == "其他"

    # ── 白名单 ───────────────────────────────────────────────────
    def test_whitelist_exact_match(self):
        wl = ["合规培训", "法律培训", "审计培训"]
        assert extract_short_text("合规培训", whitelist=wl) == "合规培训"

    def test_whitelist_fuzzy_contains(self):
        """LLM 返回'合规培训类'时，白名单按 contains 命中'合规培训'。"""
        wl = ["合规培训", "法律培训"]
        assert extract_short_text("合规培训类", whitelist=wl, max_len=20) == "合规培训"

    def test_whitelist_unknown_falls_back(self):
        wl = ["合规培训", "法律培训"]
        assert extract_short_text("党建培训", whitelist=wl, fallback="其他") == "其他"

    # ── 自定义 json_keys ─────────────────────────────────────────
    def test_custom_json_keys(self):
        raw = '{"training_category": "合规培训"}'
        assert (
            extract_short_text(raw, json_keys=("category", "training_category"))
            == "合规培训"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
