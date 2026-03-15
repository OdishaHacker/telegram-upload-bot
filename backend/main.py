import os
import uuid
import json
import tempfile
import asyncio
import time
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession

LOG_FILE = "/tmp/telestore.log"

def log(msg):
    import datetime
    line = f"{datetime.datetime.now().strftime('%H:%M:%S')} | {msg}\n"
    sys.stderr.write(line)
    sys.stderr.flush()
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except:
        pass

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
DB_FILE     = "/app/data/files_db.json"

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

async def cleanup_deleted_files():
    while True:
        await asyncio.sleep(30 * 60)
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
                except:
                    pass
            if to_delete:
                for sid in to_delete:
                    del db[sid]
                save_db(db)
        except:
            pass

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
        upload_jobs[job_id].update({"percent": 5, "status": f"Connecting to Telegram..."})

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        t_start = time.time()
        log(f"⬆️  UPLOAD START | {filename} | {mb_total:.1f}MB")
        client = await get_client()

        speed_state = {"current": 0, "last_bytes": 0, "last_time": t_start, "speed": 0}

        def progress_callback(current, total):
            now = time.time()
            elapsed = now - speed_state["last_time"]
            if elapsed >= 0.5:
                diff = current - speed_state["last_bytes"]
                speed_state["speed"] = (diff / elapsed) / (1024 * 1024)
                speed_state["last_bytes"] = current
                speed_state["last_time"] = now
            speed_state["current"] = current

            pct = max(5, min(98, int((current / file_size) * 93) + 5))
            mb_done = current / (1024 * 1024)
            speed = speed_state["speed"]

            if speed > 0:
                remaining = (file_size - current) / (1024 * 1024)
                eta = remaining / speed
                eta_str = f"~{int(eta)}s" if eta < 60 else f"~{int(eta/60)}m {int(eta%60)}s"
                speed_str = f"{speed:.1f} MB/s"
            else:
                eta_str = ""
                speed_str = ""

            status = f"{mb_done:.1f} MB / {mb_total:.1f} MB"
            if speed_str:
                status += f"  ·  ⚡ {speed_str}"
            if eta_str:
                status += f"  ·  {eta_str}"

            log(f"⬆️  {pct}% | {status}")

            upload_jobs[job_id] = {
                "percent": pct,
                "status": status,
                "done": False,
                "error": None
            }

        message = await client.send_file(
            CHANNEL_ID,
            tmp_path,
            caption=f"📁 {filename}\n💾 {format_size(file_size)}",
            force_document=True,
            progress_callback=progress_callback,
            workers=4,
        )

        total_time = time.time() - t_start
        avg_speed = mb_total / total_time if total_time > 0 else 0
        log(f"✅ UPLOAD DONE | {mb_total:.1f}MB | {total_time:.1f}s | avg {avg_speed:.1f} MB/s")

        doc = message.document
        short_id = str(uuid.uuid4())[:8]
        db = load_db()
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
        log(f"❌ UPLOAD ERROR | {str(e)}")
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
    mb = file_size / (1024 * 1024)
    upload_jobs[job_id] = {
        "percent": 2,
        "status": f"File ready ({mb:.1f} MB) — connecting...",
        "done": False,
        "error": None
    }
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
    t_start = time.time()
    log(f"⬇️  DOWNLOAD START | {entry['filename']} | {file_size/(1024*1024):.1f}MB")

    try:
        client = await get_client()
        message = await client.get_messages(entry["channel_id"], ids=entry["message_id"])

        if not message or not message.document:
            db = load_db()
            if short_id in db:
                del db[short_id]
                save_db(db)
            raise HTTPException(status_code=404, detail="File deleted from Telegram")

        document = message.document
        log(f"🚀 Streaming starts | {time.time()-t_start:.2f}s after tap")

        async def stream_from_telegram():
            bytes_sent = 0
            async for chunk in client.iter_download(
                document,
                request_size=512 * 1024,  # 512KB chunks — balanced speed
            ):
                data = bytes(chunk)
                bytes_sent += len(data)
                yield data
            log(f"✅ DOWNLOAD DONE | {bytes_sent/(1024*1024):.1f}MB | {time.time()-t_start:.1f}s")

    except HTTPException:
        raise
    except Exception as e:
        log(f"❌ DOWNLOAD ERROR | {str(e)}")
        raise HTTPException(status_code=500, detail=f"Download error: {str(e)}")

    return StreamingResponse(
        stream_from_telegram(),
        headers={
            "Content-Disposition": f'attachment; filename="{entry["filename"]}"',
            "Content-Type": entry["content_type"],
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        },
        media_type=entry["content_type"]
    )


@app.get("/sync")
async def sync_files():
    try:
        db = load_db()
        if not db:
            return {"removed": 0, "remaining": 0}
        client = await get_client()
        to_delete = []
        for short_id, entry in db.items():
            try:
                msg = await client.get_messages(entry["channel_id"], ids=entry["message_id"])
                if not msg or not msg.document:
                    to_delete.append(short_id)
            except:
                to_delete.append(short_id)
        for sid in to_delete:
            del db[sid]
        if to_delete:
            save_db(db)
        return {"removed": len(to_delete), "remaining": len(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
