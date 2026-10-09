# Lesion check

Classifies a skin-lesion image as benign or malignant with OpenAI's Decisions API
(`POST /v1/decisions`, model `gpt-6-luna`), evaluates it on HAM10000, and shows both in a web UI.

Research demonstration only. Not a medical device.

## Setup

```bash
uv sync
# put your key in .env:  OPENAI_API_KEY=sk-...
```

The Decisions API is in beta; the key's account needs access to it.

## Run

```bash
uv run python -m tools.fetch_isic --n 500   # download the balanced test set (no key needed)
uv run python -m tools.evaluate             # call the API for each image, write results/evaluation.json
uv run uvicorn app.server:app --port 8642   # open http://localhost:8642
uv run pytest                               # unit tests for metrics and response parsing
```

`tools.evaluate` caches every answer in `.tmp/eval/predictions.jsonl`, so an interrupted run
resumes without paying twice. `--limit 20` runs a small smoke test; `--report-only` rebuilds
the report from the cache.

## Layout

- `tools/decisions_client.py`: the three questions sent with each image and response parsing
- `tools/fetch_isic.py`: seeded, one-image-per-lesion sample from the ISIC Archive
- `tools/evaluate.py`, `tools/metrics.py`: evaluation run and statistics
- `app/server.py`, `app/static/`: FastAPI server and the UI

## Results

500 HAM10000 images (250 benign, 250 malignant), 50% cut-off fixed before the run; 499 answered, 1 refused.

| Measure | Result | 95% range |
|---|---|---|
| Accuracy | 61.9% | 58% to 66% |
| Sensitivity | 35.6% (89 of 250 cancers caught) | 30% to 42% |
| Specificity | 88.4% (220 of 249 benign cleared) | 84% to 92% |
| Precision | 75.4% | 67% to 82% |
| AUC | 0.649 | |
| Median response | 171 ms | |

The full report is in `results/evaluation.json` and a walkthrough video is in `recordings/`.
Test images are from HAM10000 in the ISIC Archive and are not stored in this repository.
