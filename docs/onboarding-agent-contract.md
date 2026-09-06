# DevSim Onboarding Agent Contract

This contract defines how an AI Coding Agent adds DevSim to an existing
repository. DevSim is a deterministic integration planner and orchestrator;
the agent remains responsible for application-aware decisions.

## Lifecycle

```text
DISCOVER  devsim capabilities --json
INSPECT   devsim onboard --inspect --json
PLAN      devsim onboard --plan --json
SCAFFOLD  devsim onboard --apply --json
IMPLEMENT agent_required steps in the target repository
VALIDATE  devsim onboard --validate --json
QUALIFY   devsim doctor --json, then the canonical preview
```

`--inspect` and `--plan` are read-only. `--apply` creates only missing
standard DevSim files and never overwrites existing files or changes
application business code. The plan uses these modes:

- `auto`: safe to reuse or scaffold mechanically.
- `agent_required`: requires reading the application's real lifecycle, API,
  schema, and UI semantics.
- `user_required`: blocked until an invalid or unsafe project decision is
  reviewed.

## Agent Responsibilities

The agent must decide and implement:

- the canonical DEV/Preview lifecycle and migration path;
- custom or schema-aware baseline seeding without violating domain invariants;
- canonical scenarios and semantic profiles (`minimal`, `normal`, `active`);
- browser base URL, pages, selectors, and evidence checks;
- the short repository `AGENTS.md` guidance.

The agent must not guess business APIs, authentication, runtime state meaning,
production configuration, production credentials, or real exchange behavior.
Runtime evolution should use the real application API, command, or browser
path. Direct PostgreSQL writes are limited to safe DEV/Preview baseline
initialization.

## Qualification

An integration is complete only when `devsim onboard --validate --json`
reports `INTEGRATION=READY`, the project validator passes, and a deterministic
preview can be started, observed, inspected, and stopped without targeting
production. Do not commit `.devsim/` runtime artifacts.
