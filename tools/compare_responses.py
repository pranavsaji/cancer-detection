"""Ask the same malignancy question through the Responses API, to compare with the Decisions API.

Usage: uv run python -m tools.compare_responses [--limit N] [--workers 8]
Same model, same images, same instructions; the answer comes back as structured JSON.
Writes results/comparison.json. Answers are cached in .tmp/eval/responses_predictions.jsonl.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import openai
from dotenv import load_dotenv

from tools import metrics
from tools.decisions_client import LESION_TYPES, MODEL, QUESTIONS, prepare_image
from tools.evaluate import DIAGNOSIS_TO_TYPE, ISIC, ROOT, THRESHOLD, load_predictions

CACHE = ROOT / ".tmp" / "eval" / "responses_predictions.jsonl"
REPORT = ROOT / "results" / "comparison.json"

SCHEMA = {
    "type": "object",
    "properties": {
        "malignant_probability": {"type": "number", "description": "Between 0 and 1."},
        "lesion_type": {"type": "string", "enum": [value for value, _ in LESION_TYPES]},
    },
    "required": ["malignant_probability", "lesion_type"],
    "additionalProperties": False,
}
PROMPT = (
    "Assess the skin lesion in this dermoscopic image.\n\n"
    f"malignant_probability: the probability that the answer to this question is yes. {QUESTIONS[0]['instructions']}\n\n"
    f"lesion_type: {QUESTIONS[1]['instructions']} Options:\n"
    + "\n".join(f"- {value}: {description}" for value, description in LESION_TYPES)
)


def ask(client: openai.OpenAI, data: bytes) -> dict:
    started = time.perf_counter()
    response = client.responses.create(
        model=MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": PROMPT},
                    {"type": "input_image", "image_url": prepare_image(data)},
                ],
            }
        ],
        text={"format": {"type": "json_schema", "name": "lesion_assessment", "schema": SCHEMA, "strict": True}},
    )
    latency_ms = round((time.perf_counter() - started) * 1000)
    try:
        answer = json.loads(response.output_text)
        probability = min(1.0, max(0.0, float(answer["malignant_probability"])))
        lesion_type = answer["lesion_type"]
    except (ValueError, KeyError, TypeError):
        probability, lesion_type = None, None
    usage = response.usage
    return {
        "malignant_probability": probability,
        "lesion_type": lesion_type,
        "latency_ms": latency_ms,
        "input_tokens": usage.input_tokens if usage else None,
        "output_tokens": usage.output_tokens if usage else None,
    }


def load_cache() -> dict[str, dict]:
    if not CACHE.exists():
        return {}
    return {row["isic_id"]: row for row in map(json.loads, filter(None, CACHE.read_text().splitlines()))}


def run(cases: list[dict], workers: int) -> None:
    todo = [c for c in cases if c["isic_id"] not in load_cache()]
    print(f"{len(cases) - len(todo)} cached, {len(todo)} to run")
    if not todo:
        return
    client = openai.OpenAI(max_retries=6, timeout=180)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool, CACHE.open("a") as out:
        futures = {pool.submit(ask, client, (ISIC / c["file"]).read_bytes()): c for c in todo}
        for count, future in enumerate(as_completed(futures), 1):
            case = futures[future]
            try:
                row = future.result()
            except (openai.AuthenticationError, openai.PermissionDeniedError, openai.BadRequestError) as error:
                pool.shutdown(cancel_futures=True)
                sys.exit(f"OpenAI rejected the request, stopping: {error}")
            except openai.OpenAIError as error:
                print(f"\n{case['isic_id']} failed: {error}")
                continue
            out.write(json.dumps({"isic_id": case["isic_id"], **row}) + "\n")
            out.flush()
            print(f"\r{count}/{len(todo)}", end="", flush=True)
    print()


def summarise(cases: list[dict], predictions: dict[str, dict]) -> dict:
    rows = [(c, predictions[c["isic_id"]]) for c in cases if c["isic_id"] in predictions]
    answered = [(c, p) for c, p in rows if p["malignant_probability"] is not None]
    labels = [int(c["label"] == "malignant") for c, _ in answered]
    probabilities = [p["malignant_probability"] for _, p in answered]
    matrix = metrics.confusion(labels, probabilities, THRESHOLD)
    typed = [(c, p) for c, p in rows if p.get("lesion_type")]
    latencies = [p["latency_ms"] for _, p in rows]
    return {
        "evaluated": len(rows),
        "answered": len(answered),
        "confusion": matrix,
        "rates": metrics.rates(matrix),
        "auc": metrics.roc_auc(labels, probabilities),
        "brier": metrics.calibration(labels, probabilities)["brier"],
        "lesion_type_accuracy": (
            sum(p["lesion_type"] == DIAGNOSIS_TO_TYPE.get(c["diagnosis"]) for c, p in typed) / len(typed)
            if typed else None
        ),
        "latency_ms": {"p50": metrics.percentile(latencies, 0.5), "p95": metrics.percentile(latencies, 0.95)},
        "mean_input_tokens": _mean([p.get("input_tokens") for _, p in rows]),
        "mean_output_tokens": _mean([p.get("output_tokens") for _, p in rows]),
    }


def _mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    cases = json.loads((ISIC / "manifest.json").read_text())
    if args.limit:
        cases = cases[: args.limit]
    run(cases, args.workers)

    responses = load_cache()
    shared = [c for c in cases if c["isic_id"] in responses]
    report = {
        "model": MODEL,
        "threshold": THRESHOLD,
        "cases": len(shared),
        "decisions_api": summarise(shared, load_predictions()),
        "responses_api": summarise(shared, responses),
    }
    REPORT.write_text(json.dumps(report, indent=1))
    for name in ("decisions_api", "responses_api"):
        s = report[name]
        r = s["rates"]
        print(
            f"{name:14} n={s['answered']} acc={r['accuracy']['value']:.3f} sens={r['sensitivity']['value']:.3f} "
            f"spec={r['specificity']['value']:.3f} auc={s['auc']:.3f} type={s['lesion_type_accuracy']:.3f} "
            f"p50={s['latency_ms']['p50']:.0f}ms p95={s['latency_ms']['p95']:.0f}ms "
            f"tokens in/out={s['mean_input_tokens']}/{s['mean_output_tokens']}"
        )


if __name__ == "__main__":
    main()
