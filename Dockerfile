# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# Install git (required for gitops worktree operations)
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY core/ ./core/
COPY web/ ./web/

RUN pip install --no-cache-dir ./core/

# Single worker is REQUIRED: workers 1. Engine state is in-process.
ENV NEXUSSY_ENV=production
EXPOSE 7771

CMD ["uvicorn", "nexussy.api.server:app", "--host", "0.0.0.0", "--port", "7771", "--workers", "1"]
