# Product and architecture documentation

These documents are versioned beside the code. The PRD defines the problem, users, and product outcome; the requirements make those goals testable through IDs and verification methods; ADRs record significant architecture decisions and their consequences.

The structure follows three intentionally lightweight practices:

- Requirements have an ID, priority, status, and verification method. This gives traceability without a heavyweight requirements-management system. [NASA SRS guidance](https://swehb.nasa.gov/spaces/SWEHBVD/pages/140640605/SRS%2B-%2BSoftware%2BRequirements%2BSpecification)
- Each ADR covers one significant decision, records its context, options, and consequences, and is later replaced by a new ADR instead of being silently edited. [Defra ADR guidance](https://defra.github.io/architecture/governance/architecture-decision-records/)
- The PRD, requirements, and ADRs remain as Markdown in the repository so they can be reviewed and traced with code changes. [Google Cloud ADR overview](https://docs.cloud.google.com/architecture/architecture-decision-records)

| Document | Purpose |
| --- | --- |
| [PRD](PRD.md) | Product goal, users, scope, and success criteria |
| [Requirements](requirements.md) | Testable functional and non-functional requirements |
| [ADR index](adr/README.md) | Binding architecture decisions |

Changes to the product goal begin in the PRD. Changes to verifiable behavior add or update a requirement. A difficult-to-reverse architecture decision requires a new ADR.
