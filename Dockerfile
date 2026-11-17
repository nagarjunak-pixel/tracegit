FROM node:22-bookworm-slim AS ui-builder
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends clang && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.6.6 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY csrc ./csrc
COPY src ./src
COPY benchmarks ./benchmarks
COPY --from=ui-builder /ui/dist ./ui/dist

RUN uv sync --python 3.13 --frozen --no-dev

EXPOSE 8100
CMD ["uv", "run", "--no-dev", "tracegit", "serve", "--host", "0.0.0.0", "--port", "8100"]
