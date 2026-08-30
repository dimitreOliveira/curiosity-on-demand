FROM python:3.12-slim

# Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install Astral uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set working directory
WORKDIR /app

# Copy dependency specifications first for Docker layer caching
COPY pyproject.toml uv.lock* .python-version* ./

# Install project dependencies
RUN uv sync --frozen --no-install-project || uv sync --no-install-project

# Copy application source code (filtered by .dockerignore)
COPY . .

# Finalize project installation
RUN uv sync --frozen || uv sync

# Ensure runtime storage directory exists
RUN mkdir -p storage

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

# Run main application entrypoint
CMD ["python", "main.py"]
