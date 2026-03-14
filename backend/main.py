import os
import uuid
import json
import tempfile
import asyncio
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
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
DB_FILE     = "files_db.json"

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

_client = None

async def get_client():
    global _client
    if _client is None or not _client.is_connected():
        session = StringSession(SESSION_STR) if SESSION_STR else StringSession()
        _client = TelegramClient(session, API_ID, API_HASH)
        await _client.start(bot_token=BOT_TOKEN)
    return _client

def load_db():
    if not Path(DB_FILE).exists():
        return {}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
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

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not BOT_TOKEN or not API_ID or not API_HASH or not CHANNEL_ID:
        raise HTTPException(status_code=500, detail="Missing config: BOT_TOKEN, API_ID, API_HASH, CHANNEL_ID")

    file_content = await file.read()
    file_size = len(file_content)

    if file_size > 2 * 1024 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max 2GB.")

    suffix = Path(file.filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        client = await get_client()
        caption = f"📁 {file.filename}\n💾 {format_size(file_size)}"
        message = await client.send_file(
            CHANNEL_ID,
            tmp_path,
            caption=caption,
            force_document=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload error: {str(e)}")
    finally:
        os.unlink(tmp_path)

    short_id = str(uuid.uuid4())[:8]
    db = load_db()
    db[short_id] = {
        "message_id": message.id,
        "filename": file.filename,
        "size": file_size,
        "content_type": file.content_type or "application/octet-stream",
        "channel_id": CHANNEL_ID,
    }
    save_db(db)

    return {
        "success": True,
        "filename": file.filename,
        "size": format_size(file_size),
        "download_link": f"{BASE_URL}/download/{short_id}",
        "short_id": short_id
    }


@app.post("/upload-stream")
async def upload_stream(file: UploadFile = File(...)):
    """SSE-based upload with real progress"""
    if not BOT_TOKEN or not API_ID or not API_HASH or not CHANNEL_ID:
        raise HTTPException(status_code=500, detail="Missing configuration")

    file_content = await file.read()
    file_size = len(file_content)
    filename = file.filename
    content_type = file.content_type or "application/octet-stream"

    if file_size > 2 * 1024 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max 2GB.")

    async def event_generator():
        suffix = Path(filename).suffix or ".bin"
        tmp_path = None
        try:
            # Step 1 — Save to disk
            yield f"data: {json.dumps({'type': 'progress', 'percent': 2, 'status': 'Saving file...'})}\n\n"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name

            yield f"data: {json.dumps({'type': 'progress', 'percent': 5, 'status': 'Connecting to Telegram...'})}\n\n"

            client = await get_client()

            # Step 2 — Upload with real progress callback
            last_pct = [5]

            def progress_callback(current, total):
                pct = int((current / total) * 90) + 5  # 5% to 95%
                if pct > last_pct[0]:
                    last_pct[0] = pct

            # Run upload in executor to allow progress updates
            caption = f"📁 {filename}\n💾 {format_size(file_size)}"

            upload_task = asyncio.create_task(
                client.send_file(
                    CHANNEL_ID,
                    tmp_path,
                    caption=caption,
                    force_document=True,
                    progress_callback=progress_callback,
                )
            )

            # Stream progress while uploading
            while not upload_task.done():
                pct = last_pct[0]
                mb_done = (file_size * (pct - 5) / 90) / (1024 * 1024)
                mb_total = file_size / (1024 * 1024)
                status = f"Uploading... {mb_done:.1f} MB / {mb_total:.1f} MB"
                yield f"data: {json.dumps({'type': 'progress', 'percent': pct, 'status': status})}\n\n"
                await asyncio.sleep(0.5)

            message = await upload_task

            yield f"data: {json.dumps({'type': 'progress', 'percent': 97, 'status': 'Saving link...'})}\n\n"

            # Save to DB
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

            download_link = f"{BASE_URL}/download/{short_id}"

            yield f"data: {json.dumps({'type': 'done', 'percent': 100, 'status': 'Upload complete!', 'download_link': download_link, 'filename': filename, 'size': format_size(file_size), 'short_id': short_id})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


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

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        await client.download_media(message, tmp_path)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download error: {str(e)}")

    async def stream_and_cleanup():
        try:
            with open(tmp_path, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    yield chunk
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    headers = {
        "Content-Disposition": f'attachment; filename="{entry["filename"]}"',
        "Content-Type": entry["content_type"],
        "Content-Length": str(entry["size"])
    }
    return StreamingResponse(stream_and_cleanup(), headers=headers, media_type=entry["content_type"])


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
