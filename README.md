# VoiceForge — Voice Dataset Studio

A clean web app for collecting labelled voice data from friends/contributors.

## Features
- 🎤 Live voice recording with real-time waveform
- 📝 Transcript input
- 🏷️ Language label: Bengali / English / Mixed
- 🔊 Environment label: Noisy / Quiet
- 📊 Live dataset stats on the page
- Session counter per browser session

## Dataset Output
Audio files saved to `dataset/audio/` as `.webm`.
Metadata saved to `dataset/metadata.csv`:
```
filename, text, language, environment, timestamp
```

---

## Setup & Run Locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload
# Open http://localhost:8000
```

---

## Share With Friends (Two Options)

### Option A — ngrok (easiest, temporary link)
1. Install ngrok: https://ngrok.com/download
2. Run the app:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```
3. In a second terminal:
   ```bash
   ngrok http 8000
   ```
4. Share the `https://xxxx.ngrok-free.app` link with your friends.
   They can open it on any device — phone, laptop, etc.

### Option B — Deploy to Railway (free, permanent link)
1. Push this folder to a GitHub repo.
2. Go to https://railway.app → New Project → Deploy from GitHub.
3. Set start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Railway gives a permanent public URL to share.

### Option C — Run on same WiFi
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```
Find your local IP (e.g. `192.168.1.5`) and share:
`http://192.168.1.5:8000` — works for anyone on the same WiFi.

---

## Download Dataset
All collected data lives in the `dataset/` folder:
- `dataset/metadata.csv` — labels + transcripts
- `dataset/audio/*.webm` — audio files
