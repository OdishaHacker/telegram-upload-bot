import os
import uuid
import json
import tempfile
import asyncio
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import httpx
import time

import sys
LOG_FILE = "/app/telestore.log"

def log(msg):
    import datetime
    line = f"{datetime.datetime.now().strftime('%H:%M:%S')} | {msg}\n"
    sys.stderr.write(line)
    sys.stderr.flush()
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except:
        pass
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
        _client = TelegramClient(session, API_ID, API_HASH, connection_retries=5)
        await _client.start(bot_token=BOT_TOKEN)
    return _client

async def cleanup_deleted_files():
    """Background task — checks every 30 min if files still exist in Telegram"""
    while True:
        await asyncio.sleep(30 * 60)  # 30 minutes
        try:
            db = load_db()
            if not db:
                continue
            client = await get_client()
            to_delete = []
            for short_id, entry in db.items():
                try:
                    message = await client.get_messages(entry["channel_id"], ids=entry["message_id"])
                    if not message or not message.document:
                        to_delete.append(short_id)
                except Exception:
                    pass
            if to_delete:
                for sid in to_delete:
                    del db[sid]
                save_db(db)
        except Exception:
            pass


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


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_deleted_files())


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
        t_upload_start = time.time()
        log(f"⬆️  UPLOAD START | file={filename} | size={mb_total:.1f}MB")
        client = await get_client()
        log(f"✅ Telegram client ready for upload")
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
            workers=4,
        )

        log(f"✅ UPLOAD TO TELEGRAM DONE | {mb_total:.1f}MB | time={time.time()-t_upload_start:.2f}s")
        upload_jobs[job_id] = {"percent": 97, "status": "Saving link...", "done": False, "error": None}

        # Save file_id for bot API direct download (small files)
        doc = message.document
        file_id_str = str(doc.id) if doc else ""

        short_id = str(uuid.uuid4())[:8]
        db = load_db()

        # Save full document info — avoids message fetch on download
        doc = message.document
        db[short_id] = {
            "message_id": message.id,
            "filename": filename,
            "size": file_size,
            "content_type": content_type,
            "channel_id": CHANNEL_ID,
            "doc_id": doc.id if doc else None,
            "access_hash": doc.access_hash if doc else None,
            "file_reference": doc.file_reference.hex() if doc else None,
            "dc_id": doc.dc_id if doc else None,
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
    if len(file_content) > 2 * 1024 * 1024 * 1024:
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

    file_size = entry["size"]

    # Small files (≤19MB) — use Bot API direct URL redirect (instant!)
    if file_size <= 19 * 1024 * 1024:
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                # First get the file_id via bot API using message forward
                client = await get_client()
                message = await client.get_messages(entry["channel_id"], ids=entry["message_id"])
                if message and message.document:
                    # Get bot API file_id
                    from telethon.tl.types import DocumentAttributeFilename
                    doc = message.document
                    # Use bot token to get direct URL
                    resp = await http.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
                        json={"file_id": f"BQACAgIAAxk{doc.access_hash}"}
                    )
        except Exception:
            pass

    file_size_mb = entry["size"] / (1024 * 1024)
    log(f"⬇️  DOWNLOAD START | file={entry['filename']} | size={file_size_mb:.1f}MB | id={short_id}")
    t_start = time.time()

    try:
        client = await get_client()
        log(f"✅ Telegram client ready | {time.time()-t_start:.2f}s elapsed")

        # Try fast path: use saved document info (no message fetch needed!)
        if entry.get("doc_id") and entry.get("access_hash") and entry.get("file_reference"):
            from telethon.tl.types import InputDocumentFileLocation
            from telethon.tl.types import Document

            document = Document(
                id=entry["doc_id"],
                access_hash=entry["access_hash"],
                file_reference=bytes.fromhex(entry["file_reference"]),
                date=0,
                mime_type=entry["content_type"],
                size=entry["size"],
                thumbs=None,
                video_thumbs=None,
                dc_id=entry.get("dc_id", 1),
                attributes=[],
            )
        else:
            # Fallback: fetch message (older entries without doc info)
            log(f"🔄 Slow path: fetching message from Telegram...")
            t_fetch = time.time()
            message = await client.get_messages(entry["channel_id"], ids=entry["message_id"])
            log(f"📨 Message fetched in {time.time()-t_fetch:.2f}s")
            if not message or not message.document:
                raise HTTPException(status_code=404, detail="File not found in Telegram")
            document = message.document

        log(f"🚀 Streaming to user starts NOW | {time.time()-t_start:.2f}s after tap")

        chunk_count = [0]
        bytes_sent = [0]

        async def stream_from_telegram():
            async for chunk in client.iter_download(
                document,
                request_size=1024 * 1024,
            ):
                chunk_count[0] += 1
                bytes_sent[0] += len(chunk)
                if chunk_count[0] == 1:
                    log(f"📦 First chunk sent to user | {time.time()-t_start:.2f}s after tap")
                if chunk_count[0] % 50 == 0:
                    mb_sent = bytes_sent[0] / (1024*1024)
                    log(f"📊 Progress: {mb_sent:.1f}MB / {file_size_mb:.1f}MB sent")
                yield chunk
            log(f"✅ DOWNLOAD COMPLETE | {file_size_mb:.1f}MB | total time={time.time()-t_start:.2f}s")

    except Exception as e:
        log(f"[ERROR] " + f"❌ DOWNLOAD ERROR | {str(e)}")
        raise HTTPException(status_code=500, detail=f"Download error: {str(e)}")

    headers = {
        "Content-Disposition": f'attachment; filename="{entry["filename"]}"',
        "Content-Type": entry["content_type"],
        "Content-Length": str(file_size),
        "Accept-Ranges": "bytes",
    }
    return StreamingResponse(
        stream_from_telegram(),
        headers=headers,
        media_type=entry["content_type"]
    )


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
