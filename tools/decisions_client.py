"""Skin-lesion classification through the OpenAI Decisions API (POST /v1/decisions)."""
import base64
import io
import time

from openai import OpenAI
from PIL import Image

MODEL = "gpt-6-luna"
MAX_SIDE = 1024

LESION_TYPES = [
    ("melanoma", "Melanoma: malignant melanocytic tumour."),
    ("basal_cell_carcinoma", "Basal cell carcinoma: malignant."),
    ("squamous_cell_carcinoma", "Squamous cell carcinoma, including Bowen's disease: malignant."),
    ("nevus", "Melanocytic nevus (common mole): benign."),
    ("benign_keratosis", "Seborrheic keratosis, solar lentigo or lichen-planus-like keratosis: benign."),
    ("dermatofibroma", "Dermatofibroma: benign."),
    ("vascular_lesion", "Angioma, angiokeratoma, pyogenic granuloma or haemorrhage: benign."),
    ("other", "None of the above, or not a skin lesion."),
]
MALIGNANT_TYPES = {"melanoma", "basal_cell_carcinoma", "squamous_cell_carcinoma"}

QUESTIONS = [
    {
        "type": "predicate",
        "name": "malignant",
        "instructions": (
            "Is the skin lesion in this image malignant (melanoma, basal cell carcinoma or "
            "squamous cell carcinoma) rather than benign (nevus, benign keratosis, "
            "dermatofibroma or vascular lesion)? Judge only from what is visible, using "
            "dermoscopic criteria such as asymmetry, border irregularity, colour variegation, "
            "atypical network, blue-white veil, arborising vessels and ulceration."
        ),
    },
    {
        "type": "choice",
        "name": "lesion_type",
        "instructions": "Which diagnosis best matches the skin lesion in this image?",
        "choices": [{"value": v, "description": d} for v, d in LESION_TYPES],
    },
    {
        "type": "predicate",
        "name": "is_skin_lesion",
        "instructions": "Does this image show a close-up or dermoscopic view of a human skin lesion?",
    },
]


def prepare_image(data: bytes) -> str:
    """Return a JPEG data URL, downscaled so the longest side is at most MAX_SIDE."""
    image = Image.open(io.BytesIO(data))
    if image.format != "JPEG" or max(image.size) > MAX_SIDE:
        image = image.convert("RGB")
        image.thumbnail((MAX_SIDE, MAX_SIDE))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=92)
        data = buffer.getvalue()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def parse_answers(answers: list[dict]) -> dict:
    by_name = {a["name"]: a for a in answers}
    refused = sorted(name for name, a in by_name.items() if a["type"] == "refusal")
    result = {
        "malignant_probability": None,
        "lesion_type": None,
        "lesion_type_confidence": None,
        "lesion_type_probabilities": {},
        "is_skin_lesion_probability": None,
        "refused": refused,
    }
    malignant = by_name.get("malignant")
    if malignant and malignant["type"] == "predicate":
        result["malignant_probability"] = malignant["probability"]
    lesion = by_name.get("lesion_type")
    if lesion and lesion["type"] == "choice":
        result["lesion_type"] = lesion["choice"]
        result["lesion_type_confidence"] = lesion.get("confidence")
        result["lesion_type_probabilities"] = {
            p["value"]: p["probability"] for p in lesion.get("probabilities", [])
        }
    is_lesion = by_name.get("is_skin_lesion")
    if is_lesion and is_lesion["type"] == "predicate":
        result["is_skin_lesion_probability"] = is_lesion["probability"]
    return result


def classify_image(client: OpenAI, data: bytes) -> dict:
    image_url = prepare_image(data)
    started = time.perf_counter()
    decision = client.decisions.create(
        model=MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Assess the skin lesion in this dermoscopic image."},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ],
        questions=QUESTIONS,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)
    result = parse_answers(decision.model_dump()["answers"])
    result["latency_ms"] = latency_ms
    result["model"] = MODEL
    return result
