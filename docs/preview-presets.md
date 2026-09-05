# Preview Presets

Presets combine a seed profile and a persistent scenario into one repeatable
preview entry point:

```yaml
presets:
  normal:
    seed_profile: normal
    scenario: active-runtime
```

Run one with:

```bash
devsim preview normal --seed 42 --json
```

The command performs reset, migrate, seed, and managed scenario start in that
order. The selected seed is passed unchanged to both the seed operation and the
runtime. A preset must name an existing persistent scenario. Presets are project
configuration, not a second scenario language.

## Recommended Semantic Names

Projects may implement the profiles that fit their domain. The recommended
names have these meanings:

- `empty`: schema only, with no meaningful application data.
- `minimal`: the minimum valid application state.
- `normal`: representative normal usage.
- `active`: application state that is actively evolving at runtime.
- `degraded`: a safe simulated degraded state.
- `ui-stress`: high-density data intended to exercise UI limits.

These names are semantic guidance, not a requirement that every project
implement all six profiles. DevSim Core does not assign domain-specific
meaning such as trading behavior to a profile.
