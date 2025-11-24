# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Set working directory
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy dependency files first
COPY pyproject.toml uv.lock ./

# Install dependencies
# --no-dev: Production dependencies only
# --frozen: Use exact versions from uv.lock
RUN uv sync --frozen --no-dev --no-install-project

# Copy the application code
COPY app ./app
COPY mcp_config.json .
COPY README.md .

# Install the project itself
RUN uv sync --frozen --no-dev

# Expose the port
EXPOSE 8000

# Run the application
# We use 'uv run' to ensure it runs in the virtual environment
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
