# Director Studio for Unraid.
# ComfyUI and Ollama stay on the host; this image is the FastAPI + UI orchestrator.
FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci
COPY src/frontend/ ./
RUN npm run build

FROM node:22-bookworm-slim AS harness
WORKDIR /build/harness
COPY src/harness/package.json src/harness/package-lock.json ./
RUN npm ci
COPY src/harness/ ./
RUN npm run build && npm prune --omit=dev

FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        curl \
        git \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY src/backend/requirements.txt /tmp/requirements.txt
RUN grep -vE '^(pytest|pytest-asyncio)' /tmp/requirements.txt > /tmp/requirements.prod.txt \
    && pip install --no-cache-dir -r /tmp/requirements.prod.txt python-dotenv \
    && rm /tmp/requirements.txt /tmp/requirements.prod.txt

COPY src/backend /app/backend
COPY --from=frontend /build/frontend/dist /app/frontend/dist
COPY --from=harness /build/harness/dist /app/harness/dist
COPY --from=harness /build/harness/node_modules /app/harness/node_modules
COPY --from=harness /build/harness/package.json /app/harness/package.json
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && mkdir -p /data

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DS_HOST=0.0.0.0 \
    DS_PORT=8790 \
    DS_DATA_DIR=/data \
    DS_COMFY_BASE_URL=http://127.0.0.1:8188 \
    DS_OLLAMA_BASE_URL=http://127.0.0.1:11434 \
    DS_LLM_PROVIDER=ollama \
    DS_DIRECTOR_AGENT_RUNTIME=legacy \
    DS_H3_PROVIDER=local

EXPOSE 8790
VOLUME ["/data"]
ENTRYPOINT ["/entrypoint.sh"]
