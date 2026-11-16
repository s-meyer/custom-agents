# syntax=docker/dockerfile:1.7
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1 \
    VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git tini file python3 python3-venv make \
      gcc-arm-linux-gnueabihf libc6-dev-armhf-cross \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 10001 agent && python3 -m venv "$VIRTUAL_ENV"
WORKDIR /app
COPY codex/pyproject.toml ./
COPY shared/agent/ ./agent/
COPY codex/harness.py ./codex_harness.py
RUN pip install --no-cache-dir .
COPY codex/profiles/ ./profiles/
COPY shared/docker-entrypoint.sh /usr/local/bin/agent-entrypoint
ENV AGENT_MODE=run AGENT_PROFILES_DIR=/app/profiles \
    WORKSPACE_DIR=/workspace OUTPUT_DIR=/output PORT=8088 CODEX_HOME=/home/agent/.codex
RUN mkdir -p /workspace /output /home/agent/.codex \
    && chown -R agent:agent /workspace /output /home/agent/.codex \
    && git config --system user.name "agent" \
    && git config --system user.email "agent@localhost" \
    && git config --system --add safe.directory '*'
USER agent
EXPOSE 8088
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/agent-entrypoint"]
