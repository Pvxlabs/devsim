# DevSim Agent Contract

`--json` is the canonical machine interface. Agents should use process exit
codes together with the stable JSON `error.code`; they should not parse human
stderr. Successful commands retain their command-specific v1 JSON fields.

## Required Workflow

```text
Discovery:  devsim capabilities --json
            devsim detect --json
            devsim project status --json
Preflight:  devsim doctor --json
Preview:    devsim preview <profile> --seed 42 --json
Observe:    devsim preview status --json
            devsim scenario inspect <run_id> --json
Shutdown:   devsim preview stop --json
```

`project status` reports integration completeness. `doctor` reports current
runtime and environment health. `preview status` reports the active canonical
preview and its evidence readback.

## Stable Discovery

`devsim capabilities --json` reports supported manifest/scenario versions,
adapters, seed modes, runtime controls, observations, and control surfaces.
`devsim detect --json` is read-only and describes the current repository.

## Agent Safety

Agents MUST:

- use a canonical project scenario when one exists;
- prefer real application paths for runtime evolution;
- treat browser `BLOCKED` or unavailable as blocked, never as `PASS`;
- keep production and real exchange endpoints out of DevSim operations;
- inspect the run artifact when evidence is relevant;
- stop a managed preview when finished.

Agents MUST NOT:

- invent runtime rows when a canonical scenario exists;
- bypass the real application path for runtime evolution;
- use DevSim against production;
- commit `.devsim/` runtime artifacts, screenshots, credentials, or database dumps.

## Exit Codes

`0` success, `1` operation failure, `2` configuration or validation error,
`3` unavailable environment dependency, and `4` safety rejection.

Machine errors use this shape:

```json
{"ok": false, "error": {"code": "INVALID_MANIFEST", "message": "...", "recoverable": false, "hint": "..."}}
```
