import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from metrics import calculate
from online_code import perform_eval
from evaluators import exact_checks, judge_evidence
from upload_traces import prepare


class LabTests(unittest.TestCase):
    def test_fixture_parentage_and_time_intervals(self):
        files = sorted((HERE / "student_traces").glob("T*.json"))
        self.assertEqual(len(files), 12)
        for file in files:
            runs = json.loads(file.read_text())["runs"]
            root = runs[0]
            self.assertIsNone(root["parent_run_id"])
            for child in runs[1:]:
                self.assertEqual(child["trace_id"], root["id"])
                self.assertEqual(child["parent_run_id"], root["id"])
                self.assertLessEqual(child["end_time"], root["end_time"])
            shifted = prepare(json.loads(file.read_text()), datetime.now(timezone.utc))
            for child in shifted[1:]:
                self.assertTrue(child["dotted_order"].startswith(shifted[0]["dotted_order"] + "."))
            self.assertNotEqual(str(shifted[0]["id"]), root["id"])

    def test_code_rule_and_missing_evidence(self):
        self.assertEqual(perform_eval({"outputs": {}}), {"limit_evidence_available": 0})
        self.assertEqual(perform_eval({"outputs": {"saved_order": {"total_paise": 120000}}})["draft_limit_pass"], 0)
        self.assertEqual(perform_eval({"outputs": {"saved_order": {"total_paise": 50000}}})["draft_limit_pass"], 1)

    def test_confusion_matrix_and_no_denominator(self):
        labels = [(1, 1), (1, 0), (0, 1), (0, 0)]
        rows = [{"case_id": str(i), "human_task_fail": h, "human_confirmation_fail": h,
                 "judge_confirmation_fail": j} for i, (h, j) in enumerate(labels)]
        result = calculate(rows)
        self.assertEqual([result[k] for k in ("TP", "FP", "FN", "TN")], [1, 1, 1, 1])
        self.assertEqual(result["precision"], .5)
        self.assertIsNone(calculate([])["recall"])
        with self.assertRaises(ValueError):
            calculate(rows + [rows[0]])

    def test_judge_does_not_receive_golden_labels(self):
        result = judge_evidence({"query": "hi", "expected": "secret"}, {
            "answer": "hello", "saved_order": {}, "expected": "hidden", "human_label": 1})
        self.assertEqual(set(result), {"query", "answer", "saved_order"})

    def test_failed_execution_cannot_pass_expected_state(self):
        scores = exact_checks({}, {"error": "TimeoutError", "saved_order": {"items": []}},
                              {"items": {}, "required_tools": [], "forbidden_tools": []})
        self.assertEqual(scores[0]["score"], 0)

    def test_disposable_worker_preserves_seeded_state_and_live_files(self):
        live_paths = [HERE.parent / "kiosk.sqlite3", HERE.parent / "kiosk.log"]
        before = {p: p.read_bytes() if p.exists() else None for p in live_paths}
        env = dict(os.environ, LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
        payload = {"case_id": "test", "query": "Hi", "initial_items": [
            {"product_id": "veg_sandwich", "quantity": 1}], "history": [], "mock": True}
        process = subprocess.run([sys.executable, str(HERE / "sandbox_worker.py")],
                                 input=json.dumps(payload), text=True, capture_output=True, env=env, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["saved_order"]["items"][0]["product_id"], "veg_sandwich")
        self.assertEqual(result["saved_order"]["total_paise"], 10000)
        self.assertTrue(result["mock"])
        for path in live_paths:
            self.assertEqual(path.read_bytes() if path.exists() else None, before[path])


if __name__ == "__main__":
    unittest.main()
