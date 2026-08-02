# Production-shaped memory-test substrate, not a deployment image. It includes
# the API/worker Python runtime but deliberately excludes the generated model
# artifact and Playwright's Chromium binary; both remain external to this test.
FROM python:3.12-slim

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.13

COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/pyproject.toml
COPY api/pyproject.toml api/pyproject.toml
COPY worker/pyproject.toml worker/pyproject.toml

RUN uv sync --frozen --package manzil-api --extra vision-onnx --no-dev --no-install-workspace

COPY shared/src shared/src
COPY worker/src worker/src
COPY api/src api/src

RUN uv sync --frozen --package manzil-api --extra vision-onnx --no-dev

ENTRYPOINT ["/app/.venv/bin/uvicorn", "manzil_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
