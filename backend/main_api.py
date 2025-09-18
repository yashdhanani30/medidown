from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import os
import uuid
import tempfile
from typing import List, Optional
import sqlite3
import json
from datetime import datetime

app = FastAPI(title="MediDown Backend", version="1.0.0")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check for Render
@app.get("/health")
def health():
    return {"status": "ok"}

# Database setup (simple SQLite)
DB_PATH = os.getenv("DB_PATH", os.path.join(tempfile.gettempdir(), "downloads.db"))

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id TEXT PRIMARY KEY,
            url TEXT,
            title TEXT,
            format TEXT,
            status TEXT,
            file_path TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

class DownloadRequest(BaseModel):
    url: str
    format: str = "best"  # e.g., best, mp4, mp3, etc.
    convert: Optional[str] = None  # e.g., mp3 for audio

class DownloadResponse(BaseModel):
    id: str
    status: str

class DownloadStatus(BaseModel):
    id: str
    status: str
    title: Optional[str]
    file_path: Optional[str]

@app.post("/download", response_model=DownloadResponse)
async def start_download(request: DownloadRequest, background_tasks: BackgroundTasks):
    download_id = str(uuid.uuid4())
    background_tasks.add_task(process_download, download_id, request.url, request.format, request.convert)
    return DownloadResponse(id=download_id, status="queued")

@app.get("/download/{download_id}", response_model=DownloadStatus)
async def get_download_status(download_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM downloads WHERE id = ?", (download_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Download not found")
    return DownloadStatus(id=row[0], status=row[3], title=row[2], file_path=row[4])

@app.get("/download/{download_id}/file")
async def download_file(download_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT file_path, title FROM downloads WHERE id = ?", (download_id,))
    row = cursor.fetchone()
    conn.close()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="File not ready")
    return FileResponse(row[0], filename=row[1])

# History endpoint
@app.get("/history")
async def get_history():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, url, title, format, status, created_at FROM downloads ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "url": r[1], "title": r[2], "format": r[3], "status": r[4], "created_at": r[5]} for r in rows]

def process_download(download_id: str, url: str, format: str, convert: Optional[str]):
    try:
        # Update status to downloading
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO downloads (id, url, status, created_at) VALUES (?, ?, 'downloading', ?)", (download_id, url, datetime.now().isoformat()))
        conn.commit()

        # yt-dlp options
        ydl_opts = {
            'outtmpl': os.path.join(tempfile.gettempdir(), f'{download_id}.%(ext)s'),
            'format': format,
        }
        if convert:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': convert,
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Unknown')
            file_path = ydl.prepare_filename(info)

        # Update status to completed
        cursor.execute("UPDATE downloads SET status = 'completed', title = ?, file_path = ? WHERE id = ?", (title, file_path, download_id))
        conn.commit()
        conn.close()
    except Exception as e:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE downloads SET status = 'failed' WHERE id = ?", (download_id,))
        conn.commit()
        conn.close()
        print(f"Download failed: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)