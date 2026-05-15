import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


class SkillRegistryTests(unittest.TestCase):
    def test_backend_skill_registry_exposes_chat_intent_contract(self):
        from skills.registry import (
            ACTIONABLE_STAGES,
            INTENT_DESCRIPTIONS_WORKFLOW,
            INTENT_RESPONSES,
            VALID_INTENTS,
            WORKFLOW_HINTS,
        )

        for intent in [
            "download_training_excel",
            "download_ledger_excel",
            "download_compliance_excel",
            "waiting_files",
            "waiting_ledger_files",
            "waiting_auth_file",
            "waiting_compliance_file",
            "query_company",
            "debt_recovery_assessment",
            "other",
        ]:
            self.assertIn(intent, VALID_INTENTS)

        self.assertEqual(INTENT_RESPONSES["waiting_files"][1], "waiting_files")
        self.assertEqual(INTENT_RESPONSES["waiting_ledger_files"][1], "waiting_ledger_files")
        self.assertEqual(INTENT_RESPONSES["waiting_auth_file"][1], "waiting_auth_file")
        self.assertEqual(INTENT_RESPONSES["waiting_compliance_file"][1], "waiting_compliance_file")

        for stage in [
            "waiting_files",
            "waiting_ledger_files",
            "waiting_auth_file",
            "waiting_compliance_file",
            "waiting_ledger_merge_files",
            "waiting_audit_file",
        ]:
            self.assertIn(stage, ACTIONABLE_STAGES)
            self.assertIn(stage, WORKFLOW_HINTS)

        self.assertIn("download_training_excel", INTENT_DESCRIPTIONS_WORKFLOW)
        self.assertIn("waiting_compliance_file", INTENT_DESCRIPTIONS_WORKFLOW)

    def test_qcc_intent_descriptions_exported(self):
        from skills.registry import QCC_INTENT_DESCRIPTIONS
        self.assertIn("query_company", QCC_INTENT_DESCRIPTIONS)
        self.assertIn("debt_recovery_assessment", QCC_INTENT_DESCRIPTIONS)
        self.assertIn("claim_amount", QCC_INTENT_DESCRIPTIONS)


if __name__ == "__main__":
    unittest.main()
