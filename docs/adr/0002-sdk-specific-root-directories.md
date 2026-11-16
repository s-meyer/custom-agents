# ADR-0002: Use one root directory and container per SDK

**Status:** Accepted
**Date:** 2026-11-16

## Context

The SDKs need different runtimes and dependencies: Python with Codex, Python with Claude Code, and Bun with OpenCode. One combined image would merge unnecessary packages, credentials, and failure modes.

## Considered options

1. One large image containing every SDK.
2. An `image/` subdirectory containing multiple Dockerfiles.
3. One root directory per SDK and a separate directory for shared code.

## Decision

SDK-specific assets live in `codex/`, `claude/`, and `opencode/`; shared code lives in `shared/`. Docker Compose builds from the repository root and selects the relevant Dockerfile.

## Consequences

- Images stay smaller and SDK dependencies remain clearly separated.
- Each integration is visible directly at repository root.
- Shared changes require coordinated builds for the affected images.
