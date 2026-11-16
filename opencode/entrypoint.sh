#!/bin/sh
set -eu

exec bun run /app/runner.ts "$@"
