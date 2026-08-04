FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
COPY bankassist ./bankassist
COPY migrations ./migrations
COPY alembic.ini ./

RUN pip install . && useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Cloud Run / ECS discipline: uvicorn binds the PORT the platform provides
# (default 8000 — deploy with a matching --port or the TCP probe fails).
CMD ["sh", "-c", "uvicorn bankassist.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
