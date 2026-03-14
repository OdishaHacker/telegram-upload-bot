import os
import uuid
import json
import tempfile
import asyncio
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from telethon import TelegramClient
from telethon.sessions import StringSession

app = FastAPI(title="TeleStore API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
API_ID      = int(os.getenv("API_ID", "0"))
API_HASH    = os.getenv("API_HASH", "")
CHANNEL_ID  = int(os.getenv("CHANNEL_ID", "0"))
BASE_URL    = os.getenv("BASE_URL", "http://localhost:9500")
SESSION_STR = os.getenv("SESSION_STRING", "")
DB_FILE     = "/app/files_db.json"

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

_client = None
upload_jobs = {}

async def get_client():
    global _client
    if _client is None or not _client.is_connected():
        session = StringSession(SESSION_STR) if SESSION_STR else StringSession()
        _client = TelegramClient(
            session, API_ID, API_HASH,
            connection_retries=5,
            # Use multiple connections for faster upload/download
            request_retries=5,
        )
        await _client.start(bot_token=BOT_TOKEN)
    return _client

def load_db():
    if not Path(DB_FILE).exists():
        return {}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


@app.get("/", response_class=HTMLResponse)
async def root():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text())
    return HTMLResponse(content="<h1>TeleStore Running</h1>")


async def do_upload(job_id: str, file_content: bytes, filename: str, content_type: str):
    file_size = len(file_content)
    mb_total = file_size / (1024 * 1024)
    suffix = Path(filename).suffix or ".bin"
    tmp_path = None

    try:
        upload_jobs[job_id] = {"percent": 2, "status": "Saving file...", "done": False, "error": None}

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        upload_jobs[job_id] = {"percent": 5, "status": "Connecting to Telegram...", "done": False, "error": None}

        client = await get_client()
        caption = f"📁 {filename}\n💾 {format_size(file_size)}"
        progress_state = {"current": 0}

        def progress_callback(current, total):
            progress_state["current"] = current
            pct = max(5, min(95, int((current / file_size) * 90) + 5)) if file_size > 0 else 5
            mb_done = current / (1024 * 1024)
            upload_jobs[job_id] = {
                "percent": pct,
                "status": f"Uploading... {mb_done:.1f} MB / {mb_total:.1f} MB",
                "done": False,
                "error": None
            }

        message = await client.send_file(
            CHANNEL_ID,
            tmp_path,
            caption=caption,
            force_document=True,
            progress_callback=progress_callback,
            # Max workers for parallel upload parts
            workers=4,
        )

        upload_jobs[job_id] = {"percent": 97, "status": "Saving link...", "done": False, "error": None}

        short_id = str(uuid.uuid4())[:8]
        db = load_db()
        db[short_id] = {
            "message_id": message.id,
            "filename": filename,
            "size": file_size,
            "content_type": content_type,
            "channel_id": CHANNEL_ID,
        }
        save_db(db)

        upload_jobs[job_id] = {
            "percent": 100,
            "status": "Upload complete!",
            "done": True,
            "error": None,
            "result": {
                "success": True,
                "filename": filename,
                "size": format_size(file_size),
                "download_link": f"{BASE_URL}/download/{short_id}",
                "short_id": short_id
            }
        }

    except Exception as e:
        upload_jobs[job_id] = {"percent": 0, "status": "Failed", "done": True, "error": str(e)}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not BOT_TOKEN or not API_ID or not API_HASH or not CHANNEL_ID:
        raise HTTPException(status_code=500, detail="Missing config")

    file_content = await file.read()
    file_size = len(file_content)

    if file_size > 2 * 1024 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max 2GB.")

    job_id = str(uuid.uuid4())[:12]
    upload_jobs[job_id] = {"percent": 0, "status": "Starting...", "done": False, "error": None}
    asyncio.create_task(do_upload(job_id, file_content, file.filename, file.content_type or "application/octet-stream"))

    return JSONResponse({"job_id": job_id})


@app.get("/progress/{job_id}")
async def get_progress(job_id: str):
    job = upload_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(job)


@app.get("/download/{short_id}")
async def download_file(short_id: str):
    db = load_db()
    entry = db.get(short_id)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        client = await get_client()
        message = await client.get_messages(entry["channel_id"], ids=entry["message_id"])
        if not message or not message.document:
            raise HTTPException(status_code=404, detail="File not found in Telegram")

        document = message.document

        # Stream directly chunk by chunk — no temp file, instant start!
        async def stream_from_telegram():
            async for chunk in client.iter_download(
                document,
                request_size=1024 * 1024,  # 1MB chunks
            ):
                yield chunk

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download error: {str(e)}")

    headers = {
        "Content-Disposition": f'attachment; filename="{entry["filename"]}"',
        "Content-Type": entry["content_type"],
        "Content-Length": str(entry["size"]),
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
    }
    return StreamingResponse(stream_from_telegram(), headers=headers, media_type=entry["content_type"])

@app.get("/files")
async def list_files():
    db = load_db()
    files = [
        {
            "short_id": sid,
            "filename": e["filename"],
            "size": format_size(e["size"]),
            "download_link": f"{BASE_URL}/download/{sid}"
        }
        for sid, e in db.items()
    ]
    return {"files": files, "total": len(files)}


@app.get("/info/{short_id}")
async def file_info(short_id: str):
    db = load_db()
    entry = db.get(short_id)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")
    return {
        "filename": entry["filename"],
        "size": format_size(entry["size"]),
        "content_type": entry["content_type"],
        "download_link": f"{BASE_URL}/download/{short_id}"
    }
