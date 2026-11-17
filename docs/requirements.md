# Requirements

**Last updated:** 2026-11-17
**Legend:** `Implemented` describes the current repository state. `External verification` requires a real provider account and deployment to accept.

| ID | Requirement | Type | Priority | Status | Verification |
| --- | --- | --- | --- | --- | --- |
| FR-001 | The system accepts a versioned JSON task containing a repository, objective, criteria, limits, and permissions. | Functional | Must | Implemented | Schema validation and example tasks |
| FR-002 | Each task creates a fresh workspace from the specified Git repository and base branch. | Functional | Must | Implemented | Runner log and created workspace |
| FR-003 | A task with a non-technical result publishes a work branch and returns its commit hash and patch. | Functional | Must | Implemented | Result JSON and `changes.patch` |
| FR-004 | The result contains status, criterion outcomes, summary, rationale, duration, and artifact references. | Functional | Must | Implemented | Validate `result.json` against the contract |
| FR-005 | Codex, Claude, and OpenCode use the same task contract. | Functional | Must | Implemented | One example task per adapter in `demo/examples/` |
| FR-006 | A task can select `read_only`, `workspace_write`, or `full_access`. | Functional | Must | Implemented | Adapter rules and `permissions.applied` log |
| FR-007 | With OpenCode, `workspace_write` permits reading, editing, `make`, and `arm-linux-gnueabihf-gcc`; other shell commands remain denied. | Functional | Must | Implemented | Inspect OpenCode configuration and run a negative command test |
| FR-008 | Progress and errors are emitted as JSON on `stderr` without recording prompts, responses, or credentials. | Functional | Should | Implemented | Container run and log inspection |
| FR-009 | Codex can read credentials from a read-only host mount; API-based providers can read credentials from `shared/.env`. | Functional | Must | Implemented | Compose configuration and startup check |
| FR-010 | All three adapters can use an Azure AI Foundry endpoint, deployment, and service-principal credentials from `shared/.env`. | Functional | Must | External verification | Run against an authorized Foundry deployment |
| FR-011 | The demo includes a standalone image with an ARM32 cross-compiler that demonstrates the failed build without an agent or model credentials. | Functional | Should | Implemented | `docker build` and `docker run … make` (see `demo/README.md`) |
| FR-012 | A task can configure ordered completion checks, warning policy, timeouts, and repair attempts through a provider-neutral contract field. | Functional | Must | Implemented | Validate example tasks and inspect the runner's completion artifacts |
| FR-013 | The runner must not return `succeeded` unless every required completion check passes; it must return failures to the agent for repair up to the configured limit. | Functional | Must | Implemented | Run a task with an initially failing build and inspect the final result and completion logs |
| FR-014 | A task can specify the model identifier used by its agent; it takes precedence over the profile default and over the Azure deployment fallback. | Functional | Must | Implemented | Validate a task with `model` and inspect the adapter invocation |
| FR-015 | The runner emits live agent activity (tool calls with targets, failures with reasons, per-step token and cost totals) on `stderr` and records it in the transcript artifact. | Functional | Should | Implemented | Run the OpenCode demo and inspect `stderr` and `transcript.jsonl` |
| NFR-001 | Secrets must not appear in Docker images, logs, or the Git repository. | Security | Must | Implemented | Inspect `.gitignore`, Dockerfiles, and logging code |
| NFR-002 | A task must not edit the host repository directly; changes happen in the container workspace and are published as a Git branch. | Security | Must | Implemented | Inspect mounts and Git workflow |
| NFR-003 | Provider-specific code remains in `codex/`, `claude/`, and `opencode/`; contract and workflow remain in `shared/`. | Maintainability | Should | Implemented | Inspect directory structure |
| NFR-004 | Product and architecture decisions are versioned as Markdown in the same repository. | Governance | Should | Implemented | Inspect `docs/` and pull-request review |

## Traceability

| PRD goal | Requirements |
| --- | --- |
| Shared provider-independent task | FR-001 through FR-005, NFR-003 |
| Auditable, bounded execution | FR-006 through FR-008, FR-015, NFR-001 through NFR-002 |
| Flexible model access | FR-009 through FR-010 |
| Reproducible demonstration | FR-011 |
| Verified completion | FR-012 through FR-013 |
| Reproducible model selection | FR-014 |

## Known limitations

- `limits.max_steps` and `limits.max_cost_usd` are validated by the contract but not enforced by the runners; only `limits.max_duration_s` aborts a run.
- `permissions.sandbox: full_access` delegates to each SDK's unrestricted mode; the providers do not guarantee identical sandbox behavior (see PRD out of scope).

New requirements receive a sequential ID, testable wording, and one verification method. This lightweight traceability follows the recommendation to track requirements with type, priority, status, and verification. [NASA SRS guidance](https://swehb.nasa.gov/spaces/SWEHBVD/pages/140640605/SRS%2B-%2BSoftware%2BRequirements%2BSpecification)
