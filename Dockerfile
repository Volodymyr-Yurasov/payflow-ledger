FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv
RUN useradd --create-home --uid 1000 app && chown app:app /srv

COPY requirements.txt .
RUN pip install -r requirements.txt


# Test image: dev dependencies + test suite (docker compose --profile test run --rm tests)
FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY --chown=app:app . .
USER app
CMD ["pytest", "--cov=app", "--cov-report=term-missing", "--cov-fail-under=90"]


# Runtime image (default target): migrate, then serve on :8000
FROM base AS runtime
COPY --chown=app:app . .
USER app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec gunicorn -c gunicorn.conf.py 'app:create_app()'"]
