# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/playwright/python:v1.65.2-noble
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    novnc x11vnc openbox tini x11-utils xvfb python3-venv \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY browser_worker/requirements.txt ./browser_worker/requirements.txt
RUN python -m venv /opt/worker
ENV PATH="/opt/worker/bin:$PATH"
RUN pip install --no-cache-dir -r browser_worker/requirements.txt
COPY browser_worker ./browser_worker
RUN mkdir -p /profile /run/campfinder && chown pwuser:pwuser /profile /run/campfinder
USER pwuser
ENV DISPLAY=:99 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
VOLUME ["/profile"]
EXPOSE 6080
HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=3 \
    CMD ["python", "-m", "browser_worker.control", "health"]
ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "browser_worker"]
