"""Download a balanced, seeded benign/malignant sample of HAM10000 from the ISIC archive.

Usage: uv run python -m tools.fetch_isic --n 500
Writes .tmp/isic/manifest.json and .tmp/isic/images/<isic_id>.jpg
"""
import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

API = "https://api.isic-archive.com/api/v2/images/search/"
HAM10000_COLLECTION = "212"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".tmp" / "isic"


def fetch_metadata(client: httpx.Client, label: str) -> list[dict]:
    cache = OUT / f"metadata_{label.lower()}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    rows = []
    url = API
    params = {"query": f"diagnosis_1:{label}", "collections": HAM10000_COLLECTION, "limit": "100"}
    while url:
        r = client.get(url, params=params)
        r.raise_for_status()
        page = r.json()
        rows.extend(page["results"])
        url, params = page.get("next"), None
        print(f"\r{label}: {len(rows)}/{page.get('count', '?')}", end="", flush=True)
    print()
    cache.write_text(json.dumps(rows))
    return rows


def one_per_lesion(rows: list[dict]) -> list[dict]:
    """HAM10000 has several images of some lesions; keep one so cases are independent."""
    by_lesion = {}
    for row in sorted(rows, key=lambda r: r["isic_id"]):
        lesion = row["metadata"]["clinical"].get("lesion_id") or row["isic_id"]
        by_lesion.setdefault(lesion, row)
    return list(by_lesion.values())


def to_case(row: dict, label: str) -> dict:
    clinical = row["metadata"]["clinical"]
    return {
        "isic_id": row["isic_id"],
        "label": label.lower(),
        "diagnosis": clinical.get("diagnosis_3") or clinical.get("diagnosis_2") or "Unknown",
        "confirmed_by": clinical.get("diagnosis_confirm_type"),
        "age": clinical.get("age_approx"),
        "sex": clinical.get("sex"),
        "site": clinical.get("anatom_site_1"),
        "url": row["files"]["full"]["url"],
        "file": f"images/{row['isic_id']}.jpg",
    }


def download(client: httpx.Client, case: dict) -> None:
    dest = OUT / case["file"]
    if dest.exists() and dest.stat().st_size > 0:
        return
    r = client.get(case["url"])
    r.raise_for_status()
    dest.write_bytes(r.content)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=500, help="total cases, split evenly")
    parser.add_argument("--seed", type=int, default=20261009)
    args = parser.parse_args()

    (OUT / "images").mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    cases = []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for label in ("Benign", "Malignant"):
            lesions = one_per_lesion(fetch_metadata(client, label))
            rng.shuffle(lesions)
            picked = lesions[: args.n // 2]
            print(f"{label}: {len(lesions)} distinct lesions, sampled {len(picked)}")
            cases.extend(to_case(row, label) for row in picked)

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(lambda c: download(client, c), cases))

    rng.shuffle(cases)
    (OUT / "manifest.json").write_text(json.dumps(cases, indent=1))
    print(f"Wrote {len(cases)} cases to {OUT / 'manifest.json'}")


if __name__ == "__main__":
    main()
