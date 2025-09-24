# Multi-stage build for security and efficiency
FROM python:3.11-bookworm AS builder

# Install uv for modern Python dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set environment variables for non-interactive installs
ENV UV_NO_CACHE=1
ENV UV_COMPILE_BYTECODE=1

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Create virtual environment and install dependencies
RUN set -e && uv sync --frozen --no-dev

# Production stage with minimal attack surface
FROM python:3.11-slim-bookworm AS production

# Create non-root user for security
RUN groupadd --gid 1000 kpiuser && \
    useradd --uid 1000 --gid kpiuser --shell /bin/bash --create-home kpiuser

# Copy virtual environment from builder stage
COPY --from=builder --chown=kpiuser:kpiuser /app/.venv /app/.venv

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=kpiuser:kpiuser . .

# Add virtual environment to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER kpiuser

# Use script entry point defined in pyproject.toml
ENTRYPOINT ["kpicalculator"]