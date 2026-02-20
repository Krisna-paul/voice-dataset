import os
import uuid
import base64
import logging
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import csv
import io
import zipfile


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Voice Dataset Collector")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# MongoDB
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
client = AsyncIOMotorClient(MONGO_URI)
db = client["voicedb"]
collection = db["entries"]

MAX_AUDIO_SIZE_MB = 10
VALID_LANGUAGES   = {"bengali", "english", "mixed"}
VALID_NOISE       = {"noisy", "quiet"}
VALID_INTENTS     = {
    "pick_and_place", "pick_object", "place_object",
    "move_robot", "query_weather", "query_cricket",
    "arm_home", "stop", "greet", ""
}
VALID_COLORS      = {
    "red", "green", "blue", "yellow", "orange",
    "white", "black", "purple", "pink", ""
}
VALID_DIRECTIONS  = {"forward", "backward", "left", "right", ""}


@app.get("/", response_class=HTMLResponse)
async def form(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/stats")
async def stats():
    total   = await collection.count_documents({})
    bengali = await collection.count_documents({"language": "bengali"})
    english = await collection.count_documents({"language": "english"})
    mixed   = await collection.count_documents({"language": "mixed"})
    noisy   = await collection.count_documents({"environment": "noisy"})
    quiet   = await collection.count_documents({"environment": "quiet"})

    # Intent breakdown
    intent_counts = {}
    for intent in ["pick_and_place", "pick_object", "place_object",
                   "move_robot", "query_weather", "query_cricket",
                   "arm_home", "stop", "greet"]:
        intent_counts[intent] = await collection.count_documents({"intent": intent})

    return {
        "total": total, "bengali": bengali,
        "english": english, "mixed": mixed,
        "noisy": noisy, "quiet": quiet,
        "intents": intent_counts,
    }


@app.post("/upload/")
async def upload(
    audio_data:   str = Form(...),
    text:         str = Form(...),
    language:     str = Form(...),
    environment:  str = Form(...),
    speaker_id:   str = Form(...),
    intent:       str = Form(""),
    object_color: str = Form(""),
    target_color: str = Form(""),
    direction:    str = Form(""),
):
    # ── Validate text ─────────────────────────────────────────
    text = text.strip()
    if not text or len(text) > 1000:
        raise HTTPException(400, "Text must be 1–1000 characters.")

    # ── Validate speaker_id ───────────────────────────────────
    speaker_id = speaker_id.strip().upper()
    if not speaker_id:
        raise HTTPException(400, "Speaker ID is required.")
    if len(speaker_id) > 20:
        raise HTTPException(400, "Speaker ID too long (max 20 chars).")

    # ── Validate enums ────────────────────────────────────────
    if language.lower() not in VALID_LANGUAGES:
        raise HTTPException(400, f"Language must be one of: {VALID_LANGUAGES}")
    if environment.lower() not in VALID_NOISE:
        raise HTTPException(400, f"Environment must be one of: {VALID_NOISE}")
    if intent.lower() not in VALID_INTENTS:
        raise HTTPException(400, f"Intent must be one of: {VALID_INTENTS}")
    if object_color.lower() not in VALID_COLORS:
        raise HTTPException(400, f"Object color must be one of: {VALID_COLORS}")
    if target_color.lower() not in VALID_COLORS:
        raise HTTPException(400, f"Target color must be one of: {VALID_COLORS}")
    if direction.lower() not in VALID_DIRECTIONS:
        raise HTTPException(400, f"Direction must be one of: {VALID_DIRECTIONS}")

    # ── Validate audio ────────────────────────────────────────
    if "," not in audio_data:
        raise HTTPException(400, "Invalid audio format.")
    header, encoded = audio_data.split(",", 1)
    if not header.startswith("data:audio/"):
        raise HTTPException(400, "Uploaded data is not audio.")
    try:
        audio_bytes = base64.b64decode(encoded)
    except Exception:
        raise HTTPException(400, "Failed to decode audio data.")
    if len(audio_bytes) > MAX_AUDIO_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"Audio exceeds {MAX_AUDIO_SIZE_MB}MB limit.")

    # ── Build entry ───────────────────────────────────────────
    filename  = f"{uuid.uuid4()}.webm"
    timestamp = datetime.utcnow().isoformat()

    entry = {
        "filename":     filename,
        "speaker_id":   speaker_id,
        "text":         text,
        "language":     language.lower(),
        "environment":  environment.lower(),
        "intent":       intent.lower(),
        "object_color": object_color.lower(),
        "target_color": target_color.lower(),
        "direction":    direction.lower(),
        "timestamp":    timestamp,
        "audio_b64":    encoded,
    }

    try:
        await collection.insert_one(entry)
    except Exception as e:
        logger.error(f"MongoDB insert failed: {e}")
        raise HTTPException(500, "Failed to save to database.")

    logger.info(
        f"Saved {filename} | spk={speaker_id} | lang={language} "
        f"| intent={intent} | env={environment} | text={text[:40]}"
    )
    return JSONResponse({"message": "Saved successfully!", "filename": filename})


@app.get("/download-csv")
async def download_csv():
    entries = await collection.find({}, {"audio_b64": 0}).to_list(length=10000)
    if not entries:
        raise HTTPException(404, "No data yet.")

    output = io.StringIO()
    writer = csv.writer(output)
    # ── Updated header with all new columns ──────────────────
    writer.writerow([
        "filename", "speaker_id", "text", "language",
        "intent", "object_color", "target_color", "direction",
        "environment", "timestamp"
    ])
    for e in entries:
        writer.writerow([
            e.get("filename", ""),
            e.get("speaker_id", ""),
            e.get("text", ""),
            e.get("language", ""),
            e.get("intent", ""),
            e.get("object_color", ""),
            e.get("target_color", ""),
            e.get("direction", ""),
            e.get("environment", ""),
            e.get("timestamp", ""),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=metadata.csv"}
    )


@app.get("/download-audio/{filename}")
async def download_audio(filename: str):
    entry = await collection.find_one({"filename": filename})
    if not entry:
        raise HTTPException(404, "Audio not found.")
    audio_bytes = base64.b64decode(entry["audio_b64"])
    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/webm",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/download-all")
async def download_all():
    entries = await collection.find({}).to_list(length=10000)
    if not entries:
        raise HTTPException(404, "No data yet.")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        csv_output = io.StringIO()
        writer = csv.writer(csv_output)
        writer.writerow([
            "filename", "speaker_id", "text", "language",
            "intent", "object_color", "target_color", "direction",
            "environment", "timestamp"
        ])
        for e in entries:
            writer.writerow([
                e.get("filename", ""),
                e.get("speaker_id", ""),
                e.get("text", ""),
                e.get("language", ""),
                e.get("intent", ""),
                e.get("object_color", ""),
                e.get("target_color", ""),
                e.get("direction", ""),
                e.get("environment", ""),
                e.get("timestamp", ""),
            ])
            if "audio_b64" in e:
                audio_bytes = base64.b64decode(e["audio_b64"])
                zf.writestr(f"audio/{e['filename']}", audio_bytes)

        zf.writestr("metadata.csv", csv_output.getvalue())

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=dataset.zip"}
    )


@app.get("/debug")
async def debug():
    total = await collection.count_documents({})
    sample = await collection.find_one({}, {"audio_b64": 0, "_id": 0})
    return {
        "mongo_connected": True,
        "total_entries": total,
        "database": "voicedb",
        "collection": "entries",
        "sample_entry": sample,
    }
