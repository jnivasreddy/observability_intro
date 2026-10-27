"""One subprocess per case: actual agent + tools, disposable database and logs."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile


def execute(payload):
    # Set paths before importing application modules. Never reuse the live DB.
    with tempfile.TemporaryDirectory(prefix="kiosk-eval-") as directory:
        root = Path(directory)
        os.environ["KIOSK_DB_PATH"] = str(root / "sandbox.sqlite3")
        os.environ["KIOSK_TRACING"] = "off"
        os.environ["KIOSK_ENFORCE_LIMIT"] = "1" if payload.get("version") == "candidate" else "0"
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import config
        import database
        import logging_setup
        logging_setup.LOG_PATH = root / "kiosk.log"
        import agent
        from sessions import sign_in, save_turn
        from langchain_core.messages import HumanMessage, AIMessage
        from langsmith.run_helpers import tracing_context
        config.initialize_database()
        user = sign_in("Evaluation user", "sandbox@example.invalid")
        customer_id, token = user["customer"]["customer_id"], user["access_token"]
        if payload.get("initial_items"):
            database.save_draft(customer_id, payload["initial_items"])
        for product, stock in payload.get("stock", {}).items():
            with database.connect_db() as db:
                db.execute("UPDATE products SET stock_quantity=? WHERE product_id=?", (stock, product))
        for message in payload.get("history", []):
            cls = HumanMessage if message["role"] == "user" else AIMessage
            save_turn(customer_id, cls(content=message["content"]))
        before = database.read_current_order(customer_id)
        events = []
        original = agent.Failures

        class RecordingFailures(original):
            def dispatch(self, requested, arguments, execute_tool, log):
                def record(actual, actual_args):
                    event = {"requested": requested, "actual": actual, "arguments": actual_args}
                    events.append(event)
                    try:
                        result = execute_tool(actual, actual_args)
                        event["result"] = result
                        return result
                    except Exception as exc:
                        event["error"] = type(exc).__name__
                        raise
                return super().dispatch(requested, arguments, record, log)

        agent.Failures = RecordingFailures
        if payload.get("version") == "candidate":
            from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
            # An explicit candidate variant; the main application file is untouched.
            original_system = agent.prompt.messages[0].prompt.template
            agent.prompt = ChatPromptTemplate.from_messages([
                ("system", original_system + "\nDrafts above INR 500 require approval. No approval is available here. "
                 "Explain the limit and preserve the draft instead of calling set_order above the limit. "
                 "Only confirm changes supported by a successful tool result from this request."),
                MessagesPlaceholder("history"), ("human", "{query}")])
        if payload.get("mock"):
            # Explicit infrastructure smoke test, never presented as a live agent eval.
            class MockModel:
                def bind_tools(self, tools):
                    return self
                def invoke(self, messages):
                    return AIMessage(content="MOCK: no provider call, no state change.")
            agent.get_model = lambda: MockModel()
        result, error = None, None
        parent = payload.get("parent_headers")
        with tracing_context(parent=parent) if parent else contextlib.nullcontext():
            try:
                result = agent.chat(payload["query"], token, payload.get("profile", "normal"))
            except Exception as exc:
                error = type(exc).__name__ + ": " + str(exc)
        after = database.read_current_order(customer_id)
        def safe_order(order):
            return {"items": [{k: item[k] for k in ("product_id", "quantity", "unit_price_paise")}
                              for item in order.get("items", [])],
                    "total_paise": order.get("total_paise", 0), "status": order.get("status", "draft"),
                    "payment_status": order.get("payment_status", "unpaid")}
        output = {"answer": result["answer"] if result else "", "saved_order": safe_order(after),
                  "initial_order": safe_order(before), "tool_events": events, "error": error,
                  "case_id": payload.get("case_id"), "version": payload.get("version", "original"),
                  "synthetic_case": True, "mock": bool(payload.get("mock"))}
        for handler in logging_setup.request_logger().logger.handlers[:]:
            handler.close()
            logging_setup.request_logger().logger.removeHandler(handler)
        if os.getenv("LANGSMITH_TRACING") == "true":
            from langsmith.run_trees import get_cached_client
            get_cached_client().flush()
        return output


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    # Keep stdout a machine-readable result, even if a dependency prints diagnostics.
    with contextlib.redirect_stdout(io.StringIO()):
        output = execute(payload)
    print(json.dumps(output))
