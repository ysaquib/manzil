# syntax=docker/dockerfile:1.7
# Production API/worker image. Render runs its FastAPI or standalone worker
# command from this same image; Build context = monorepo root. ONNX archive is
# fetched at build time via BuildKit secret id=manzil_clip_archive_url (never
# ARG or env var).
FROM python:3.12-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.11.13

COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/pyproject.toml
COPY api/pyproject.toml api/pyproject.toml
COPY worker/pyproject.toml worker/pyproject.toml

RUN uv sync --frozen --package manzil-api --extra vision-onnx --no-dev --no-install-workspace

COPY shared/src shared/src
COPY worker/src worker/src
COPY api/src api/src
COPY worker/prompts/vision_refs worker/prompts/vision_refs
# Product SemVer — `manzil_api.build_info.release_version()` reads /app/VERSION.
COPY VERSION VERSION

RUN uv sync --frozen --package manzil-api --extra vision-onnx --no-dev

RUN --mount=type=secret,id=manzil_clip_archive_url,required=true \
    set -eu; \
    archive_url="$(cat /run/secrets/manzil_clip_archive_url)"; \
    if [ -z "$(printf '%s' "$archive_url" | tr -d '[:space:]')" ]; then \
      echo >&2 'BuildKit secret manzil_clip_archive_url is blank; provide the authenticated HTTPS URL for the pinned CLIP ONNX archive'; \
      exit 1; \
    fi; \
    mkdir -p .manzil/models/clip-vision-uint8; \
    curl --proto '=https' --tlsv1.2 --fail --location --retry 5 \
      "$archive_url" -o /tmp/manzil-clip-vision-uint8.tar.gz; \
    tar -xzf /tmp/manzil-clip-vision-uint8.tar.gz \
      -C .manzil/models/clip-vision-uint8 \
      --no-same-owner --no-same-permissions; \
    uv run --no-sync --package manzil-api python -c \
      'from pathlib import Path; from manzil_worker.vision_onnx import artifact_digest, ONNX_SHADOW_ARTIFACT_SHA256; actual=artifact_digest(Path(".manzil/models/clip-vision-uint8")); assert actual == ONNX_SHADOW_ARTIFACT_SHA256, f"ONNX artifact digest mismatch: {actual}"'; \
    rm -f /tmp/manzil-clip-vision-uint8.tar.gz


FROM python:3.12-slim AS runtime

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/shared/src /app/shared/src
COPY --from=builder /app/worker/src /app/worker/src
COPY --from=builder /app/api/src /app/api/src
COPY --from=builder /app/worker/prompts/vision_refs /app/worker/prompts/vision_refs
COPY --from=builder /app/VERSION /app/VERSION
COPY --from=builder /app/.manzil/models/clip-vision-uint8 /app/.manzil/models/clip-vision-uint8

RUN /app/.venv/bin/playwright install-deps chromium \
    && /app/.venv/bin/playwright install chromium \
    && rm -rf /var/lib/apt/lists/*

ENV MANZIL_IMAGE_CLASSIFY_ONNX_DIR=/app/.manzil/models/clip-vision-uint8 \
    MANZIL_WORKER_INPROCESS=true \
    PYTHONUNBUFFERED=1

CMD ["/bin/sh", "-c", "/app/.venv/bin/uvicorn manzil_api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
