import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


class AuthRequestDrafterTests(unittest.TestCase):
    def test_attachment1_title_uses_document_heading(self):
        from utils.auth_request_drafter import _extract_attachment1_title

        text = "\n".join(
            [
                "— 1 —",
                "关于国航T3 北区机务设施建设项目",
                "需求调整及明确相关工作的通知",
                "中国国际航空股份有限公司工程建设管理部：",
                "《关于办理调整T3北区项目Ameco需求的请示》我部已收悉。",
            ]
        )

        self.assertEqual(
            _extract_attachment1_title(text),
            "关于国航T3北区机务设施建设项目需求调整及明确相关工作的通知",
        )

    def test_build_request_text_falls_back_from_polluted_extraction(self):
        from utils.auth_request_drafter import build_auth_request_text

        polluted = "关于办理调整T3北区项目Ameco需求的请示" * 10
        content = build_auth_request_text(
            {
                "attachment1": {
                    "title": polluted,
                    "project_name": polluted,
                    "document_no": "国航股份有限公司中航集团规划发〔2026〕1号",
                    "undertaking_unit": polluted,
                },
                "attachment2": {
                    "principal_unit": "中国航空集团建设开发有限公司",
                    "principal_short": "建开公司",
                    "trustee_work_unit": "中国航空集团建设开发有限公司",
                    "trustee_position": "项目经理",
                    "trustee_name": "白利业白利业",
                    "permission_detail": "合同签署权限。合同签署权限。",
                    "permission_type": "合同签署权限",
                    "authorization_scope": "为开展国航T3北区机务设施建设项目的相关工作，其权限为:合同签署权限。",
                },
            },
            {"auth_mode": "direct", "copies": "3", "seal": "公章", "handler": "张三"},
        )

        self.assertIn("依据《关于国航T3北区机务设施建设项目需求调整及明确相关工作的通知》", content)
        self.assertIn("（中航集团规划发〔2026〕1号，详见附件1）", content)
        self.assertIn("白利业同志", content)
        self.assertNotIn("白利业白利业同志", content)


if __name__ == "__main__":
    unittest.main()
