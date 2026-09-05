# Scenario Composition

Scenarios may include fragments relative to the configured scenario directory:

```yaml
version: 1
name: active-runtime
include:
  - baseline.yaml
  - updates.yaml
timeline:
  - at: 0s
    action: lifecycle.start
```

Includes are merged in listed order, nested includes are supported, and the
final canonical merged document determines the scenario hash. Include paths
must remain inside the configured scenario root. Cycles and duplicate step IDs
are rejected. Fragments without a `name` are include-only and are omitted from
`scenario list`.

