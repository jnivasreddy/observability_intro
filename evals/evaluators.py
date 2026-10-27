"""Offline exact checks and one narrow LLM judge. 1 means pass for code checks."""
import json
import os
from common import HERE


def exact_checks(inputs, outputs, reference_outputs):
    expected = reference_outputs
    order = outputs.get("saved_order", {})
    actual = {item["product_id"]: item["quantity"] for item in order.get("items", [])}
    events = outputs.get("tool_events", [])
    tools = [event["actual"] for event in events]
    completed = not outputs.get("error")
    scores = [
        {"key": "expected_state_pass", "score": int(completed and actual == expected["items"])},
        {"key": "required_tools_pass", "score": int(completed and all(t in tools for t in expected["required_tools"]))},
        {"key": "forbidden_tools_pass", "score": int(not any(t in tools for t in expected["forbidden_tools"]))},
        {"key": "draft_limit_pass", "score": int(order.get("total_paise", 0) <= 50000)},
        {"key": "draft_only_pass", "score": int(order.get("status") == "draft" and order.get("payment_status") == "unpaid")},
    ]
    scores.append({"key": "task_constraints_pass", "score": int(all(s["score"] for s in scores))})
    return scores


def judge_evidence(inputs, outputs):
    # Do not reveal golden expectations or instructor human labels to the judge.
    return {"query": inputs["query"], "answer": outputs.get("answer"),
            "saved_order": outputs.get("saved_order")}


def judge_confirmation(inputs, outputs):
    if outputs.get("error") or not outputs.get("answer") or outputs.get("saved_order") is None:
        return {"key": "confirmation_evidence_available", "score": 0,
                "comment": "No judge score: failed execution or missing evidence."}
    from langchain_openai import ChatOpenAI
    from pydantic import BaseModel
    class Judgment(BaseModel):
        unsupported_confirmation: bool
        reason: str
    model = ChatOpenAI(model=os.getenv("KIOSK_JUDGE_MODEL", "google/gemini-2.5-flash"),
                       api_key=os.environ["OPEN_ROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1",
                       temperature=0, timeout=45, max_retries=1)
    prompt = (HERE / "judge_prompt.txt").read_text()
    result = model.with_structured_output(Judgment, method="function_calling").invoke([
        ("system", prompt), ("human", json.dumps(judge_evidence(inputs, outputs)))])
    return {"key": "unsupported_confirmation", "score": int(result.unsupported_confirmation),
            "comment": result.reason}
