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
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession

LOG_FILE = "/tmp/telestore.log"

# Force all output to stderr so Coolify Logs tab shows everything
sys.stdout = sys.stderr

def log(msg):
    import datetime
    line = f"{datetime.datetime.now().strftime('%H:%M:%S')} | {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
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


async def do_upload(job_id: str, tmp_path: str, filename: str, content_type: str):
    file_size = os.path.getsize(tmp_path)
    mb_total = file_size / (1024 * 1024)

    try:
        upload_jobs[job_id].update({"percent": 5, "status": f"Connecting to Telegram..."})
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

            tg_status = f"{mb_done:.1f} / {mb_total:.1f} MB"
            
            # Progress sirf har 0.5 sec me update ho raha hai (optimized)
            upload_jobs[job_id].update({
                "percent": pct,
                "status": "Uploading to Telegram...",
                "telegram_pct": pct,
                "telegram_status": tg_status,
                "telegram_speed": speed_str,
                "telegram_eta": eta_str
            })

        message = await client.send_file(
            CHANNEL_ID,
            tmp_path,
            caption=f"📁 {filename}\n💾 {format_size(file_size)}",
            force_document=True,
            progress_callback=progress_callback,
            workers=16,
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

        upload_jobs[job_id].update({
            "percent": 100,
            "status": "Upload complete!",
            "server_pct": 100,
            "server_status": f"{mb_total:.1f} MB ✓",
            "server_speed": "",
            "server_eta": "",
            "telegram_pct": 100,
            "telegram_status": f"{mb_total:.1f} MB ✓",
            "telegram_speed": "",
            "telegram_eta": "",
            "done": True,
            "error": None,
            "result": {
                "success": True,
                "filename": filename,
                "size": format_size(file_size),
                "download_link": f"{BASE_URL}/download/{short_id}",
                "short_id": short_id
            }
        })

    except Exception as e:
        log(f"❌ UPLOAD ERROR | {str(e)}")
        upload_jobs[job_id].update({"percent": 0, "status": "Failed", "done": True, "error": str(e)})
    finally:
        # Ye line ensure karti hai ki upload hone ya fail hone ke baad file SSD se hamesha delete ho jaye
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
            log(f"🗑️ Cleaned up temporary file: {tmp_path}")


@app.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    if not BOT_TOKEN or not API_ID or not API_HASH or not CHANNEL_ID:
        raise HTTPException(status_code=500, detail="Missing config")

    job_id = str(uuid.uuid4())[:12]
    filename = file.filename
    content_type = file.content_type or "application/octet-stream"
    suffix = Path(filename).suffix or ".bin"
    
    content_length = request.headers.get("content-length", "0")
    total_size = int(content_length) if content_length.isdigit() else 0

    mb_total_declared = total_size / (1024 * 1024) if total_size > 0 else 0
    upload_jobs[job_id] = {
        "percent": 0,
        "status": "Receiving...",
        "server_pct": 1,
        "server_status": f"0.0 / {mb_total_declared:.1f} MB",
        "server_speed": "",
        "server_eta": "",
        "telegram_pct": 0,
        "telegram_status": "Waiting...",
        "telegram_speed": "",
        "telegram_eta": "",
        "done": False,
        "error": None
    }

    log(f"⬆️  RECEIVE START | {filename} | {mb_total_declared:.1f}MB")

    t_recv_start = time.time()
    received = 0
    last_update_time = t_recv_start
    last_update_bytes = 0
    CHUNK_SIZE = 64 * 1024  # 64KB

    # File ko RAM ke bajaye direct SSD par temp file me save kar rahe hain
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = tmp.name

    try:
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break
            
            tmp.write(chunk)
            received += len(chunk)

            now = time.time()
            elapsed = now - last_update_time

            if elapsed >= 0.5:
                recv_speed = (received - last_update_bytes) / elapsed / (1024 * 1024)
                last_update_time = now
                last_update_bytes = received

                if total_size > 0:
                    pct = min(99, max(1, int((received / total_size) * 100)))
                else:
                    pct = min(99, max(1, int((received / (1024*1024)) * 10)))

                mb_done = received / (1024 * 1024)
                mb_total = total_size / (1024 * 1024) if total_size > 0 else mb_done
                eta = ((total_size - received) / (1024 * 1024)) / recv_speed if (recv_speed > 0 and total_size > 0) else 0
                eta_str = f"~{int(eta)}s" if 0 < eta < 60 else (f"~{int(eta/60)}m" if eta >= 60 else "")

                upload_jobs[job_id].update({
                    "server_pct": pct,
                    "server_status": f"{mb_done:.1f} / {mb_total:.1f} MB",
                    "server_speed": f"⚡ {recv_speed:.1f} MB/s" if recv_speed > 0.01 else "",
                    "server_eta": eta_str
                })
    finally:
        tmp.close()

    file_size = os.path.getsize(tmp_path)
    recv_time = time.time() - t_recv_start
    recv_speed_avg = file_size / recv_time / (1024*1024) if recv_time > 0 else 0

    log(f"📥 RECEIVE DONE | {file_size/(1024*1024):.1f}MB | {recv_time:.1f}s | avg {recv_speed_avg:.1f} MB/s")

    if file_size > 2 * 1024 * 1024 * 1024:
        os.unlink(tmp_path)
        raise HTTPException(status_code=400, detail="File too large. Max 2GB.")

    mb_size = file_size / (1024 * 1024)
    upload_jobs[job_id].update({
        "status": "Uploading to Telegram...",
        "server_pct": 100,
        "server_status": f"{mb_size:.1f} MB ✓",
        "server_speed": f"avg {recv_speed_avg:.1f} MB/s",
        "server_eta": "",
        "telegram_pct": 1,
        "telegram_status": "Connecting to Telegram...",
        "telegram_speed": "",
        "telegram_eta": "",
    })

    # Background me Telegram upload start karna
    asyncio.create_task(do_upload(job_id, tmp_path, filename, content_type))
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

        # Stream directly — no temp file, instant start!
        async def stream_from_telegram():
            bytes_sent = 0
            async for chunk in client.iter_download(
                document,
                request_size=2 * 1024 * 1024,  # 2MB chunks — max speed
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

    filename_safe = entry["filename"].replace('"', '\"')

    return StreamingResponse(
        stream_from_telegram(),
        headers={
            "Content-Disposition": f'attachment; filename="{filename_safe}"',
            "Content-Type": entry["content_type"],
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
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
