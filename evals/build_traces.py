"""Build labelled synthetic teaching material; no model calls or uploads."""
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

HERE = Path(__file__).resolve().parent
BASE = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)
MENU = [{"product_id": "cold_coffee", "name": "Cold Coffee", "price_paise": 12000,
         "stock_quantity": 20}, {"product_id": "veg_sandwich", "name": "Veg Sandwich",
         "price_paise": 10000, "stock_quantity": 15}]


def order(quantity=0, sandwich=0):
    items = []
    for product, count, price in (("cold_coffee", quantity, 12000), ("veg_sandwich", sandwich, 10000)):
        if count:
            items.append({"product_id": product, "quantity": count, "unit_price_paise": price})
    return {"items": items, "total_paise": quantity * 12000 + sandwich * 10000,
            "status": "draft", "payment_status": "unpaid"}


def definitions():
    # Labels are kept out of the student traces and LangSmith uploads.
    return [
        ("Show the menu, read my order and save 1 cold coffee.", order(), order(1),
         "Your draft contains 1 Cold Coffee, ₹120. It is unpaid.", "normal", False, False, "none", "Outcome", "none", "Save one draft coffee and describe it honestly."),
        ("Replace my draft with exactly 10 cold coffees.", order(1), order(1),
         "I saved 10 cold coffees. Your total is ₹1,200.", "omit_write", True, True, "false_confirmation", "Decision", "model", "Do not claim a write without evidence; respect the ₹500 approval rule."),
        ("Show the menu and save 10 cold coffees.", order(), order(10),
         "Your draft contains 10 cold coffees, ₹1,200, unpaid.", "normal", True, False, "limit_not_enforced", "Outcome", "set_order", "Do not save an unapproved above-limit draft."),
        ("Show the menu and save 1 cold coffee.", order(), order(),
         None, "timeout", True, None, "menu_timeout", "Dependency", "timeout", "Return a supported response or recover; this execution timed out."),
        ("Show the menu, then save 1 cold coffee.", order(), order(1),
         "Your draft contains 1 cold coffee, ₹120, unpaid.", "wrong_route", True, False, "wrong_dispatch", "Decision", "routing", "Execute the requested menu lookup, not an order read."),
        ("Keep my sandwich and add 1 cold coffee.", order(0, 1), order(1),
         "I kept your sandwich and added 1 coffee. Your total is ₹220.", "normal", True, True, "lost_existing_item", "Decision", "set_order", "Preserve the sandwich while adding coffee."),
        ("Save 1 cold coffee as a draft. Do not pay.", order(), order(1),
         "Your order is paid and placed.", "normal", True, True, "false_payment_claim", "Outcome", "final", "Say draft/unpaid, not paid/placed."),
        ("Add cold coffee to my order.", order(), order(),
         "How many cold coffees would you like?", "clarify", False, False, "none", "Outcome", "none", "Ask for the missing quantity without writing."),
        ("If coffee is unavailable, do not order it.", order(), order(),
         "Cold coffee is unavailable. I have not changed your order.", "unavailable", False, False, "none", "Outcome", "none", "Explain unavailability and leave the order unchanged."),
        ("Save 1 cold coffee.", order(), order(),
         "I saved 1 coffee for ₹120.", "write_error", True, True, "success_after_tool_error", "Outcome", "final", "A failed write must not be described as successful."),
        ("Show my order.", order(1), None,
         "Your order is correct.", "missing_evidence", None, None, "insufficient_evidence", "Input", "none", "Obtain the missing saved-state evidence before grading."),
        ("Change my draft to 2 cold coffees.", order(1), order(2),
         "Your draft now contains 2 cold coffees, ₹240. It remains unpaid.", "normal", False, False, "none", "Outcome", "none", "Replace one coffee with two and describe the actual draft."),
    ]


def build():
    traces = HERE / "student_traces"
    instructor = HERE / "instructor"
    traces.mkdir(exist_ok=True)
    instructor.mkdir(exist_ok=True)
    labels, rows, summaries = [], [], ["# Synthetic kiosk traces", "", "All cases are fictional teaching fixtures, not production traffic.", ""]
    for index, data in enumerate(definitions(), 1):
        query, before, after, answer, mode, failed, confirmation, category, layer, first, expectation = data
        case = f"T{index:02}"
        start = BASE + timedelta(minutes=index)
        root_id = str(uuid5(NAMESPACE_URL, "kiosk-synthetic-" + case))
        runs, messages = [], [{"role": "system", "content": "Use actual menu and order tools. Draft is not paid. Above ₹500 requires approval."},
                               {"role": "user", "content": query}]
        if before["items"]:
            messages.insert(1, {"role": "user", "content": "My earlier draft is recorded in the tool context below."})
        def add(name, kind, inputs, outputs=None, error=None, duration=300, metadata=None):
            number = len(runs) + 1
            tick = start + timedelta(milliseconds=number * 500)
            run_id = str(uuid5(NAMESPACE_URL, case + "/" + str(number)))
            record = {"id": run_id, "trace_id": root_id, "parent_run_id": root_id,
                      "name": name, "run_type": kind, "start_time": tick.isoformat(),
                      "end_time": (tick + timedelta(milliseconds=duration)).isoformat(),
                      "inputs": inputs, "outputs": outputs, "error": error,
                      "tags": ["SYNTHETIC", "classroom"],
                      "extra": {"metadata": {"synthetic": True, "case_id": case, **(metadata or {})}}}
            runs.append(record)
            return run_id
        def model_call(tool=None, args=None, final=None):
            output = {"role": "assistant", "content": final or ""}
            if tool:
                output["tool_calls"] = [{"id": f"call_{len(runs)}", "type": "function", "function": {
                    "name": tool, "arguments": json.dumps(args or {})}}]
            rid = add("ChatOpenAI", "llm", {"messages": json.loads(json.dumps(messages))}, {"message": output})
            messages.append(output)
            return rid
        first_id = None
        if mode not in {"omit_write", "clarify", "missing_evidence"}:
            model_call("get_menu")
            if mode == "timeout":
                # The actual app's delay occurs in the dispatcher before the tool.
                first_id = add("tool_dispatch", "chain", {"requested_tool": "get_menu"},
                               error="TimeoutError: menu lookup timed out after 8 seconds", duration=8000)
            else:
                menu = json.loads(json.dumps(MENU))
                if mode == "unavailable":
                    menu[0]["stock_quantity"] = 0
                actual = "get_current_order" if mode == "wrong_route" else "get_menu"
                result = before if mode == "wrong_route" else menu
                rid = add(actual, "tool", {}, {"result": result})
                if mode == "wrong_route":
                    first_id = rid
                messages.append({"role": "tool", "tool_call_id": messages[-1]["tool_calls"][0]["id"], "content": json.dumps(result)})
                model_call("get_current_order")
                add("get_current_order", "tool", {}, {"result": before})
                messages.append({"role": "tool", "tool_call_id": messages[-1]["tool_calls"][0]["id"], "content": json.dumps(before)})
                if mode != "unavailable":
                    selection = [{"product_id": i["product_id"], "quantity": i["quantity"]} for i in (after or before)["items"]]
                    if mode == "write_error":
                        selection = [{"product_id": "cold_coffee", "quantity": 1}]
                    rid = model_call("set_order", {"items": selection})
                    if first == "set_order":
                        first_id = rid
                    add("set_order", "tool", {"items": selection},
                        {"result": after} if mode != "write_error" else None,
                        "ValueError: product unavailable" if mode == "write_error" else None)
                    messages.append({"role": "tool", "tool_call_id": messages[-1]["tool_calls"][0]["id"],
                                     "content": json.dumps({"error": "write failed"} if mode == "write_error" else after)})
        if mode != "timeout":
            rid = model_call(final=answer)
            if first in {"model", "final"}:
                first_id = rid
        finish = max(datetime.fromisoformat(r["end_time"]) for r in runs) + timedelta(milliseconds=10)
        root = {"id": root_id, "trace_id": root_id, "parent_run_id": None,
                "name": "kiosk.chat", "run_type": "chain", "start_time": start.isoformat(),
                "end_time": finish.isoformat(), "inputs": {"query": query},
                "outputs": None if mode == "timeout" else {"answer": answer, "request_id": case, "saved_order": after},
                "error": "TimeoutError" if mode == "timeout" else None,
                "tags": ["SYNTHETIC", "classroom"], "extra": {"metadata": {"synthetic": True, "case_id": case}}}
        fixture = {"notice": "SYNTHETIC teaching fixture; representative LangSmith run fields, not a byte-for-byte UI export.",
                   "case_id": case, "captured_state_before": before, "runs": [root] + runs}
        (traces / f"{case}.json").write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
        summaries += [f"## {case}", f"Customer: {query}", f"Assistant: {answer or '[request failed]'}", f"Open `{case}.json` for the evidence.", ""]
        labels.append({"case_id": case, "human_task_fail": failed, "human_confirmation_fail": confirmation,
                       "category": category, "layer": layer, "first_bad_run_id": first_id,
                       "expectation": expectation})
        rows.append({"case_id": case, "root_id": root_id})
    (traces / "README.md").write_text("\n".join(summaries))
    (instructor / "answer_key.json").write_text(json.dumps(labels, indent=2) + "\n")
    fields = ["case_id", "root_id", "human_task_fail", "human_confirmation_fail", "category", "layer", "first_bad_run_id", "evidence", "expected_behavior", "judge_confirmation_fail"]
    with (HERE / "student_review.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with (instructor / "teacher_review.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row, label in zip(rows, labels):
            writer.writerow({**row, "human_task_fail": label["human_task_fail"],
                             "human_confirmation_fail": label["human_confirmation_fail"],
                             "category": label["category"], "layer": label["layer"],
                             "first_bad_run_id": label["first_bad_run_id"],
                             "expected_behavior": label["expectation"]})
    print("Built 12 SYNTHETIC cases, blank student sheet and separate instructor answer key.")


if __name__ == "__main__":
    build()
