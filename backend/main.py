import os
import uuid
import json
import tempfile
import asyncio
import time
import sys
import logging
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import httpx
from telethon import TelegramClient
from telethon.sessions import StringSession


# =========================================================
# LOGGING SYSTEM (COOLIFY FRIENDLY)
# =========================================================

LOG_FILE = "/app/telestore.log"

logger = logging.getLogger("telestore")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s",
    "%H:%M:%S"
)

# stdout handler (Coolify logs)
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(formatter)

# file handler
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(formatter)

logger.addHandler(stdout_handler)
logger.addHandler(file_handler)

log = logger.info
log_error = logger.error


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(title="TeleStore API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
API_ID      = int(os.getenv("API_ID", "0"))
API_HASH    = os.getenv("API_HASH", "")
CHANNEL_ID  = int(os.getenv("CHANNEL_ID", "0"))
BASE_URL    = os.getenv("BASE_URL", "http://localhost:9500")
SESSION_STR = os.getenv("SESSION_STRING", "")

DB_FILE = "/app/files_db.json"

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


_client = None
upload_jobs = {}

# =========================================================
# TELEGRAM CLIENT
# =========================================================

async def get_client():
    global _client

    if _client is None or not _client.is_connected():

        log("Connecting Telegram client...")

        session = StringSession(SESSION_STR) if SESSION_STR else StringSession()

        _client = TelegramClient(
            session,
            API_ID,
            API_HASH,
            connection_retries=5
        )

        await _client.start(bot_token=BOT_TOKEN)

        log("Telegram client connected")

    return _client


# =========================================================
# DATABASE
# =========================================================

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

    for unit in ['B','KB','MB','GB']:

        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"

        size_bytes /= 1024

    return f"{size_bytes:.1f} TB"


# =========================================================
# ROOT
# =========================================================

@app.get("/", response_class=HTMLResponse)
async def root():

    index = FRONTEND_DIR / "index.html"

    if index.exists():
        return HTMLResponse(index.read_text())

    return HTMLResponse("<h1>TeleStore Running</h1>")


# =========================================================
# UPLOAD LOGIC
# =========================================================

async def do_upload(job_id, file_content, filename, content_type):

    file_size = len(file_content)
    mb_total = file_size / (1024*1024)

    log(f"UPLOAD START | {filename} | {mb_total:.2f}MB")

    tmp_path = None

    try:

        suffix = Path(filename).suffix or ".bin"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        client = await get_client()

        caption = f"{filename}\n{format_size(file_size)}"

        progress_state = {"current":0}

        def progress_callback(current,total):

            progress_state["current"] = current

            mb_done = current/(1024*1024)

            pct = int((current/file_size)*100)

            upload_jobs[job_id] = {
                "percent": pct,
                "status": f"Uploading {mb_done:.1f}/{mb_total:.1f}MB",
                "done": False,
                "error": None
            }

        message = await client.send_file(
            CHANNEL_ID,
            tmp_path,
            caption=caption,
            force_document=True,
            progress_callback=progress_callback,
            workers=4
        )

        log(f"UPLOAD COMPLETE | {filename}")

        short_id = str(uuid.uuid4())[:8]

        db = load_db()

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
            "status": "Upload complete",
            "done": True,
            "error": None,
            "result":{
                "download_link": f"{BASE_URL}/download/{short_id}",
                "short_id": short_id
            }
        }

    except Exception as e:

        log_error(f"UPLOAD ERROR | {str(e)}")

        upload_jobs[job_id] = {
            "percent":0,
            "status":"Failed",
            "done":True,
            "error":str(e)
        }

    finally:

        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# =========================================================
# UPLOAD API
# =========================================================

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):

    file_content = await file.read()

    job_id = str(uuid.uuid4())[:12]

    upload_jobs[job_id] = {
        "percent":0,
        "status":"Starting",
        "done":False,
        "error":None
    }

    asyncio.create_task(
        do_upload(
            job_id,
            file_content,
            file.filename,
            file.content_type or "application/octet-stream"
        )
    )

    return {"job_id":job_id}


# =========================================================
# PROGRESS API
# =========================================================

@app.get("/progress/{job_id}")
async def progress(job_id:str):

    job = upload_jobs.get(job_id)

    if not job:
        raise HTTPException(404)

    return job


# =========================================================
# DOWNLOAD API
# =========================================================

@app.get("/download/{short_id}")
async def download(short_id:str):

    db = load_db()

    entry = db.get(short_id)

    if not entry:
        raise HTTPException(404)

    log(f"DOWNLOAD START | {entry['filename']}")

    client = await get_client()

    message = await client.get_messages(
        entry["channel_id"],
        ids=entry["message_id"]
    )

    document = message.document

    async def stream():

        async for chunk in client.iter_download(
            document,
            request_size=1024*1024
        ):
            yield chunk

    return StreamingResponse(
        stream(),
        headers={
            "Content-Disposition":f'attachment; filename="{entry["filename"]}"'
        }
    )


# =========================================================
# FILE LIST
# =========================================================

@app.get("/files")
async def files():

    db = load_db()

    return {
        "files":[
            {
                "id":sid,
                "filename":e["filename"],
                "size":format_size(e["size"]),
                "download":f"{BASE_URL}/download/{sid}"
            }
            for sid,e in db.items()
        ]
    }
