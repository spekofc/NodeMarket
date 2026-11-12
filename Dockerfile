# NodeMarket — production-ready, zero-JS, privacy-first.
# Build:  docker build -t nodemarket .
# Run:    docker run -p 8000:8000 -v nodemarket-data:/app/data nodemarket

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libpq-less build: requirements are pure Python (pgpy, fastapi, uvicorn…),
# so no OS packages are needed beyond the base image.
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py ./run.py
COPY static ./static

# Non-root: the process cannot write outside /app/data.
RUN useradd --system --create-home --shell /usr/sbin/nologin nodemarket \
    && mkdir -p /app/data \
    && chown -R nodemarket:nodemarket /app/data

USER nodemarket

# SQLite database and any future persistent state live here.
VOLUME ["/app/data"]

EXPOSE 8000

# Bind 0.0.0.0 inside the container; publish only to loopback or a
# TLS/onion frontend on the host (see README "Transport security").
CMD ["python", "run.py"]
