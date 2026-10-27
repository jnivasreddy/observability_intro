"""Create a content-versioned golden dataset; no agent/model calls."""
import hashlib
from common import golden, smith_client


def setup(client, limit=None):
    cases = golden()[:limit]
    import json
    digest = hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest()[:10]
    name = "kiosk-golden-" + digest
    from langsmith.utils import LangSmithNotFoundError
    try:
        dataset = client.read_dataset(dataset_name=name)
        existing = list(client.list_examples(dataset_id=dataset.id))
        if len(existing) != len(cases):
            raise RuntimeError("Golden dataset exists but is incomplete. Inspect it before rerunning.")
        by_case = {e.inputs["case_id"]: e for e in existing}
        for case in cases:
            example = by_case.get(case["id"])
            if example is None or example.inputs != case["inputs"] or example.outputs != case["expected"]:
                raise RuntimeError("Hosted golden dataset was edited. Restore it or use a new dataset version.")
    except LangSmithNotFoundError:
        dataset = client.create_dataset(dataset_name=name,
                                        description="SYNTHETIC fixed kiosk scenarios; actual sandbox agent executes during experiments.")
        client.create_examples(inputs=[c["inputs"] for c in cases],
                               outputs=[c["expected"] for c in cases],
                               metadata=[{"synthetic": True, "case_id": c["id"]} for c in cases],
                               dataset_id=dataset.id)
    print("Golden dataset:", name)
    return name


if __name__ == "__main__":
    setup(smith_client())
