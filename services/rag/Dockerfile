FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system aiw && adduser --system --ingroup aiw aiw

COPY pyproject.toml README.md ./
COPY src ./src
COPY sql ./sql

RUN pip install --upgrade pip && pip install ".[dev]"

ENV PYTHONPATH=/app/src
USER aiw

CMD ["python", "-m", "ai_workflow_rag.worker.ingestion_worker"]
