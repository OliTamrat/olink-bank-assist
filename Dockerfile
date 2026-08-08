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
#
# --proxy-headers is not optional here. Cloud Run terminates TLS and forwards
# over plain HTTP, so without it request.client.host is Google's front-end
# address rather than the caller's, and every request in production appears to
# come from the same IP. That silently turns the per-client-IP rate limiting
# on admin auth into a single global counter — one attacker would throttle
# every real operator, and the property the tests assert would simply be false
# where it matters.
#
# --forwarded-allow-ips="*" trusts whatever peer connects. That is correct
# ONLY because the container is not reachable except through Cloud Run's
# ingress; exposing this port directly would let a caller spoof its own
# X-Forwarded-For and defeat the same rate limiting.
CMD ["sh", "-c", "uvicorn bankassist.api:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
