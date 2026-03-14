FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend
COPY backend/ ./backend/

# Copy frontend
COPY frontend/ ./frontend/

RUN pip install --no-cache-dir aiofiles

EXPOSE 9500

# IMPORTANT: flush logs immediately
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV BOT_TOKEN=""
ENV CHANNEL_ID=""
ENV BASE_URL="http://localhost:9500"
ENV PORT=9500

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-9500} --log-level info"]
