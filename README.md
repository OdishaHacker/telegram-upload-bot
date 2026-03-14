# 📡 TeleStore — Telegram-Powered File Upload & Share

Upload any file (up to 2GB) via a web interface. Files are stored in a private Telegram channel. Share via instant download links.

---

## 🚀 Quick Setup

### Step 1 — Create Telegram Bot

1. Open Telegram, search **@BotFather**
2. Send `/newbot`
3. Give it a name & username
4. Copy the **Bot Token** → looks like `1234567890:ABCdef...`

### Step 2 — Create Private Channel

1. Create a new **Private Channel** in Telegram
2. Add your bot as **Administrator** (with "Post Messages" permission)
3. Get Channel ID:
   - Forward any message from the channel to **@userinfobot**
   - Or send a message and check: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Channel ID starts with `-100...`

### Step 3 — Configure Environment

```bash
cp .env.example .env
# Edit .env and fill in your BOT_TOKEN, CHANNEL_ID, BASE_URL
```

### Step 4 — Run Locally

```bash
# Install dependencies
pip install -r backend/requirements.txt

# Run server
BOT_TOKEN=your_token CHANNEL_ID=your_channel_id BASE_URL=http://localhost:8000 \
  uvicorn backend.main:app --reload --port 8000
```

Open `http://localhost:8000` in your browser ✅

---

## 🐳 Docker

```bash
docker-compose up -d
```

---

## ☁️ Deploy on Coolify

1. Push this repo to **GitHub**
2. In Coolify: **New Resource → Application → GitHub repo**
3. Set **Build Pack**: Dockerfile
4. Add **Environment Variables**:
   ```
   BOT_TOKEN = your_bot_token
   CHANNEL_ID = your_channel_id
   BASE_URL = https://your-coolify-domain.com
   ```
5. Deploy! 🎉

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Frontend UI |
| `POST` | `/upload` | Upload a file |
| `GET` | `/download/{id}` | Download a file |
| `GET` | `/files` | List all files |
| `GET` | `/info/{id}` | File metadata |

---

## ⚠️ Notes

- **Max file size**: 2GB (Telegram standard) / 4GB (Telegram Premium)
- **Storage**: Unlimited (Telegram channel)
- **Files DB**: Stored locally in `files_db.json` — back it up!
- For production, replace `files_db.json` with a real database (SQLite/PostgreSQL)
