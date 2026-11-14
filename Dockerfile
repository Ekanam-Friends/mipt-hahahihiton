FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    REGNAV_DATA=/app/data/official REGNAV_LLM=extractive REGNAV_LOCAL_ONLY=1 \
    TESSDATA_DIR=/usr/share/tesseract-ocr/5/tessdata
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-web.txt constraints-web.txt ./
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir -r requirements-web.txt -c constraints-web.txt
COPY regnav ./regnav
RUN chmod -R a=rX /app/regnav && useradd --create-home --uid 10001 regnav && mkdir -p /app/data/official /app/state && chown -R regnav:regnav /app/data /app/state
USER regnav
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["python", "-m", "uvicorn", "regnav.web.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
