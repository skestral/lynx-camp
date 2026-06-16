# syntax=docker/dockerfile:1

ARG NODE_VERSION=22-alpine
ARG PYTHON_VERSION=3.12-slim
FROM node:${NODE_VERSION} AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:${PYTHON_VERSION} AS runtime
ARG APP_GIT_SHA=unknown

LABEL org.opencontainers.image.title="Lynx Camp" \
    org.opencontainers.image.description="Local-network Recreation.gov campground availability monitor" \
    org.opencontainers.image.source="https://github.com/skestral/lynx-camp" \
    org.opencontainers.image.revision=${APP_GIT_SHA}

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    APP_GIT_SHA=${APP_GIT_SHA} \
    CAMPFINDER_DB=/data/campfinder.db \
    CAMPFINDER_STATIC_DIR=/app/frontend/dist
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend ./backend
COPY --from=frontend /app/frontend/dist ./frontend/dist
RUN printf "%s\n" "${APP_GIT_SHA}" > /app/BUILD_SHA
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import sys, urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=5); sys.exit(0)"
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
