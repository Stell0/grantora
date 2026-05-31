FROM python:3.12-alpine3.22

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY containers/grantora-api-entrypoint.sh ./containers/grantora-api-entrypoint.sh

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && chmod +x ./containers/grantora-api-entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/app/containers/grantora-api-entrypoint.sh"]
CMD ["sh", "-c", "python -m uvicorn grantora.main:create_app --factory --host ${GRANTORA_BIND_ADDR:-0.0.0.0} --port ${GRANTORA_PORT:-8080}"]
