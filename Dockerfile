FROM python:3.12-slim

# System deps for git, node/npm (skills), basic tools, and C++ compiler (annoy)
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl g++ nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — agent runs as 'agent', not root
RUN groupadd -r agent && \
    useradd -r -g agent -d /home/agent -m agent

WORKDIR /app

# --- Layer 1: Dependencies only (cached unless pyproject.toml changes) ---
COPY pyproject.toml README.md ./
RUN mkdir -p src/commandclaw && \
    echo '__version__ = "0.1.0"' > src/commandclaw/__init__.py && \
    pip install --no-cache-dir --timeout=300 --retries=5 . && \
    rm -rf src/commandclaw

# Pre-download NeMo Guardrails embedding model (fastembed) into a fixed cache path.
# FASTEMBED_CACHE_PATH must match at build-time and runtime so the model is found.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed_cache
ENV HF_HOME=/opt/hf_cache
RUN python -c "from fastembed import TextEmbedding; \
    TextEmbedding('BAAI/bge-small-en-v1.5'); \
    TextEmbedding('sentence-transformers/all-MiniLM-L6-v2')"

# --- Layer 2: Source code (fast — only rebuilds on code changes) ---
COPY src/ src/
RUN pip install --no-cache-dir --no-deps --force-reinstall .

# Workspace is mounted at /workspace — the agent's vault
VOLUME /workspace

# Entrypoint script — initializes vault from template if needed
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Agent home for any runtime state (sqlite checkpointer, etc.)
RUN mkdir -p /home/agent/.commandclaw && \
    chown -R agent:agent /home/agent

# Trust all git directories (workspace is mounted from host with different uid)
RUN git config --system safe.directory '*'

WORKDIR /workspace

# Default env vars — overridden by docker-compose or spawn script
ENV COMMANDCLAW_VAULT_PATH=/workspace
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check — agent process is running
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["python", "-c", "print('ok')"]

# Entrypoint: init vault from /vault-template if workspace is empty, then run agent
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["chat"]
