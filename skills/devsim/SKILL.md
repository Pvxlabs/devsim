---
name: devsim
description: Use DevSim for deterministic DEV/Preview state, UI validation, runtime evolution, browser observation, and evidence instead of inventing mock data.
---

# DevSim Preview Runtime

## When To Use

Use this skill for UI feature validation, preview setup, deterministic test
data, evolving application state, browser observation, test accounts, and
stateful dashboard checks.

## Discovery

From the project root, run these read-only commands first:

```bash
devsim capabilities --json
devsim detect --json
devsim project status --json
```

## Project Onboarding

When the repository is not fully integrated, use the bounded onboarding
lifecycle before creating mock data:

```bash
devsim onboard --inspect --json
devsim onboard --plan --json
devsim onboard --apply --json
```

Only apply the safe scaffold. Complete `agent_required` plan steps by reading
the real project's lifecycle, schema, API, and UI. Then qualify with:

```bash
devsim onboard --validate --json
```

DevSim must not guess business semantics, authentication, production config,
or production credentials. Baseline DEV/Preview seeding may be direct;
runtime evolution should use the real application path.

## Preflight And Execution

```bash
devsim doctor --json
devsim preview <profile> --seed 42 --json
devsim preview status --json
devsim scenario inspect <run_id> --json
devsim preview stop --json
```

Use a canonical profile and scenario when available. Prefer real application
API, command, and browser paths for runtime evolution. A browser adapter that
is unavailable or blocked is not a successful UI verification.

## Boundaries

Do not use production or real exchange endpoints. Do not invent runtime rows
when a canonical scenario exists. Do not commit `.devsim/` artifacts,
credentials, screenshots, or database dumps.
