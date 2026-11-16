# Architecture Decision Records

ADRs document significant decisions that shape the project's structure, quality attributes, dependencies, or interfaces. Each ADR records context, considered options, a decision, and consequences.

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-shared-contract-and-runner.md) | Accepted | Use a shared contract and runner for all adapters |
| [0002](0002-sdk-specific-root-directories.md) | Accepted | Use one root directory and container per SDK |
| [0003](0003-runtime-provider-credentials.md) | Accepted | Supply credentials at runtime and use a service principal for Azure |
| [0004](0004-runner-enforced-completion-checks.md) | Accepted | Enforce build completion checks in the shared runner |

Create a numbered Markdown file for each new significant decision. Do not silently edit an accepted ADR; a later decision should reference it with `Supersedes`, while the earlier ADR receives the status `Superseded`.

The format follows lightweight ADR practices from [Defra](https://defra.github.io/architecture/governance/architecture-decision-records/) and [AWS](https://docs.aws.amazon.com/prescriptive-guidance/latest/architectural-decision-records/adr-process.html).
