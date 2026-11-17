# ADR-0005: Implement the OpenCode adapter as a TypeScript-native runner

**Status:** Accepted
**Date:** 2026-11-17
**Supersedes:** ADR-0001 for the OpenCode adapter's runner implementation. The shared contract, Git workflow, and completion-check semantics remain unchanged.

## Context

ADR-0001 placed a shared Python runner between the task contract and every SDK. The OpenCode SDK (`@opencode/sdk`) is an embedded, in-process host whose lifecycle does not fit a request/response shim:

- Session prompts are admitted asynchronously; completion must be observed via `session.execution.*` events rather than by the return value of the prompt call.
- Configuration is applied through `OpenCode.create()` options. The `OPENCODE_CONFIG_CONTENT` environment variable is honored only by the CLI bootstrap, so an embedded host that relies on it silently ignores the configured provider, model, and permissions and can fall back to opencode.ai's free inference gateway.
- Message shape, provider activation, and credential resolution are versioned with the SDK and drifted from the shapes the Python bridge assumed.

Extending the Python shim for this lifecycle duplicated SDK surface while hiding behavior that only the embedded host exhibits.

## Considered options

1. Keep the Python shim and add OpenCode-specific event handling to it.
2. Implement the OpenCode adapter natively in TypeScript against `@opencode/sdk`.
3. Shell out to the opencode CLI and drive it through text protocols.

## Decision

`opencode/runner.ts` is a Bun/TypeScript runner that uses `@opencode/sdk` directly. It keeps the shared contract semantics: the same request and result schema, repository checkout, completion checks with the repair loop, artifacts, and Git publication as the Python runner. OpenCode-specific concerns — event-driven completion with a deadline watchdog, config content via create options, message parsing, permission rules, and the final report extraction — stay inside the adapter. Logging follows the same `stderr` convention, and agent activity (tool calls with targets, tool failures with reasons, per-step token and cost totals) is logged live and recorded in the transcript artifact.

## Consequences

- Adapter behavior tracks the SDK it embeds instead of a second abstraction layer.
- The completion guarantee stays provider-neutral and identical across adapters.
- Contract changes must now be applied to two implementations: the Python shared runner (Codex, Claude) and the TypeScript OpenCode runner.
- Only the OpenCode adapter diverges from the shared runner; Codex and Claude are unchanged.
