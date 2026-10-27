"""Publish fictional runs to a separate classroom project. Requires --send."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import time
from uuid import uuid4
from common import HERE, read_json, smith_client

CLASSROOM_PROJECT = "kiosk-synthetic-classroom"


def prepare(fixture, start):
    runs = fixture["runs"]
    original_start = datetime.fromisoformat(runs[0]["start_time"])
    ids = {run["id"]: uuid4() for run in runs}
    root_id = ids[runs[0]["id"]]
    root_order = start.strftime("%Y%m%dT%H%M%S%fZ") + str(root_id)
    result = []
    for run in runs:
        item = json.loads(json.dumps(run))
        item["id"] = ids[run["id"]]
        item["trace_id"] = root_id
        item["parent_run_id"] = ids.get(run["parent_run_id"])
        for key in ("start_time", "end_time"):
            item[key] = start + (datetime.fromisoformat(run[key]) - original_start)
        suffix = item["start_time"].strftime("%Y%m%dT%H%M%S%fZ") + str(item["id"])
        item["dotted_order"] = root_order if run["parent_run_id"] is None else root_order + "." + suffix
        result.append(item)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    files = sorted((HERE / "student_traces").glob("T*.json"))
    if not args.send:
        print(f"Dry run: {len(files)} SYNTHETIC traces would go to {CLASSROOM_PROJECT}.")
        print("Run again with --send to upload. No models or real kiosk tools are called.")
        return
    client = smith_client()
    root_ids = []
    try:
        for index, path in enumerate(files):
            runs = prepare(read_json(path), datetime.now(timezone.utc) - timedelta(minutes=len(files) - index))
            for run in runs:
                client.create_run(project_name=CLASSROOM_PROJECT, **run)
            root_ids.append(str(runs[0]["id"]))
        client.flush()
        output = HERE / "output"
        output.mkdir(exist_ok=True)
        (output / "uploaded_ids.json").write_text(json.dumps(root_ids, indent=2))
        # A read check distinguishes accepted uploads from merely queued records.
        from langsmith.utils import LangSmithNotFoundError
        for attempt in range(8):
            try:
                client.read_run(root_ids[-1])
                break
            except LangSmithNotFoundError:
                if attempt == 7:
                    raise RuntimeError("Upload sent but not yet readable. Check the project before uploading again.")
                time.sleep(2)  # Ingestion/read indexes are eventually consistent.
        print(f"Verified last upload. Open LangSmith → Tracing → {CLASSROOM_PROJECT}.")
        print("Fresh IDs are created on every upload. Filter one upload window to avoid double counting.")
    finally:
        client.flush()


if __name__ == "__main__":
    main()
