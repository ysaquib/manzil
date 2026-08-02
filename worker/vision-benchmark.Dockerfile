FROM python:3.12-slim

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.13

COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/pyproject.toml
COPY api/pyproject.toml api/pyproject.toml
COPY worker/pyproject.toml worker/pyproject.toml

RUN uv sync --frozen --package manzil-worker --extra vision-bench --no-dev --no-install-workspace

COPY shared/src shared/src
COPY worker/src worker/src

RUN uv sync --frozen --package manzil-worker --extra vision-bench --no-dev

ENTRYPOINT ["/app/.venv/bin/manzil", "vision-ml-bench"]
