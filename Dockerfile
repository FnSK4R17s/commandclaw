FROM python:3.12-slim

# System deps for git (vault operations) and basic tools
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — agent runs as 'agent', not root
RUN groupadd -r agent && \
    useradd -r -g agent -d /home/agent -m agent

WORKDIR /app

# Install Python package
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .

# Workspace is mounted at /workspace — the agent's vault
# This is the ONLY writable directory the agent should have
VOLUME /workspace

# Agent home for any runtime state (sqlite checkpointer, etc.)
RUN mkdir -p /home/agent/.commandclaw && \
    chown -R agent:agent /home/agent

# Trust all git directories (workspace is mounted from host with different uid)
RUN git config --system safe.directory '*'

USER agent
WORKDIR /workspace

# Default env vars — overridden by docker-compose or spawn script
ENV COMMANDCLAW_VAULT_PATH=/workspace
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check — agent process is running
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["python", "-c", "print('ok')"]

# Default: chat mode (telegram mode via override)
ENTRYPOINT ["python", "-m", "commandclaw"]
CMD ["chat"]
