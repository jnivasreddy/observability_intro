"""Execute fresh agent runs against the golden dataset; publish LangSmith experiments."""
import argparse
import json
import os
import subprocess
import sys
from common import HERE, smith_client
from setup_dataset import setup
from evaluators import exact_checks, judge_confirmation


def run_case(inputs, version="original", mock=False):
    from langsmith.run_helpers import get_current_run_tree
    active = get_current_run_tree()
    payload = {**inputs, "version": version, "mock": mock}
    if active and not mock:
        payload["parent_headers"] = active.to_headers()
    env = os.environ.copy()
    if active:
        env["LANGSMITH_PROJECT"] = active.session_name
    process = subprocess.run([sys.executable, str(HERE / "sandbox_worker.py")],
                             input=json.dumps(payload), capture_output=True, text=True,
                             env=env, timeout=240)
    if process.returncode:
        raise RuntimeError("Sandbox process failed: " + process.stderr[-1500:])
    return json.loads(process.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=["code", "judge", "both"], default="code")
    parser.add_argument("--version", choices=["original", "candidate"], default="original")
    parser.add_argument("--limit", type=int, choices=range(1, 9))
    parser.add_argument("--repetitions", type=int, choices=range(1, 6), default=1)
    args = parser.parse_args()
    os.environ["LANGSMITH_TRACING"] = "true"
    client = smith_client()
    dataset = setup(client, args.limit)
    from langsmith import evaluate
    def target(inputs):
        return run_case(inputs, args.version)
    evaluators = []
    if args.method in {"code", "both"}:
        evaluators.append(exact_checks)
    if args.method in {"judge", "both"}:
        evaluators.append(judge_confirmation)
    try:
        results = evaluate(target, data=dataset, evaluators=evaluators, client=client,
                 experiment_prefix=f"kiosk-{args.version}-{args.method}",
                 metadata={"agent_version": args.version, "synthetic_cases": True,
                           "target": "fresh agent + real SQLite tools in disposable subprocess"},
                 max_concurrency=1, num_repetitions=args.repetitions)
        rows = list(results)
        failures = sum(bool((row["run"].outputs or {}).get("error")) or bool(row["run"].error) for row in rows)
        print(f"Completed {len(rows)} cases; {failures} agent execution errors. Inspect task checks and judge coverage separately.")
    finally:
        client.flush()


if __name__ == "__main__":
    main()
