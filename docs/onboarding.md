# DevSim Onboarding

DevSim can be added to an existing development repository without changing
application business code.

## Human Workflow

From the project root:

```bash
devsim detect
devsim onboard
devsim project validate --json
devsim doctor --json
devsim preview normal --seed 42
```

Review generated files and complete the project-owned lifecycle, seed,
scenario, preset, and browser configuration before treating the integration
as ready. `devsim onboard --dry-run` is not required: use the read-only
inspection and planning commands when a preview of changes is needed.

## Agent Workflow

Agents should use the machine-readable contract:

```bash
devsim capabilities --json
devsim detect --json
devsim onboard --inspect --json
devsim onboard --plan --json
devsim onboard --apply --json
devsim onboard --validate --json
```

The apply step creates only missing standard scaffold files. Agents must read
the real application before completing project-owned integration and must use
the real application path for runtime evolution. Never target production or
commit `.devsim/` runtime artifacts.

See [onboarding-agent-contract.md](onboarding-agent-contract.md) for the
complete machine-readable onboarding contract.
