FROM python:3.12-alpine3.22

ARG GRANTORA_VERSION=0.1.0
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="Grantora API" \
    org.opencontainers.image.description="Standalone capability gateway for agents" \
    org.opencontainers.image.version="${GRANTORA_VERSION}" \
    org.opencontainers.image.revision="${VCS_REF}" \
    org.opencontainers.image.created="${BUILD_DATE}" \
    org.opencontainers.image.source="https://github.com/grantora/grantora"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GRANTORA_IMAGE_VERSION=${GRANTORA_VERSION}

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY containers/grantora-api-entrypoint.sh ./containers/grantora-api-entrypoint.sh

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && chmod +x ./containers/grantora-api-entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/app/containers/grantora-api-entrypoint.sh"]
CMD ["sh", "-c", "python -m uvicorn grantora.main:create_app --factory --host ${GRANTORA_BIND_ADDR:-0.0.0.0} --port ${GRANTORA_PORT:-8080}"]
