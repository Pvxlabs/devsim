# Adapter Reference

## Public Stable Adapters

### `api.request`

The HTTP adapter uses the manifest's `runtime.base_url` and accepts:

```yaml
with:
  method: POST
  path: /api/events
  headers:
    Content-Type: application/json
  json:
    type: started
  timeout: 30
```

Methods are `GET`, `POST`, `PUT`, `PATCH`, and `DELETE`. Response data includes `status`, `headers`, `json`, and compatibility field `body`. Transport failures are adapter failures. Response status and body validation belong in `expect`.

For M0 compatibility, `with.expected_status` and the older top-level `with.status` are still accepted by the HTTP adapter.

### `command.run`

The command adapter executes a project-owned shell command in the configured project directory or `with.cwd`:

```yaml
with:
  command: python scripts/preview_check.py
  cwd: .
  timeout: 120
  env:
    PREVIEW_MODE: "1"
```

The adapter passes `DEVSIM_SEED`, `DEVSIM_RUN_ID`, `DEVSIM_PROJECT`, `DEVSIM_SCENARIO`, and `DEVSIM_VIRTUAL_TIME_MS`. Results include `stdout`, `stderr`, and `exit_code`. Use `expect.exit_code` for scenario validation.

## Registry

The runner resolves the complete action name through an `AdapterRegistry`:

```python
registry.register("api.request", http_adapter)
registry.register("command.run", command_adapter)
```

Unknown actions and duplicate registrations fail deterministically. The old `get("api")` and `get("http")` lookups remain compatibility aliases for callers using the M0 Python API.

## Internal

`lifecycle.start` and `lifecycle.complete` are internal builtin markers used by the scenario runner. They do not start or stop application processes; lifecycle operations are configured separately in `devsim.yaml`.

DevSim currently has no SQL or WebSocket adapter. External projects should use their real HTTP/application command path unless evidence from a concrete integration establishes a generic adapter gap.
