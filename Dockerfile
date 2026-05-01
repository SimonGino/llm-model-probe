# Stage 1: build frontend
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: backend + static files
FROM python:3.11-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev
COPY --from=frontend /app/frontend/dist ./frontend/dist
ENV LLM_MODEL_PROBE_HOME=/data
ENV LLM_MODEL_PROBE_DIST=/app/frontend/dist
EXPOSE 8765
CMD ["uv", "run", "uvicorn", "llm_model_probe.api:app", "--host", "0.0.0.0", "--port", "8765"]
