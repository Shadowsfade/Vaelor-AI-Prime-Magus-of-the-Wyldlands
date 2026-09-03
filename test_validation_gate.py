import unittest

from core.validation_gate import evaluate_validation


class ValidationGateTests(unittest.TestCase):
    def test_all_required_evidence_can_reach_full_confidence(self):
        result = evaluate_validation([
            {"name": "build", "status": "passed", "evidence": "exit 0", "weight": 3},
            {"name": "smoke", "status": "passed", "evidence": "launched", "weight": 2},
        ])
        self.assertEqual(result["confidence_percent"], 100.0)
        self.assertTrue(result["ready_to_promote"])

    def test_unknown_required_check_blocks_promotion_and_reduces_confidence(self):
        result = evaluate_validation([
            {"name": "build", "status": "passed", "evidence": "exit 0", "weight": 9},
            {"name": "visual", "status": "unknown", "weight": 1},
        ], threshold=90)
        self.assertEqual(result["confidence_percent"], 90.0)
        self.assertFalse(result["ready_to_promote"])
        self.assertEqual(result["required_unknowns"], ["visual"])

    def test_required_failure_blocks_even_above_threshold(self):
        result = evaluate_validation([
            {"name": "tests", "status": "passed", "weight": 99},
            {"name": "security", "status": "failed", "weight": 1},
        ], threshold=95)
        self.assertEqual(result["confidence_percent"], 99.0)
        self.assertFalse(result["ready_to_promote"])
        self.assertEqual(result["blocking_failures"], ["security"])

    def test_malformed_contract_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_validation([{"name": "build", "status": "probably"}])


if __name__ == "__main__":
    unittest.main()
