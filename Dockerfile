FROM python:3.12-slim

# Install system dependencies: FFmpeg, Cairo, Pango, and build essentials
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libcairo2 \
    libcairo2-dev \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    pkg-config \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Astral uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml .python-version ./

# Install dependencies using uv sync
RUN uv sync --frozen --no-dev || uv sync

# Copy application source code
COPY . .

# Ensure storage directory exists
RUN mkdir -p storage/media

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

# Run main application
CMD ["python", "main.py"]
