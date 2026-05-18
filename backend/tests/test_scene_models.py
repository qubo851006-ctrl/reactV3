"""Tests for per-scene model routing (P1-3)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from llm_audit.scene_models import (
    _parse_env_override,
    current_routing,
    reload_routing,
    resolve_model,
)


class SceneRoutingTests(unittest.TestCase):
    def setUp(self):
        reload_routing()  # ensure clean default state

    def test_known_scenes_get_routed(self):
        # Spot-check the categories that matter most
        self.assertEqual(resolve_model("extract_judgment_fields", "fallback"), "qwen2.5-72b")
        self.assertEqual(resolve_model("compliance_review", "fallback"), "DeepSeek-V3")
        self.assertEqual(resolve_model("audit_cross_review", "fallback"), "DeepSeek-V3")
        self.assertEqual(resolve_model("intent_classify", "fallback"), "DeepSeek-V3")

    def test_unknown_scene_falls_back_to_caller_model(self):
        self.assertEqual(resolve_model("brand_new_scene_xyz", "fallback-m"), "fallback-m")

    def test_vision_scenes_pass_through(self):
        """Vision scenes are intentionally not in the table — they preserve
        whatever the caller (resolve_vision_model) chose."""
        self.assertEqual(resolve_model("vision_ocr_page", "qwen2.5-vl-72b"), "qwen2.5-vl-72b")
        self.assertEqual(resolve_model("vision_analyze_image", "qwen3-vl:8b"), "qwen3-vl:8b")

    def test_env_override_takes_precedence(self):
        with patch.dict("os.environ", {
            "SCENE_MODELS": "extract_judgment_fields:experimental-model-v2,compliance_review:custom-judge",
        }):
            reload_routing()
            self.assertEqual(resolve_model("extract_judgment_fields", "x"), "experimental-model-v2")
            self.assertEqual(resolve_model("compliance_review", "x"), "custom-judge")
            # Untouched scene still uses the default routing
            self.assertEqual(resolve_model("audit_cross_review", "x"), "DeepSeek-V3")
        reload_routing()

    def test_malformed_env_override_is_ignored(self):
        with patch.dict("os.environ", {
            "SCENE_MODELS": "garbage,no_colon_here,valid:ok,:empty_scene,empty_model:",
        }):
            reload_routing()
            self.assertEqual(resolve_model("valid", "fb"), "ok")
        reload_routing()

    def test_parse_env_override_unit(self):
        self.assertEqual(_parse_env_override("a:1,b:2"), {"a": "1", "b": "2"})
        self.assertEqual(_parse_env_override("  a : 1 ,  b : 2 "), {"a": "1", "b": "2"})
        self.assertEqual(_parse_env_override(""), {})
        self.assertEqual(_parse_env_override(None), {})
        self.assertEqual(_parse_env_override("nocolon"), {})

    def test_current_routing_includes_overrides(self):
        snapshot = current_routing()
        self.assertIn("extract_judgment_fields", snapshot)
        self.assertIn("compliance_review", snapshot)


class TracedCompleteUsesRoutingTests(unittest.TestCase):
    """End-to-end: traced_complete should call the LLM with the routed model,
    not the caller's `model=` argument."""

    def setUp(self):
        reload_routing()
        # Tracer is irrelevant here — NoopTracer is fine because we only
        # assert on the OpenAI client mock.
        import llm_audit
        from skills.tracer import NoopTracer
        self._orig_tracer = llm_audit._tracer
        llm_audit.set_tracer(NoopTracer())

    def tearDown(self):
        import llm_audit
        llm_audit._tracer = self._orig_tracer

    def test_routed_scene_overrides_caller_model(self):
        from llm_audit import traced_complete
        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content="ok"))]
        completion.usage = None
        client = MagicMock()
        client.chat.completions.create.return_value = completion

        traced_complete(
            client,
            scene="compliance_review",
            prompt_template_id="compliance.review.v1",
            model="qwen2.5-72b",  # caller's default, should be overridden
            messages=[{"role": "user", "content": "x"}],
            inject_few_shot=False,
        )
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["model"],
            "DeepSeek-V3",
        )

    def test_unrouted_scene_uses_caller_model(self):
        from llm_audit import traced_complete
        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content="ok"))]
        completion.usage = None
        client = MagicMock()
        client.chat.completions.create.return_value = completion

        traced_complete(
            client,
            scene="some_brand_new_scene",
            prompt_template_id="x.v1",
            model="caller-default",
            messages=[{"role": "user", "content": "x"}],
            inject_few_shot=False,
        )
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["model"],
            "caller-default",
        )


if __name__ == "__main__":
    unittest.main()
