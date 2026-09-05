# Persistent Runtime

`scenario run` is a foreground finite execution. `scenario start` is a
managed process for persistent previews. The managed process owns one project
runtime, writes heartbeats and appends the same redacted JSONL artifact used by
finite runs.

```yaml
version: 1
name: active-runtime
clock: {speed: 10}
runtime:
  mode: persistent
  limits:
    max_events: 10000
    max_virtual_duration: 24h
timeline:
  - at: 0s
    action: lifecycle.start
  - every: 5s
    action: api.request
    with: {method: GET, path: /health}
```

Use `scenario pause`, `scenario resume`, and `scenario stop` to control it.
Pause freezes virtual time and recurring scheduling. A dead process is reported
as `STALE`; replay starts from the deterministic beginning rather than guessing
an event checkpoint.

