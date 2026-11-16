#!/bin/sh
set -eu

if [ -n "${CODEX_AUTH_MOUNT:-}" ] && [ -d "$CODEX_AUTH_MOUNT" ]; then
  mkdir -p "$CODEX_HOME"
  cp -R "$CODEX_AUTH_MOUNT"/. "$CODEX_HOME"/
  chmod -R go-rwx "$CODEX_HOME"
fi
exec python -m agent "$@"
