"""Run the Decisions API over the ISIC test set and write results/evaluation.json.

Usage: uv run python -m tools.evaluate [--limit N] [--workers 8] [--report-only]
Predictions are cached in .tmp/eval/predictions.jsonl, so reruns only call the API
for cases that have no answer yet.
"""
import argparse
import json
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import openai
from dotenv import load_dotenv

from tools import metrics
from tools.decisions_client import MALIGNANT_TYPES, MODEL, QUESTIONS, classify_image

ROOT = Path(__file__).resolve().parent.parent
ISIC = ROOT / ".tmp" / "isic"
PREDICTIONS = ROOT / ".tmp" / "eval" / "predictions.jsonl"
REPORT = ROOT / "results" / "evaluation.json"
THRESHOLD = 0.5

DIAGNOSIS_TO_TYPE = {
    "Nevus": "nevus",
    "Melanoma, NOS": "melanoma",
    "Basal cell carcinoma": "basal_cell_carcinoma",
    "Squamous cell carcinoma, NOS": "squamous_cell_carcinoma",
    "Pigmented benign keratosis": "benign_keratosis",
    "Benign soft tissue proliferations - Vascular": "vascular_lesion",
    "Dermatofibroma": "dermatofibroma",
}


def load_predictions() -> dict[str, dict]:
    if not PREDICTIONS.exists():
        return {}
    rows = (json.loads(line) for line in PREDICTIONS.read_text().splitlines() if line.strip())
    return {row["isic_id"]: row for row in rows}


def run(cases: list[dict], workers: int) -> None:
    done = load_predictions()
    todo = [c for c in cases if c["isic_id"] not in done]
    print(f"{len(done)} cached, {len(todo)} to run")
    if not todo:
        return

    client = openai.OpenAI(max_retries=6, timeout=120)
    PREDICTIONS.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    failures = 0

    def work(case: dict) -> dict:
        return classify_image(client, (ISIC / case["file"]).read_bytes())

    with ThreadPoolExecutor(max_workers=workers) as pool, PREDICTIONS.open("a") as out:
        futures = {pool.submit(work, case): case for case in todo}
        for count, future in enumerate(as_completed(futures), 1):
            case = futures[future]
            try:
                prediction = future.result()
            except (openai.AuthenticationError, openai.PermissionDeniedError) as error:
                pool.shutdown(cancel_futures=True)
                sys.exit(f"OpenAI rejected the request, stopping: {error}")
            except openai.OpenAIError as error:
                failures += 1
                print(f"\n{case['isic_id']} failed: {error}")
                continue
            with lock:
                out.write(json.dumps({"isic_id": case["isic_id"], **prediction}) + "\n")
                out.flush()
            print(f"\r{count}/{len(todo)}", end="", flush=True)
    print()
    if failures:
        print(f"{failures} cases failed and were not cached; rerun to retry them")


def build_report(cases: list[dict]) -> dict:
    predictions = load_predictions()
    rows = []
    for case in cases:
        prediction = predictions.get(case["isic_id"])
        if prediction is None:
            continue
        rows.append(
            {
                "isic_id": case["isic_id"],
                "label": case["label"],
                "diagnosis": case["diagnosis"],
                "true_type": DIAGNOSIS_TO_TYPE.get(case["diagnosis"]),
                "age": case["age"],
                "sex": case["sex"],
                "site": case["site"],
                "probability": prediction["malignant_probability"],
                "predicted_type": prediction["lesion_type"],
                "latency_ms": prediction["latency_ms"],
            }
        )

    answered = [r for r in rows if r["probability"] is not None]
    labels = [int(r["label"] == "malignant") for r in answered]
    probabilities = [r["probability"] for r in answered]
    matrix = metrics.confusion(labels, probabilities, THRESHOLD)

    by_diagnosis = defaultdict(list)
    for r in answered:
        by_diagnosis[r["diagnosis"]].append(r)
    diagnosis_table = []
    for diagnosis, members in sorted(by_diagnosis.items(), key=lambda kv: -len(kv[1])):
        flagged = sum(r["probability"] >= THRESHOLD for r in members)
        is_malignant = members[0]["label"] == "malignant"
        correct = flagged if is_malignant else len(members) - flagged
        typed = [r for r in members if r["predicted_type"] is not None]
        diagnosis_table.append(
            {
                "diagnosis": diagnosis,
                "label": members[0]["label"],
                "n": len(members),
                "correct": correct,
                "correct_rate": correct / len(members),
                "ci": metrics.wilson_interval(correct, len(members)),
                "mean_probability": sum(r["probability"] for r in members) / len(members),
                "type_correct": sum(r["predicted_type"] == r["true_type"] for r in typed),
                "type_n": len(typed),
            }
        )

    typed = [r for r in rows if r["predicted_type"] is not None]
    type_correct = sum(r["predicted_type"] == r["true_type"] for r in typed)
    type_binary_correct = sum(
        (r["predicted_type"] in MALIGNANT_TYPES) == (r["label"] == "malignant") for r in typed
    )
    latencies = [r["latency_ms"] for r in rows]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL,
        "endpoint": "POST /v1/decisions",
        "dataset": {
            "name": "HAM10000 (ISIC Archive)",
            "source": "https://api.isic-archive.com/collections/212/",
            "sampling": "One image per lesion, seeded random sample, balanced by class.",
            "planned": len(cases),
            "evaluated": len(rows),
            "answered": len(answered),
            "refused": len(rows) - len(answered),
            "benign": labels.count(0),
            "malignant": labels.count(1),
        },
        "questions": QUESTIONS,
        "threshold": THRESHOLD,
        "confusion": matrix,
        "rates": metrics.rates(matrix),
        "auc": metrics.roc_auc(labels, probabilities),
        "roc": metrics.roc_curve(labels, probabilities),
        "calibration": metrics.calibration(labels, probabilities),
        "by_diagnosis": diagnosis_table,
        "lesion_type": {
            "n": len(typed),
            "accuracy": type_correct / len(typed) if typed else None,
            "ci": metrics.wilson_interval(type_correct, len(typed)),
            "benign_vs_malignant_accuracy": type_binary_correct / len(typed) if typed else None,
        },
        "latency_ms": {
            "p50": metrics.percentile(latencies, 0.5),
            "p95": metrics.percentile(latencies, 0.95),
            "mean": sum(latencies) / len(latencies) if latencies else None,
        },
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="only evaluate the first N cases")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--report-only", action="store_true", help="rebuild the report from cache")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    cases = json.loads((ISIC / "manifest.json").read_text())
    if args.limit:
        cases = cases[: args.limit]
    if not args.report_only:
        run(cases, args.workers)

    report = build_report(cases)
    if not report["cases"]:
        sys.exit("No predictions yet, nothing to report.")
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report))
    r = report["rates"]
    print(
        f"n={report['dataset']['answered']}  accuracy={r['accuracy']['value']:.3f}  "
        f"sensitivity={r['sensitivity']['value']:.3f}  specificity={r['specificity']['value']:.3f}  "
        f"AUC={report['auc']:.3f}  refused={report['dataset']['refused']}"
    )
    print(f"Wrote {REPORT}")


if __name__ == "__main__":
    main()
