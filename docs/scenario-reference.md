# Scenario Reference

## Top-Level Fields

```yaml
version: 1
name: active-session
description: Optional human-readable text.
clock:
  speed: 10
timeline: []
```

`version` and `name` are required. `clock.speed` must be positive and defaults to `1`.

## Timeline Items

Each item contains exactly one of `at` or `every`:

```yaml
timeline:
  - at: 0s
    id: start
    action: lifecycle.start
  - every: 1s
    until: 5s
    id: heartbeat
    action: api.request
    with:
      method: GET
      path: /api/health
    expect:
      status: 200
```

Supported durations are integer or decimal values with `ms`, `s`, or `m`. Repeating items require `until`; the boundary is inclusive. Same-time events retain timeline order.

`id` identifies the result for later context references. IDs must be non-empty and unique within a scenario. If omitted, the parser assigns `step-<index>`.

## Context References

The supported syntax is deliberately small:

```yaml
with:
  headers:
    Authorization: Bearer ${env.API_TOKEN}
  path: /sessions/${steps.create-session.json.id}/events
  seed: ${run.seed}
```

Supported roots are `env`, `run`, and `steps`. A full placeholder preserves the referenced value's native type. Embedded placeholders become strings. Missing values and unsupported expressions fail with a structured context error. The resolver does not evaluate Python, Jinja, or other executable expressions.

HTTP results expose `status`, `headers`, and `json` (with `body` retained for compatibility). Command results expose `stdout`, `stderr`, and `exit_code` (with `returncode` retained for compatibility).

## Expectations

```yaml
expect:
  status: 201
  json:
    status: processing
    metadata:
      accepted: true
```

`status` accepts an integer or list of integers. `json` requires a mapping and compares nested mappings as a subset. `exit_code` requires an integer. Any expectation failure stops the run and marks the runtime state as failed. A scenario is completed only after every scheduled action and declared expectation succeeds.

`expected_status` inside `with` is a legacy M0 compatibility field for `api.request`; prefer `expect.status`.
