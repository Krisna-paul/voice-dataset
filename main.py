import os
import csv
import uuid
import base64
import asyncio
import logging
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Voice Dataset Collector")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# On Render, the persistent disk is mounted at /app/dataset
# Locally, it falls back to a dataset/ folder next to main.py
DATASET_DIR = os.environ.get("DATASET_DIR", os.path.join(BASE_DIR, "dataset"))
AUDIO_DIR   = os.path.join(DATASET_DIR, "audio")

os.makedirs(AUDIO_DIR, exist_ok=True)

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

CSV_FILE           = os.path.join(DATASET_DIR, "metadata.csv")
MAX_AUDIO_SIZE_MB  = 10
VALID_LANGUAGES    = {"bengali", "english", "mixed"}
VALID_NOISE        = {"noisy", "quiet"}

csv_lock = asyncio.Lock()

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["filename", "text", "language", "environment", "timestamp"])


@app.get("/", response_class=HTMLResponse)
async def form(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/stats")
async def stats():
    """Return dataset statistics."""
    if not os.path.exists(CSV_FILE):
        return {"total": 0, "bengali": 0, "english": 0, "mixed": 0, "noisy": 0, "quiet": 0}

    counts = {"total": 0, "bengali": 0, "english": 0, "mixed": 0, "noisy": 0, "quiet": 0}
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            counts["total"] += 1
            lang = row.get("language", "").lower()
            env  = row.get("environment", "").lower()
            if lang in counts:
                counts[lang] += 1
            if env in counts:
                counts[env] += 1
    return counts


@app.post("/upload/")
async def upload(
    audio_data:  str = Form(...),
    text:        str = Form(...),
    language:    str = Form(...),
    environment: str = Form(...),
):
    from datetime import datetime

    # Validate text
    text = text.strip()
    if not text or len(text) > 1000:
        raise HTTPException(status_code=400, detail="Text must be 1–1000 characters.")

    # Validate language
    if language.lower() not in VALID_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Language must be one of: {VALID_LANGUAGES}")

    # Validate environment
    if environment.lower() not in VALID_NOISE:
        raise HTTPException(status_code=400, detail=f"Environment must be one of: {VALID_NOISE}")

    # Validate and decode audio
    if "," not in audio_data:
        raise HTTPException(status_code=400, detail="Invalid audio format.")

    header, encoded = audio_data.split(",", 1)
    if not header.startswith("data:audio/"):
        raise HTTPException(status_code=400, detail="Uploaded data is not audio.")

    try:
        audio_bytes = base64.b64decode(encoded)
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to decode audio data.")

    if len(audio_bytes) > MAX_AUDIO_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"Audio exceeds {MAX_AUDIO_SIZE_MB}MB limit.")

    # Save audio
    filename  = f"{uuid.uuid4()}.webm"
    file_path = os.path.join(AUDIO_DIR, filename)

    try:
        with open(file_path, "wb") as f:
            f.write(audio_bytes)
    except IOError as e:
        logger.error(f"Failed to save audio: {e}")
        raise HTTPException(status_code=500, detail="Failed to save audio file.")

    # Save metadata
    timestamp = datetime.utcnow().isoformat()
    async with csv_lock:
        try:
            with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([filename, text, language.lower(), environment.lower(), timestamp])
        except IOError as e:
            logger.error(f"CSV write failed: {e}")
            os.remove(file_path)
            raise HTTPException(status_code=500, detail="Failed to save metadata.")

    logger.info(f"Saved {filename} | lang={language} | env={environment} | text={text[:40]}")
    return JSONResponse({"message": "Saved successfully!", "filename": filename})
