# DevSim Project Integration Standard v1

This document is the canonical integration contract for a DevSim-enabled
repository. The released implementation is authoritative for compatibility;
this standard does not rename existing v1 fields.

## Layout

```text
project/
├── devsim.yaml                 # canonical integration entrypoint
├── devsim/
│   ├── seed.yaml               # optional schema-aware seed intent
│   ├── scenarios/              # project-owned scenario definitions
│   ├── commands/               # optional project helpers
│   └── browser/                # optional browser fixtures/helpers
└── application...
```

Only create `commands/` or `browser/` when the project needs them. Runtime
state and run evidence belong in `.devsim/`, which must not be committed.

## Manifest

`devsim.yaml` has `version: 1` and is the single canonical project entrypoint.
The current v1 field names are:

```yaml
version: 1
project: {name: example-app}
environment: {mode: development}
database:
  engine: postgres
  lifecycle:
    up: {command: docker compose up -d postgres}
    migrate: {command: python scripts/migrate.py}
    reset: {command: python scripts/reset_database.py}
    down: {command: docker compose down}
seed:
  mode: schema
  schema: {database_url: '${env.DEVSIM_DATABASE_URL}'}
  plan: {tables: {}}
  profiles: {normal: {}}
scenarios: {path: devsim/scenarios}
runtime:
  base_url: http://127.0.0.1:8000
  adapters: [{type: http}, {type: command}]
observation:
  browser:
    pages: {home: {path: /}}
presets:
  normal: {seed_profile: normal, scenario: normal}
```

`seed.command` is also valid. A project may use either a custom seed command or
the schema-aware PostgreSQL seed mode. Direct writes to a DEV/Preview database
are allowed for baseline initialization. Once the application is running,
runtime evolution should use the real application API, command, or browser
path so domain behavior is exercised.

## Six Contracts

1. **Project Manifest Contract**: `devsim.yaml` declares project identity,
   development environment, database lifecycle, seed mode, scenario path,
   runtime endpoint, adapters, observation, and named presets.
2. **Environment Lifecycle Contract**: `database.lifecycle` commands own
   application-specific startup, migration, reset, and shutdown. DevSim
   orchestrates them and applies its safety checks.
3. **Seed Contract**: a custom `seed.command` or schema-aware PostgreSQL plan
   creates deterministic baseline state. Schema-aware seeding is for local
   DEV/Preview/Test targets only.
4. **Scenario Contract**: scenario files use `version: 1`, the released DSL,
   adapters, expectations, and finite or persistent runtime semantics.
5. **Observation Contract**: API, WebSocket, browser, and screenshot checks
   observe the real application. A blocked browser adapter is not a pass.
6. **Preview Profile Contract**: a preset binds a semantic seed profile to a
   persistent scenario. Recommended names are `empty`, `minimal`, `normal`,
   `active`, `degraded`, and `ui-stress`; projects may implement a subset.

## Ownership Boundary

DevSim Core owns orchestration, simulation, scheduling, safety, observation,
control, replay, and evidence. The project owns schema, migrations, domain
behavior, authentication, lifecycle commands, semantic seed values, and
scenario actions. DevSim Core is not an application business-logic library.

## Validation

Use `devsim project validate --json` before running a preview. It validates the
manifest, lifecycle references, seed declaration, scenarios, preset references,
browser configuration, and local/private observation URLs without starting a
process or mutating a database.
