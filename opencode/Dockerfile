# syntax=docker/dockerfile:1.7
FROM oven/bun:1

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1 \
    VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONPATH=/app \
    WORKSPACE_DIR=/workspace OUTPUT_DIR=/output AGENT_PROFILES_DIR=/app/profiles \
    OPENCODE_DISABLE_PROJECT_CONFIG=1 AGENT_MODE=run AGENT_HARNESS=opencode-sdk

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git tini file python3 python3-venv make \
      gcc-arm-linux-gnueabihf libc6-dev-armhf-cross \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY opencode/package.json ./package.json
RUN bun install --production
COPY shared/agent/ ./agent/
COPY opencode/harness.py ./opencode_harness.py
COPY opencode/profiles/ ./profiles/
COPY opencode/sdk-runner.ts ./opencode-sdk-runner.ts
COPY shared/docker-entrypoint.sh /usr/local/bin/agent-entrypoint
RUN python3 -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir \
      'azure-identity>=1.19,<2' 'pydantic>=2.10,<3' 'PyYAML>=6.0,<7' 'starlette>=0.45,<1' 'uvicorn[standard]>=0.34,<1' \
    && useradd -m -u 10001 agent \
    && mkdir -p /workspace /output /home/agent/.config/opencode \
    && chown -R agent:agent /workspace /output /home/agent/.config/opencode /app \
    && git config --system user.name "agent" \
    && git config --system user.email "agent@localhost" \
    && git config --system --add safe.directory '*'

USER agent
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/agent-entrypoint"]
