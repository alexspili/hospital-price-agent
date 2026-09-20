# The page is built with Node, then served by the Python process that owns the database.
# One container, one process, one DuckDB file on a mounted disk (SPEC "Process model").
FROM node:24-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HPA_DB=/data/hpa.duckdb
WORKDIR /app
COPY requirements-lock.txt pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install -r requirements-lock.txt && pip install -e . --no-deps
COPY demo/ ./demo/
COPY --from=web /app/frontend/dist ./frontend/dist

# The scan's own trace is the liveness signal; this only checks the process answers.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

EXPOSE 8000
CMD ["sh", "-c", "hpa --db \"$HPA_DB\" serve --host 0.0.0.0 --port 8000 --url \"${HPA_PUBLIC_URL:-http://127.0.0.1:8000}\""]
