FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    OMP_NUM_THREADS=1 \
    COD_GUARD_DATA_DIR=/data \
    COD_GUARD_MODEL_PATH=/app/backend/app/model.pkl \
    COD_GUARD_OFFLINE=1 \
    HF_HUB_OFFLINE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN python backend/app/train_model.py \
    && mkdir -p /data \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /data

USER appuser
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
