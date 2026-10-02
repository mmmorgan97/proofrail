import json
import sys
import tempfile
import unittest
from pathlib import Path

import proofrail


class ProofrailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.plan = self.root / "task.json"
        proofrail.initialize(self.plan, "Run the unit tests and prove they passed.")
        self.evidence = self.root / "test-output.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepts_evidence_containing_declared_success_signal(self):
        self.evidence.write_text("Ran 8 tests\nOK\n", encoding="utf-8")
        proofrail.add_check(self.plan, "Tests pass", str(self.evidence), "OK")
        result = proofrail.verify(self.plan)
        self.assertTrue(result["passed"])
        self.assertEqual(result["checks"][0]["status"], "PASS")

    def test_rejects_missing_evidence_file(self):
        proofrail.add_check(self.plan, "Tests pass", str(self.evidence), "OK")
        result = proofrail.verify(self.plan)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["status"], "MISSING")

    def test_rejects_evidence_without_required_success_signal(self):
        self.evidence.write_text("Ran 8 tests\nFAILED (failures=1)\n", encoding="utf-8")
        proofrail.add_check(self.plan, "Tests pass", str(self.evidence), "OK")
        result = proofrail.verify(self.plan)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["status"], "SIGNAL_MISSING")

    def test_requires_nonempty_acceptance_checks(self):
        result = proofrail.verify(self.plan)
        self.assertFalse(result["passed"])
        self.assertEqual(result["reason"], "NO_CHECKS")

    def test_rejects_ambiguous_or_empty_check_definition(self):
        with self.assertRaises(ValueError):
            proofrail.add_check(self.plan, "", str(self.evidence), "OK")
        with self.assertRaises(ValueError):
            proofrail.add_check(self.plan, "Tests pass", str(self.evidence), "")

    def test_duplicate_check_names_are_rejected(self):
        proofrail.add_check(self.plan, "Tests pass", str(self.evidence), "OK")
        with self.assertRaises(ValueError):
            proofrail.add_check(self.plan, "Tests pass", str(self.evidence), "PASS")

    def test_refuses_to_claim_pass_after_evidence_changes(self):
        self.evidence.write_text("Ran 8 tests\nOK\n", encoding="utf-8")
        proofrail.add_check(self.plan, "Tests pass", str(self.evidence), "Ran 8 tests\nOK\n")
        self.evidence.write_text("Ran 8 tests\nNOT OK\n", encoding="utf-8")
        result = proofrail.verify(self.plan)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["status"], "SIGNAL_MISSING")

    def test_corrupt_plan_json(self):
        self.plan.write_text("{broken", encoding="utf-8")
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            proofrail.verify(self.plan)

    def test_command_check_cannot_pass_before_it_has_been_run(self):
        proofrail.add_command_check(self.plan, "Unit suite", [sys.executable, "-c", "print('OK')"])
        result = proofrail.verify(self.plan)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["status"], "NOT_RUN")

    def test_runs_command_without_shell_and_verifies_real_exit_code(self):
        proofrail.add_command_check(self.plan, "Unit suite", [sys.executable, "-c", "print('OK')"])
        runs = proofrail.run_commands(self.plan, proofrail.plan_digest(self.plan))
        result = proofrail.verify(self.plan)
        self.assertEqual(runs[0]["returncode"], 0)
        self.assertIn("OK", runs[0]["stdout"])
        self.assertTrue(result["passed"])
        self.assertTrue(result["checks"][0]["sha256"])

    def test_nonzero_command_exit_code_blocks_completion_even_if_output_says_ok(self):
        proofrail.add_command_check(self.plan, "Unit suite", [sys.executable, "-c", "print('OK'); raise SystemExit(3)"])
        proofrail.run_commands(self.plan, proofrail.plan_digest(self.plan))
        result = proofrail.verify(self.plan)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["status"], "COMMAND_FAILED")

    def test_command_timeout_is_recorded_and_blocks_completion(self):
        proofrail.add_command_check(self.plan, "Slow check", [sys.executable, "-c", "import time; time.sleep(1)"], timeout_seconds=0.1)
        runs = proofrail.run_commands(self.plan, proofrail.plan_digest(self.plan))
        result = proofrail.verify(self.plan)
        self.assertTrue(runs[0]["timed_out"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["status"], "TIMEOUT")

    def test_rejects_shell_string_instead_of_argument_list(self):
        with self.assertRaises(ValueError):
            proofrail.add_command_check(self.plan, "Unsafe", "python -c print(1)")

    def test_tampered_captured_output_is_detected(self):
        proofrail.add_command_check(self.plan, "Unit suite", [sys.executable, "-c", "print('OK')"])
        proofrail.run_commands(self.plan, proofrail.plan_digest(self.plan))
        record = self.plan.parent / ".proofrail" / "command-1.json"
        data = json.loads(record.read_text(encoding="utf-8"))
        data["stdout"] = "FORGED OK"
        record.write_text(json.dumps(data), encoding="utf-8")
        result = proofrail.verify(self.plan)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["status"], "OUTPUT_CHANGED")

    def test_rejects_plan_change_after_run(self):
        proofrail.add_command_check(self.plan, "Unit suite", [sys.executable, "-c", "print('OK')"])
        approved = proofrail.plan_digest(self.plan)
        proofrail.run_commands(self.plan, approved)
        obj = json.loads(self.plan.read_text(encoding="utf-8"))
        obj["goal"] = "Changed after approval"
        self.plan.write_text(json.dumps(obj), encoding="utf-8")
        result = proofrail.verify(self.plan)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["status"], "PLAN_CHANGED")

    def test_refuses_to_run_when_approved_plan_hash_is_stale(self):
        proofrail.add_command_check(self.plan, "Unit suite", [sys.executable, "-c", "print('OK')"])
        approved = proofrail.plan_digest(self.plan)
        proofrail.add_check(self.plan, "Extra requirement", str(self.evidence), "OK")
        with self.assertRaises(ValueError):
            proofrail.run_commands(self.plan, approved)
        self.assertEqual(proofrail.verify(self.plan)["checks"][0]["status"], "NOT_RUN")

    def test_corrupt_command_record_fails_closed(self):
        proofrail.add_command_check(self.plan, "Unit suite", [sys.executable, "-c", "print('OK')"])
        proofrail.run_commands(self.plan, proofrail.plan_digest(self.plan))
        record = self.plan.parent / ".proofrail" / "command-1.json"
        record.write_text("[]", encoding="utf-8")
        result = proofrail.verify(self.plan)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["status"], "INVALID_RECORD")


if __name__ == "__main__":
    unittest.main()
