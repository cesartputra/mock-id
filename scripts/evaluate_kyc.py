"""Offline labeled-result evaluation. No upload, retraining or fabricated approval."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.score_policy import ScorePolicy, FEATURE_POLICY, calibration_contract


def evaluate(records, policy=None):
    policy = policy or ScorePolicy()
    labels = {"genuine": [], "attack": []}
    for record in records:
        label = record.get("label")
        if label not in labels:
            raise ValueError("Label harus genuine atau attack.")
        result, mandatory = record["result"], record["mandatory"]
        labels[label].append(policy.route(result, mandatory))
    if any(not group for group in labels.values()):
        raise ValueError(
            "Evaluasi membutuhkan capture asli dan serangan berlabel; satu kelas tidak cukup."
        )

    def rate(group, decisions):
        return sum(r["decision"] in decisions for r in group) / len(group)

    return {
        "schema": 1,
        "policy": policy.calibrator.version,
        "feature_policy": FEATURE_POLICY,
        "model_sha256": calibration_contract(),
        "calibrated": policy.calibrator.calibrated,
        "sample_counts": {label: len(group) for label, group in labels.items()},
        "attack_auto_approval_rate": rate(labels["attack"], ["AUTO_APPROVED"]),
        "genuine_auto_approval_rate": rate(labels["genuine"], ["AUTO_APPROVED"]),
        "genuine_rejection_rate": rate(labels["genuine"], ["REJECTED"]),
        "manual_rate": {
            label: rate(group, ["MANUAL_PENDING"]) for label, group in labels.items()
        },
        "technical_rate": {
            label: rate(group, ["TECHNICAL_PENDING"]) for label, group in labels.items()
        },
        "scope": "Measured on supplied labeled results only; no calibration approval or guarantee for unseen cameras.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", type=Path, help="Local JSONL: label, result, mandatory"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        records = [
            json.loads(line)
            for line in args.input.read_text().splitlines()
            if line.strip()
        ]
        report = evaluate(records)
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    text = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
