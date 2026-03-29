FROM python:3.12-slim

WORKDIR /app

# System deps for gitpython
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Copy source + project metadata
COPY pyproject.toml README.md ./
COPY src/ src/

# Install
RUN pip install --no-cache-dir .

# Default: run the agent
CMD ["python", "-m", "commandclaw"]
