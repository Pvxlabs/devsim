# DevSim Product Contract Audit

Audit date: 2026-09-05

This document records the product contract before the Productization & Agent
Integration work. It is intentionally an audit, not a promise that every
desired product surface already exists.

## Authority And Compatibility

The released DevSim v0.1.0 implementation is the authority for existing v1
behavior. In particular, the shipped manifest uses `runtime.base_url`,
`runtime.adapters`, `seed.command` or schema-aware `seed` mappings,
`scenarios.path`, and `observation.browser.pages`. New documentation must fit
those fields. The illustrative manifest in the productization request is not
allowed to silently redefine the existing v1 schema.

Existing CLI and JSON shapes remain backward-compatible unless a new command
is explicitly introduced. New machine-readable contracts may add fields, but
must not remove fields that existing callers consume.

## Stable Public Contract

The following surfaces are implemented, tested, and treated as public in v1:

- Manifest `version: 1` and scenario `version: 1`.
- CLI commands `init`, `up`, `down`, `reset`, `seed`, `status`, `doctor`,
  `schema inspect`, `seed plan`, and `seed validate`.
- Scenario commands `list`, `validate`, `run`, `start`, `pause`, `resume`,
  `stop`, `reset`, `inspect`, and `replay`.
- `clock status`, `serve`, and the `preview <profile> --seed <integer>`
  entrypoint.
- `api.request`, `command.run`, `websocket.expect`, and configured browser
  actions, plus the built-in lifecycle markers.
- YAML scenario fields `at`, `every`, `until`, `action`, `with`, `expect`, and
  step IDs/context references.
- Deterministic run-local seed behavior and replay identity.
- Redacted JSONL artifacts under `.devsim/runs/<run_id>.jsonl`.
- Local safety checks for reset, seed, down, database targets, and observation
  URLs.
- Schema-aware PostgreSQL seed planning and deterministic profile seeding.
- Persistent runtime ownership, heartbeat, pause/resume, and stale-runtime
  detection.
- Local control API/UI and optional browser observation with screenshots.

## Experimental Or Project-Owned Contract

These are deliberately owned by the integrating repository rather than by
DevSim Core:

- Database lifecycle commands and application startup behavior.
- Custom seed commands, schema-aware seed plans, migrations, and credentials.
- Scenario helper commands, application routes, selectors, and assertions.
- Domain semantics, authentication, authorization, and business state.
- Browser page configuration and the application's visual contract.

DevSim orchestrates and observes these contracts. It does not implement the
application's business logic.

## Internal Contract

The following implementation details are not integration APIs:

- `.devsim/` state, runtime ownership, heartbeat, and artifact layout.
- Lifecycle marker adapter internals.
- The managed runtime process command line and process ownership metadata.
- Python module and class names under `devsim/` unless explicitly documented.

Agents may inspect `.devsim` evidence through DevSim commands, but must not
invent or mutate those files directly.

## Stale Documentation

`docs/integration.md` currently says:

> DevSim does not connect to PostgreSQL directly and does not write application rows.

That sentence is stale after schema-aware seeding landed. The replacement
contract is:

- **Baseline initialization:** direct DEV/Preview PostgreSQL seeding is allowed
  when the manifest opts into schema-aware seed mode and safety checks pass.
- **Runtime evolution:** prefer the real application API, command, or browser
  path so application behavior, validation, and side effects remain real.

The old statement must not be repeated in README, integration documentation,
CLI help, Skill guidance, or agent examples.

## Missing Product Contract

The following surfaces are absent or incomplete at the start of this phase:

- Read-only project discovery: `devsim detect`.
- Capability discovery: `devsim capabilities`.
- Integration completeness: `devsim project status` and `project validate`.
- Product bootstrap: `init --dry-run` and heuristic `init --inspect`.
- Canonical preview readback and shutdown: `preview status` and `preview stop`.
- A documented exit-code contract distinct from JSON error codes.
- A complete stable machine-readable error envelope with recoverability/hints.
- Standard integration, agent, CI, and AGENTS.md documents.
- Repository integration template and minimal GitHub Actions example.
- Repository-provided `skills/devsim/SKILL.md` using the current Agent Skills
  convention.
- A documented installation/discovery path for that Skill; no private runtime
  Skill protocol should be invented before the host ecosystem requires one.
- Fresh-session dogfood proving discovery does not depend on conversation
  context.

## Productization Guardrails

The implementation that follows this audit must preserve these boundaries:

1. Read-only discovery and dry-run commands do not create or modify files,
   databases, processes, or application state.
2. Preview commands target development/preview environments only and never
   production or real exchanges.
3. Direct database writes are limited to baseline initialization under the
   schema-aware seed contract; evolving runtime state uses the real application
   path whenever available.
4. Browser `BLOCKED` or unavailable is not a UI pass.
5. `.devsim/` runtime artifacts, credentials, screenshots, and database dumps
   are not committed.
6. Product status answers integration completeness; doctor answers current
   environment/runtime health.

