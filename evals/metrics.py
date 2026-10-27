"""Compute human review metrics and the judge's confusion matrix from CSV labels."""
import argparse
import csv
import json
from collections import Counter


def bit(value):
    if str(value).strip().lower() in {"1", "true"}:
        return 1
    if str(value).strip().lower() in {"0", "false"}:
        return 0
    return None


def calculate(rows):
    ids = [r["case_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Use one row per source case; duplicate IDs would distort the metrics.")
    reviewed = [r for r in rows if bit(r.get("human_task_fail")) is not None]
    pairs = [(bit(r.get("human_confirmation_fail")), bit(r.get("judge_confirmation_fail"))) for r in rows]
    pairs = [(h, j) for h, j in pairs if h is not None and j is not None]
    tp = sum(h == 1 and j == 1 for h, j in pairs)
    fp = sum(h == 0 and j == 1 for h, j in pairs)
    fn = sum(h == 1 and j == 0 for h, j in pairs)
    tn = sum(h == 0 and j == 0 for h, j in pairs)
    def ratio(n, d):
        return n / d if d else None
    return {"source_cases": len(rows), "human_scorable": len(reviewed),
            "human_label_coverage": ratio(len(reviewed), len(rows)),
            "human_failure_rate_in_reviewed_sample": ratio(sum(bit(r["human_task_fail"]) for r in reviewed), len(reviewed)),
            "failure_categories": dict(Counter(r.get("category", "unlabelled") for r in reviewed if bit(r["human_task_fail"]) == 1)),
            "judge_scored_pairs": len(pairs), "TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
            "specificity": ratio(tn, tn + fp), "agreement": ratio(tp + tn, len(pairs))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_csv")
    parser.add_argument("--judge-results")
    args = parser.parse_args()
    with open(args.review_csv, newline="") as stream:
        rows = list(csv.DictReader(stream))
    if args.judge_results:
        with open(args.judge_results, newline="") as stream:
            judged = {r["case_id"]: r for r in csv.DictReader(stream)}
        for row in rows:
            if row["case_id"] in judged:
                row["judge_confirmation_fail"] = judged[row["case_id"]]["judge_confirmation_fail"]
    print(json.dumps(calculate(rows), indent=2))
    print("Rates describe this reviewed teaching sample, not a production prevalence estimate. null = N/A.")


if __name__ == "__main__":
    main()
