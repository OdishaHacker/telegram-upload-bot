import os
import uuid
import json
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx

app = FastAPI(title="Telegram File Storage API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
DB_FILE = "files_db.json"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def load_db():
    if not Path(DB_FILE).exists():
        return {}
    with open(DB_FILE, "r") as f:
        return json.load(f)


def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)


@app.get("/", response_class=HTMLResponse)
async def root():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text())
    return HTMLResponse(content="<h1>TeleStore API Running</h1>")


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not BOT_TOKEN or not CHANNEL_ID:
        raise HTTPException(status_code=500, detail="BOT_TOKEN or CHANNEL_ID not configured")

    file_content = await file.read()
    file_size = len(file_content)

    if file_size > 2 * 1024 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max 2GB allowed.")

    async with httpx.AsyncClient(timeout=300) as client:
        files_data = {"document": (file.filename, file_content, file.content_type or "application/octet-stream")}
        post_data = {
            "chat_id": CHANNEL_ID,
            "caption": f"📁 {file.filename}\n💾 {format_size(file_size)}"
        }
        resp = await client.post(f"{TELEGRAM_API}/sendDocument", files=files_data, data=post_data)
        result = resp.json()

        if not result.get("ok"):
            raise HTTPException(status_code=500, detail=f"Telegram error: {result.get('description')}")

    message = result["result"]
    doc = (
        message.get("document")
        or message.get("video")
        or message.get("audio")
        or message.get("animation")
    )
    if not doc:
        photo = message.get("photo")
        doc = photo[-1] if photo else None

    if not doc:
        raise HTTPException(status_code=500, detail="Could not extract file from Telegram response")

    short_id = str(uuid.uuid4())[:8]
    db = load_db()
    db[short_id] = {
        "file_id": doc["file_id"],
        "file_unique_id": doc["file_unique_id"],
        "filename": file.filename,
        "size": file_size,
        "content_type": file.content_type or "application/octet-stream",
        "message_id": message["message_id"]
    }
    save_db(db)

    return {
        "success": True,
        "filename": file.filename,
        "size": format_size(file_size),
        "download_link": f"{BASE_URL}/download/{short_id}",
        "short_id": short_id
    }


@app.get("/download/{short_id}")
async def download_file(short_id: str):
    db = load_db()
    entry = db.get(short_id)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(f"{TELEGRAM_API}/getFile", params={"file_id": entry["file_id"]})
        result = resp.json()
        if not result.get("ok"):
            raise HTTPException(status_code=500, detail="Could not retrieve file from Telegram")

        file_path = result["result"]["file_path"]
        file_resp = await client.get(f"{TELEGRAM_FILE_API}/{file_path}")

    async def stream_content():
        yield file_resp.content

    headers = {
        "Content-Disposition": f'attachment; filename="{entry["filename"]}"',
        "Content-Type": entry["content_type"],
        "Content-Length": str(entry["size"])
    }
    return StreamingResponse(stream_content(), headers=headers, media_type=entry["content_type"])


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


def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"
