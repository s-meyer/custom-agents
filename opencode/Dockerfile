# syntax=docker/dockerfile:1.7
FROM oven/bun:1

ENV DEBIAN_FRONTEND=noninteractive \
    WORKSPACE_DIR=/workspace OUTPUT_DIR=/output AGENT_PROFILES_DIR=/app/profiles \
    OPENCODE_DISABLE_PROJECT_CONFIG=1 AGENT_MODE=run AGENT_HARNESS=opencode-sdk

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git tini file make \
      gcc-arm-linux-gnueabihf libc6-dev-armhf-cross \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY opencode/package.json ./package.json
RUN bun install --production
COPY opencode/profiles/ ./profiles/
COPY opencode/runner.ts ./runner.ts
COPY opencode/entrypoint.sh /usr/local/bin/agent-entrypoint
RUN useradd -m -u 10001 agent \
    && mkdir -p /workspace /output /home/agent/.config/opencode \
    && chmod +x /usr/local/bin/agent-entrypoint \
    && chown -R agent:agent /workspace /output /home/agent/.config/opencode /app \
    && git config --system user.name "agent" \
    && git config --system user.email "agent@localhost" \
    && git config --system --add safe.directory '*'

USER agent
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/agent-entrypoint"]
