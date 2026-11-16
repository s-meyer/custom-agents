# ADR-0003: Supply credentials at runtime and use a service principal for Azure

**Status:** Accepted
**Date:** 2026-11-16

## Context

The containers must support both personal provider access and organization-managed Azure AI Foundry deployments. Secrets stored in Dockerfiles or the repository are unacceptable.

## Considered options

1. Store API keys in Docker build arguments or images.
2. Authenticate interactively inside each container.
3. Supply credentials at runtime through a local ignored environment file or read-only credential mount; obtain an Azure Entra token from service-principal credentials.

## Decision

`shared/.env` is the local ignored location for API keys and Azure service-principal values. Codex can additionally mount the local authentication cache read-only. Shared Azure code obtains an Entra token for each task and passes it to the selected adapter.

## Consequences

- Secrets are not copied into images and can rotate independently of image builds.
- An Azure run needs tenant ID, client ID, client secret, endpoint, deployment, and an appropriate RBAC role.
- Tokens are currently obtained when a task starts; long-running tasks need a future refresh extension if the token expires.
- The Azure integration requires a run against an authorized deployment for full acceptance.
