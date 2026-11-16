# syntax=docker/dockerfile:1.7
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1 \
    VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONPATH=/app \
    WORKSPACE_DIR=/workspace OUTPUT_DIR=/output AGENT_PROFILES_DIR=/app/profiles \
    CLAUDE_CONFIG_DIR=/home/agent/.claude

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git tini file python3 python3-venv make \
      gcc-arm-linux-gnueabihf libc6-dev-armhf-cross \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir \
      claude-agent-sdk==0.2.152 \
      'azure-identity>=1.19,<2' \
      'pydantic>=2.10,<3' \
      'PyYAML>=6.0,<7' \
      'starlette>=0.45,<1' \
      'uvicorn[standard]>=0.34,<1'

WORKDIR /app
COPY shared/agent/ ./agent/
COPY claude/harness.py ./claude_harness.py
COPY claude/profiles/ ./profiles/
COPY shared/docker-entrypoint.sh /usr/local/bin/agent-entrypoint
RUN useradd -m -u 10001 agent \
    && mkdir -p /workspace /output /home/agent/.claude \
    && chown -R agent:agent /workspace /output /home/agent/.claude \
    && git config --system user.name "agent" \
    && git config --system user.email "agent@localhost" \
    && git config --system --add safe.directory '*'

ENV AGENT_MODE=run AGENT_HARNESS=claude-code-sdk
USER agent
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/agent-entrypoint"]
