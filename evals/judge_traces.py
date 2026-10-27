"""Evaluate the judge against frozen synthetic answers, not an agent version."""
import csv
import os
from common import HERE, read_json
from evaluators import judge_confirmation


def main():
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = "kiosk-judge-validation"
    from langsmith import trace
    rows = []
    for path in sorted((HERE / "student_traces").glob("T*.json")):
        fixture = read_json(path)
        root = fixture["runs"][0]
        outputs = root["outputs"] or {"error": root["error"]}
        with trace("validate_confirmation_judge", inputs=root["inputs"],
                   metadata={"synthetic": True, "case_id": fixture["case_id"]}) as active:
            score = judge_confirmation(root["inputs"], outputs)
            active.outputs = score
        rows.append({"case_id": fixture["case_id"],
                     "judge_confirmation_fail": score["score"] if score["key"] == "unsupported_confirmation" else "",
                     "reason": score.get("comment", "")})
    folder = HERE / "output"
    folder.mkdir(exist_ok=True)
    with (folder / "judge_labels.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    from langsmith.run_trees import get_cached_client
    get_cached_client().flush()
    print("Wrote evals/output/judge_labels.csv; judge executions are in kiosk-judge-validation.")


if __name__ == "__main__":
    main()
