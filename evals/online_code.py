"""Paste this entire file into LangSmith's Python Code Evaluator editor."""


def perform_eval(run):
    outputs = run.get("outputs") or {}
    order = outputs.get("saved_order")
    if not isinstance(order, dict) or not isinstance(order.get("total_paise"), (int, float)):
        return {"limit_evidence_available": 0}
    # Missing evidence does not count as policy pass. No network calls required.
    return {"limit_evidence_available": 1,
            "draft_limit_pass": int(order["total_paise"] <= 50000)}
