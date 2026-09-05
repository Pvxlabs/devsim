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
