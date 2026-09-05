# DevSim

DevSim is a deterministic preview runtime for developing and testing stateful applications with realistic data and evolving runtime scenarios.

> Simulate the world. Run the real application.

DevSim orchestrates a real development environment: database lifecycle commands, project-provided seed commands, a virtual clock, and scheduled actions against a real HTTP service or process. The core is domain-agnostic. Business concepts belong in the example application or in a project-specific scenario.

## V1

- Python 3.11+
- PostgreSQL lifecycle orchestration through project commands
- YAML manifest and scenario DSL
- deterministic, run-local random seed
- virtual clock with an arbitrary positive speed
- HTTP and command adapters
- `.devsim/state.json` runtime metadata and JSON CLI output
- local development safety guard for reset, seed, and down operations

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
```

The CLI can also be invoked as `python -m devsim`.

## CLI

Run commands from a project directory containing `devsim.yaml`:

```bash
devsim init
devsim up
devsim reset --seed 42
devsim seed --seed 42
devsim status
devsim status --json
devsim scenario list --json
devsim scenario run active-session --seed 42 --json
devsim scenario stop
devsim scenario reset
devsim clock status
devsim down
```

The root manifest is configured to dogfood the FastAPI example. The complete example can also be run from its own directory:

```bash
cd examples/fastapi-postgres
pip install -r requirements.txt
devsim up
devsim reset --seed 42
devsim scenario run active-session --seed 42
devsim status
devsim down
```

`devsim reset` is deliberately strict: it runs the configured reset, migrate, and seed commands in that order. A failed step stops the operation and writes a failed state with a structured error.

## Manifest

```yaml
version: 1
project:
  name: example-app
environment:
  mode: development
database:
  engine: postgres
  lifecycle:
    up:
      command: docker compose up -d postgres
    migrate:
      command: python scripts/migrate.py
    reset:
      command: python scripts/reset_database.py
    down:
      command: docker compose down
seed:
  command: python devsim/seed.py
scenarios:
  path: devsim/scenarios
runtime:
  base_url: http://127.0.0.1:8000
  adapters:
    - type: http
    - type: command
```

All project behavior is injected through commands and adapters. DevSim does not implement a migration framework and does not write runtime metadata into the application's database.

## Scenario DSL

```yaml
version: 1
name: active-session
description: Demonstrates an evolving runtime.
clock:
  speed: 10
timeline:
  - at: 0s
    action: lifecycle.start
  - at: 5s
    action: api.request
    with:
      method: POST
      path: /api/demo/events
      json:
        type: session_started
      expected_status: 201
  - every: 1s
    until: 10s
    action: api.request
    with:
      method: POST
      path: /api/demo/heartbeat
      expected_status: 200
  - at: 11s
    action: lifecycle.complete
```

`at` and `every` accept `ms`, `s`, and `m`. Repeating events begin at their interval and include the event at `until` when it lands exactly on the boundary. Events at the same virtual time are ordered by their timeline position.

## Determinism

Every scenario run has a run-local `DeterministicRNG`, seeded from `--seed`. The state records the scenario name, canonical scenario hash, seed, run ID, scenario version, virtual start time, and event sequence. Adapter processes receive `DEVSIM_SEED`, `DEVSIM_RUN_ID`, `DEVSIM_PROJECT`, `DEVSIM_SCENARIO`, and `DEVSIM_VIRTUAL_TIME_MS`.

The run ID and wall-clock timestamps are intentionally unique per invocation. Random values, schedule expansion, event ordering, and project-provided deterministic behavior are reproducible for the same scenario and seed.

## Safety

Reset, seed, and down are denied unless `environment.mode` is one of `development`, `dev`, `test`, or `preview`, and `runtime.base_url` resolves to localhost, a private address, or a local Docker service name. Production-looking or public endpoints fail closed.

## Project layout

```text
devsim/
  adapters/
  clock.py
  cli.py
  config.py
  lifecycle.py
  runner.py
  scheduler.py
  state.py
examples/
  fastapi-postgres/
tests/
```

## License

MIT
