"""Web app: serves the UI, classifies uploaded images and exposes the evaluation report.

Usage: uv run uvicorn app.server:app --port 8642
"""
import json
import os
from pathlib import Path

import openai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import UnidentifiedImageError

from tools.decisions_client import LESION_TYPES, MALIGNANT_TYPES, classify_image

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / ".tmp" / "isic" / "images"
MANIFEST = ROOT / ".tmp" / "isic" / "manifest.json"
REPORT = Path(os.environ.get("EVALUATION_REPORT", ROOT / "results" / "evaluation.json"))
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

load_dotenv(ROOT / ".env")
app = FastAPI(title="Skin lesion malignancy check")


def run_classification(data: bytes) -> dict:
    try:
        client = openai.OpenAI(max_retries=2, timeout=60)
        return classify_image(client, data)
    except UnidentifiedImageError:
        raise HTTPException(400, "That file is not an image this app can read. Use a JPEG or PNG.")
    except openai.OpenAIError as error:
        if isinstance(error, openai.AuthenticationError) or "api_key" in str(error):
            raise HTTPException(503, "OpenAI rejected the API key. Check OPENAI_API_KEY in .env.")
        if isinstance(error, openai.PermissionDeniedError):
            raise HTTPException(503, f"This OpenAI account cannot use the Decisions API: {error}")
        raise HTTPException(502, f"OpenAI request failed: {error}")


@app.get("/api/config")
def config() -> dict:
    return {
        "lesion_types": [
            {"value": value, "description": description, "malignant": value in MALIGNANT_TYPES}
            for value, description in LESION_TYPES
        ]
    }


@app.post("/api/classify")
async def classify(file: UploadFile) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image is larger than 15 MB.")
    return run_classification(data)


@app.post("/api/classify/{isic_id}")
def classify_test_case(isic_id: str) -> dict:
    return run_classification(image_path(isic_id).read_bytes())


@app.get("/api/evaluation")
def evaluation() -> dict:
    if not REPORT.exists():
        raise HTTPException(404, "No evaluation yet. Run: uv run python -m tools.evaluate")
    return json.loads(REPORT.read_text())


@app.get("/api/samples")
def samples(limit: int = 12) -> list[dict]:
    if not MANIFEST.exists():
        return []
    keys = ("isic_id", "label", "diagnosis", "confirmed_by")
    return [{k: case[k] for k in keys} for case in json.loads(MANIFEST.read_text())[:limit]]


def image_path(isic_id: str) -> Path:
    path = IMAGES / f"{isic_id}.jpg"
    if not isic_id.replace("_", "").isalnum() or not path.exists():
        raise HTTPException(404, "Unknown test image.")
    return path


@app.get("/images/{isic_id}.jpg")
def image(isic_id: str) -> FileResponse:
    return FileResponse(image_path(isic_id), headers={"Cache-Control": "public, max-age=86400"})


app.mount("/", StaticFiles(directory=ROOT / "app" / "static", html=True), name="static")
