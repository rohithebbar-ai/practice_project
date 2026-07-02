# Dockerfile
# ───────────
# Cloud Run requires the container to listen on the port given by the
# PORT env var (Cloud Run sets this automatically at runtime — default
# 8080). Do NOT hardcode a different port.

FROM python:3.11-slim

WORKDIR /app

# System deps only if you actually need them (e.g. for PDF/OCR libs
# used by document_parser.py — tesseract, poppler-utils). Remove if
# not needed to keep the image small and builds fast.
# RUN apt-get update && apt-get install -y \
#     tesseract-ocr \
#     poppler-utils \
#     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects PORT at runtime; default to 8080 for local docker run
ENV PORT=8080

CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
