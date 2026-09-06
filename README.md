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
- `.devsim/runs/<run_id>.jsonl` redacted run artifacts
- scenario expectations, step context, inspect, and replay identity
- local development safety guard for reset, seed, and down operations
- schema-aware PostgreSQL seed planning with deterministic generators and profiles
- local preview control API/UI and optional browser observation screenshots

## M2 Persistent Runtime

DevSim can keep a scenario running as a managed local process. A finite
scenario exits after its timeline completes; a persistent scenario continues
recurring events until it is stopped or reaches a configured limit.

```bash
devsim scenario start active-runtime --seed 42
devsim status
devsim scenario pause
devsim scenario resume
devsim scenario stop
```

Persistent scenarios use `runtime.mode: persistent`. Repeating events without
`until` are allowed only in that mode. `runtime.limits.max_events` and
`runtime.limits.max_virtual_duration` bound long-running previews. Ownership
and heartbeats live under `.devsim/runtime/`; `status` reports a dead owner as
`STALE`, and `scenario reset` clears the metadata.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
```

The CLI can also be invoked as `python -m devsim`.

For a new project, the canonical first commands are:

```bash
devsim detect
devsim init
devsim doctor
devsim preview normal --seed 42
```

`devsim --json` is the agent interface. Use `devsim capabilities --json`,
`devsim detect --json`, and `devsim project status --json` for discovery. The
repository-owned Codex skill can be installed into the standard skill directory
with `devsim skill install`.

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
devsim scenario start active-runtime --seed 42 --json
devsim scenario pause --json
devsim scenario resume --json
devsim scenario stop --json
devsim scenario validate --all --json
devsim doctor --json
devsim detect --json
devsim capabilities --json
devsim project status --json
devsim project validate --json
devsim onboard --inspect --json
devsim onboard --plan --json
devsim onboard --apply --json
devsim onboard --validate --json
devsim quickstart
devsim preview status --json
devsim preview stop --json
devsim scenario inspect <run_id> --json
devsim scenario replay <run_id> --json
devsim scenario replay <run_id> --allow-changed-scenario --json
devsim scenario stop
devsim scenario reset
devsim clock status
devsim seed plan --json
devsim seed validate --json
devsim schema inspect --json
devsim serve
devsim preview normal --seed 42
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

For a project with a configured preview preset, the normal daily workflow is:

```bash
devsim preview normal --seed 42
devsim serve
```

Open the application to watch real state evolve. Use the control UI to inspect the
runtime, replay a seed, and pause or resume the scenario. `devsim preview` resets
the configured local database, applies the selected seed profile, and starts the
managed scenario; it never targets production.

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

All project behavior is injected through commands and adapters. DevSim does not
implement a migration framework. Direct writes are supported for baseline
initialization of a safe DEV/Preview PostgreSQL database; runtime evolution
should use the real application path.

### Schema-aware seed mode

Custom seed commands remain supported. Projects that opt in to schema-aware mode
declare a local PostgreSQL URL, a table plan, and optional profiles:

```yaml
seed:
  mode: schema
  schema:
    database_url: ${env.DEVSIM_DATABASE_URL}
  plan:
    tables:
      accounts:
        count: 10
        columns:
          email: {generator: internet.email}
  profiles:
    minimal: {accounts: 1}
    normal: {accounts: 10}
```

Run `devsim seed plan` or `devsim seed validate` before mutation. DevSim reads
only the configured development database, orders tables by foreign-key dependency,
assigns relationships deterministically, and fails with `CYCLIC_SEED_DEPENDENCY`
or `SEED_SCHEMA_DRIFT` when the contract cannot be applied safely.

The integration boundary is intentionally generic: an external project owns
`devsim.yaml`, its seed contract, its scenario files, and any helper commands.
DevSim only executes those contracts. See [docs/integration-standard.md](docs/integration-standard.md),
[docs/agent-contract.md](docs/agent-contract.md), [docs/integration.md](docs/integration.md),
[docs/scenario-reference.md](docs/scenario-reference.md), and [docs/adapter-reference.md](docs/adapter-reference.md).

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
    id: create-event
    action: api.request
    with:
      method: POST
      path: /api/demo/events
      json:
        type: session_started
    expect:
      status: 201
      json:
        status: processing
  - every: 1s
    until: 10s
    action: api.request
    with:
      method: POST
      path: /api/demo/heartbeat
    expect:
      status: 200
  - at: 11s
    action: lifecycle.complete
```

`at` and `every` accept `ms`, `s`, and `m`. Repeating events begin at their interval and include the event at `until` when it lands exactly on the boundary. Events at the same virtual time are ordered by their timeline position.

Every timeline item may provide an `id`; omitted IDs default to `step-<timeline index>`. Later items can reference earlier successful results with `${steps.<id>.*}`. `${env.NAME}` reads an environment variable and `${run.seed}` or `${run.run_id}` reads run metadata. A full placeholder preserves its native value; an embedded placeholder is rendered as text. Missing references fail the scenario clearly.

`expect.status` and `expect.json` validate HTTP results. `expect.json` performs a nested mapping-subset comparison. `expect.exit_code` validates command results. `expected_status` remains accepted inside `api.request.with` for M0 compatibility; new scenarios should use `expect`.

## Determinism

Every scenario run has a run-local `DeterministicRNG`, seeded from `--seed`. The state records the scenario name, canonical scenario hash, seed, run ID, scenario version, virtual start time, and event sequence. Adapter processes receive `DEVSIM_SEED`, `DEVSIM_RUN_ID`, `DEVSIM_PROJECT`, `DEVSIM_SCENARIO`, and `DEVSIM_VIRTUAL_TIME_MS`.

The run ID and wall-clock timestamps are intentionally unique per invocation. Random values, schedule expansion, event ordering, and project-provided deterministic behavior are reproducible for the same scenario and seed.

`devsim scenario inspect <run_id>` reads the JSONL artifact without changing the application. `devsim scenario replay <run_id>` re-runs the current scenario using the original seed. Replay compares the stored scenario hash with the current scenario and fails with `SCENARIO_CHANGED` unless `--allow-changed-scenario` is explicit. A replay always receives a new run ID.

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
