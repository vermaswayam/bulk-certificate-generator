FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/certificates.db \
    STORAGE_DIR=/data/storage

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# run as a non-root user; /data holds the database and generated PDFs
RUN useradd --create-home appuser && mkdir -p /data && chown appuser /data
USER appuser
VOLUME /data

EXPOSE 8000
# hosting platforms like Render pass the port in $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
