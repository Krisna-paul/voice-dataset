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
    return {
        "total": total, "bengali": bengali,
        "english": english, "mixed": mixed,
        "noisy": noisy, "quiet": quiet
    }


@app.post("/upload/")
async def upload(
    audio_data:  str = Form(...),
    text:        str = Form(...),
    language:    str = Form(...),
    environment: str = Form(...),
):
    text = text.strip()
    if not text or len(text) > 1000:
        raise HTTPException(status_code=400, detail="Text must be 1–1000 characters.")

    if language.lower() not in VALID_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Language must be one of: {VALID_LANGUAGES}")

    if environment.lower() not in VALID_NOISE:
        raise HTTPException(status_code=400, detail=f"Environment must be one of: {VALID_NOISE}")

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

    filename  = f"{uuid.uuid4()}.webm"
    timestamp = datetime.utcnow().isoformat()

    entry = {
        "filename":    filename,
        "text":        text,
        "language":    language.lower(),
        "environment": environment.lower(),
        "timestamp":   timestamp,
        "audio_b64":   encoded,
    }

    try:
        await collection.insert_one(entry)
    except Exception as e:
        logger.error(f"MongoDB insert failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to save to database.")

    logger.info(f"Saved {filename} | lang={language} | env={environment} | text={text[:40]}")
    return JSONResponse({"message": "Saved successfully!", "filename": filename})


@app.get("/download-csv")
async def download_csv():
    entries = await collection.find({}, {"audio_b64": 0}).to_list(length=10000)
    if not entries:
        raise HTTPException(status_code=404, detail="No data yet.")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["filename", "text", "language", "environment", "timestamp"])
    for e in entries:
        writer.writerow([
            e.get("filename", ""),
            e.get("text", ""),
            e.get("language", ""),
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
        raise HTTPException(status_code=404, detail="Audio not found.")
    
    audio_bytes = base64.b64decode(entry["audio_b64"])
    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/webm",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/debug")
async def debug():
    total = await collection.count_documents({})
    return {
        "mongo_connected": True,
        "total_entries": total,
        "database": "voicedb",
        "collection": "entries"
    }
