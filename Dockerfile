# Lehrer-Dashboard – Laufzeit-Image
# Debian-basiertes python-slim: das gebündelte SQLite hat FTS5 (M1/M5 brauchen das).
FROM python:3.12-slim

# Liberation-Fonts = Arial-metrisch → korrektes Arial im PDF-Export (M6).
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-liberation \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY migrations ./migrations
COPY docs ./docs
COPY web ./web
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Nicht als root laufen; Daten-/Speicherpfade anlegen.
RUN useradd -m -u 1000 app \
 && mkdir -p /data /storage \
 && chown -R app:app /app /data /storage
USER app

ENV DB_PATH=/data/data.db \
    STORAGE_ROOT=/storage \
    UPLOAD_TMP=/storage/.tmp \
    DOCS_DIR=/app/docs \
    COOKIE_SECURE=1 \
    SESSION_TTL_HOURS=168

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
