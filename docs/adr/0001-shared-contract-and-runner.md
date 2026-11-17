# ADR-0001: Use a shared contract and runner for all adapters

**Status:** Accepted (the runner part for the OpenCode adapter is superseded by [ADR-0005](0005-opencode-typescript-native-runner.md); the shared contract and Git workflow remain in force)
**Date:** 2026-11-16

## Context

Codex, Claude, and OpenCode have different SDKs, authentication models, and tool permissions. Task submitters still need one request and result format and the same Git workflow for every agent.

## Considered options

1. Write a dedicated runner for every SDK container.
2. Use a shared runner and contract with small SDK harnesses.
3. Require an external workflow or job orchestrator.

## Decision

`shared/agent/` contains the contract, validation, checkout, publishing, results, and logs. Each SDK directory contains only its Dockerfile, Compose file, profile, and harness. The harness maps the contract to its SDK call.

## Consequences

- Task submitters use the same JSON format across providers.
- Changes to the Git workflow and artifacts happen in one place.
- Adapters must adopt contract changes together.
- The contract must be extended before an SDK-specific capability can be exposed.
