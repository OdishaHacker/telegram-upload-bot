FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend
COPY backend/ ./backend/

# Copy frontend into a static folder
COPY frontend/ ./frontend/

# Serve frontend via FastAPI static files
RUN pip install --no-cache-dir aiofiles

EXPOSE 8000

ENV BOT_TOKEN=""
ENV CHANNEL_ID=""
ENV BASE_URL="http://localhost:8000"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
