# CI Integration

CI should validate project-owned integration without requiring a browser or a
long-running runtime:

```bash
devsim project validate --json
devsim scenario validate --all --json
devsim seed validate --profile normal --json
```

When CI provides an isolated PostgreSQL service, a smoke preview may be added:

```bash
devsim preview minimal --seed 42 --json
devsim preview stop --json
```

Browser observation is recommended for a dedicated UI job, not as a requirement
for every integration check. Never point CI at production or a shared database.
