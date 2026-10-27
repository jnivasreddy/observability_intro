"""N-minus-one model decision replay. No tools execute and no database is opened."""
import argparse
import os
from common import HERE, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=[f"T{i:02}" for i in range(1, 13)])
    parser.add_argument("--run-id", help="Model child ID; otherwise replay the last model call")
    parser.add_argument("--candidate", action="store_true")
    args = parser.parse_args()
    fixture = read_json(HERE / "student_traces" / (args.case + ".json"))
    calls = [r for r in fixture["runs"] if r["run_type"] == "llm"]
    selected = next(r for r in calls if r["id"] == args.run_id) if args.run_id else calls[-1]
    messages = selected["inputs"]["messages"]
    if args.candidate:
        messages[0]["content"] += " Only confirm changes supported by a successful current-request tool result. Explain contradictions instead of repeating earlier claims."
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = "kiosk-decision-replay"
    from agent import get_model
    from tools import tools
    from langsmith import trace
    with trace("replay_decision", inputs={"messages": messages}, metadata={
            "case_id": args.case, "synthetic": True, "source_run_id": selected["id"],
            "candidate": args.candidate}) as root:
        response = get_model().bind_tools(tools).invoke(messages)
        root.outputs = {"answer": response.content, "tool_calls": response.tool_calls}
        print(root.outputs)
    from langsmith.run_trees import get_cached_client
    get_cached_client().flush()
    print("No tools executed. View kiosk-decision-replay in LangSmith.")


if __name__ == "__main__":
    main()
