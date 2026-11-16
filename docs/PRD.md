# PRD: Contract-driven agent containers

**Status:** Active
**Last updated:** 2026-11-16
**Owner:** Project team

## Problem

Teams need to run a repository repair or change request reproducibly with different coding-agent SDKs. The task format, permissions, source access, logs, and artifacts must behave consistently regardless of the selected model provider. Without a shared layer, execution, security boundaries, and results differ by agent and cannot be compared easily.

## Users

- Developers who want to send a scoped code task to Codex, Claude, or OpenCode.
- Platform and security teams that need to review tool and write permissions for each task.
- Teams running models through their own API credentials or Azure AI Foundry.

## Product goal

The container accepts a versioned JSON task, works on a fresh Git branch, and returns a machine-readable result, transcript, and patch. A user can select the SDK provider without changing the task contract.

## Scope

### In scope

- Three SDK-specific containers: Codex, Claude, and OpenCode.
- A shared request/result contract, checkout, branch publication, and artifacts.
- Three sandbox levels: `read_only`, `workspace_write`, and `full_access`.
- A provider-neutral completion policy that runs required build checks and returns failures to the agent for repair.
- Structured progress logs on `stderr`.
- Model access through native provider credentials or an Azure AI Foundry service principal.
- An intentionally broken ARM32 C demo repository and separate compiler image.

### Out of scope

- Multi-agent orchestration within a task.
- Persistent sessions or resuming a prior task.
- Hosting a model endpoint from this repository.
- Guaranteeing that every external provider enforces every sandbox rule identically.

## User flow

1. The user creates `shared/.env`, prepares the demo repository, and builds the selected container.
2. The user passes a JSON task to Docker Compose through `stdin`.
3. The runner validates the contract, checks out the base branch, and maps requested permissions to SDK rules.
4. The agent modifies the isolated workspace and returns a structured final report.
5. The runner runs the task's required completion checks. A failed check is returned to the agent for repair within the configured attempt limit.
6. For a non-technical result with passing completion checks, the runner publishes the work branch and writes the result, transcript, and patch to `shared/out/`.

## Success criteria

- One example task can start each available SDK adapter through the same contract.
- Every task reports a status, output artifacts, and duration.
- An agent can run the compiler only when the selected permission allows it.
- A successful task has passed every required completion check without configured warning or error output.
- Credentials are supplied at runtime from a local environment file or read-only host mount and are never embedded in an image.

Detailed acceptance is defined by the IDs in [requirements.md](requirements.md).

## Open product questions

- Which providers and model deployments should be officially supported beyond the demo?
- Should the allowed-command list move from the OpenCode harness into the task contract?
- Which external integration should process work branches after a successful task?
