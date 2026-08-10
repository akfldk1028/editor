# Claude repository entry point

Read and follow [`AGENTS.md`](AGENTS.md) before changing this repository. Its
architecture, verification, and source-safety rules are authoritative for all
agents.

Then read:

- [`docs/handoff/repo-memory.md`](docs/handoff/repo-memory.md) for stable project
  decisions, capabilities, and known limits.
- [`docs/architecture/module-boundaries.md`](docs/architecture/module-boundaries.md)
  before changing ownership or imports.
- [`docs/architecture/integration-contract.md`](docs/architecture/integration-contract.md)
  before integrating this repository into another project.

Treat commits, ports, authentication state, test totals, and local drawing paths
as checkout-specific. Verify them locally instead of copying them into durable
project memory.
