# Runtime Context

The run-scoped context store is deliberately domain-neutral:

```yaml
- at: 0s
  action: context.set
  with: {key: workload_level, value: normal}
- at: 1s
  action: context.increment
  with: {key: counter, amount: 1}
```

Values can be referenced with `${context.workload_level}`. `context.unset` is
also available. Generated values use the run seed and are exposed as
`steps.<id>.value`:

```yaml
- at: 2s
  id: sample
  action: value.generate
  with: {type: choice, choices: [low, normal, high]}
```

Supported types are `integer`, `float`, `choice`, and deterministic `uuid`.

