# ADR-0004: Enforce build completion checks in the shared runner

**Status:** Accepted
**Date:** 2026-11-16

## Context

Every agent must run a final build and may report success only when the build passes without configured warnings or errors. The project uses three SDKs with different hook and lifecycle mechanisms. A provider-specific hook would make equivalent behavior hard to guarantee and would expose provider details in the task contract.

## Considered options

1. Instruct each agent to run the build before its final response.
2. Implement a completion hook separately in each SDK adapter.
3. Have the shared runner execute a provider-neutral completion policy after every final agent response and return failures for repair.

## Decision

The task contract exposes an optional `completion` policy containing ordered argument-vector checks, timeouts, warning handling, and a repair-attempt limit. The profile supplies a default when the task omits it. The shared runner executes the checks after each agent response, records their logs as artifacts, and starts a follow-up repair attempt when a check fails. It rejects `succeeded` until every check passes.

## Consequences

- Every adapter receives the same final-build guarantee without relying on SDK hook behavior.
- Task submitters can override the default build for another repository through the contract.
- Argument vectors avoid shell interpolation in the runner.
- Completion checks require a writable workspace; `read_only` tasks cannot use them.
- A stuck or persistently failing build ends as `failed` or `aborted` when the repair or task-time limit is reached.
