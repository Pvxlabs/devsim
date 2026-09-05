# Integrating an Existing Application

DevSim is an orchestration layer around an existing development environment. The application remains responsible for its schema, authentication, domain behavior, and runtime state.

## Setup

1. Add a root `devsim.yaml` to the application repository.
2. Set `project.name`, `environment.mode`, and the PostgreSQL lifecycle commands needed by the project.
3. Add either a project-owned `seed.command` or schema-aware PostgreSQL seed
   intent for deterministic baseline data.
4. Set `scenarios.path` and the local `runtime.base_url`.
5. Create scenario YAML files under the configured path.
6. Start the application through the project's existing lifecycle command.
7. Use `api.request` and `command.run` to drive real application paths and read observable state.
8. Use `devsim scenario inspect <run_id>` to inspect the redacted run artifact.
9. Use `devsim scenario replay <run_id>` to repeat the same scenario seed after confirming the scenario hash is unchanged.

## Example Manifest

```yaml
version: 1
project:
  name: existing-app
environment:
  mode: development
database:
  engine: postgres
  lifecycle:
    up: {command: docker compose up -d postgres app}
    migrate: {command: python scripts/migrate.py}
    reset: {command: python scripts/reset_database.py}
    down: {command: docker compose down}
seed:
  command: python scripts/seed_preview.py
scenarios:
  path: devsim/scenarios
runtime:
  base_url: http://127.0.0.1:8000
  adapters:
    - type: http
    - type: command
```

The lifecycle and custom seed commands are ordinary project commands. Baseline
initialization may write directly to a DEV/Preview PostgreSQL database through
DevSim's schema-aware seed mode. Runtime evolution should go through the
application's local API, application command, or browser path. Credentials
belong in the external project's environment or scenario context; do not
hard-code secrets in DevSim Core.

## Contract Layers

**Public stable:** manifest version `1`, scenario version `1`, `api.request`, `command.run`, the `at`/`every`/`until`/`action`/`with` timeline fields, `expect`, JSON CLI output, and redacted run artifacts.

**Internal:** lifecycle marker adapters and the on-disk `.devsim` state implementation.

**Experimental:** project-specific helper commands and application behavior invoked by those commands. They are owned and versioned by the external project.

See [integration-standard.md](integration-standard.md) for the complete v1
contract and [agent-contract.md](agent-contract.md) for machine-readable agent
workflow and exit codes.
