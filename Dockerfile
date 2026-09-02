FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PATH="/app/.venv/bin:$PATH"

# Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    make \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Astral uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set working directory
WORKDIR /app

# Copy dependency specifications first for Docker layer caching
COPY pyproject.toml uv.lock* .python-version* ./

# Install project dependencies
RUN uv sync --frozen --no-install-project || uv sync --no-install-project

# Install Playwright browser binaries and system dependencies
RUN uv run playwright install --with-deps chromium

# Copy application source code (filtered by .dockerignore)
COPY . .

# Finalize project installation
RUN uv sync --frozen || uv sync

# Ensure runtime storage directory exists
RUN mkdir -p storage

# Run main application entrypoint
CMD ["python", "main.py"]

